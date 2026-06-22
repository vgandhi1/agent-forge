"""Contract-revision POC orchestrator: Drafter → Counsel → Reviewer gate.

This is a self-contained, runnable proof that AgentForge's *architecture* (multi-turn tool loop +
independent reviewer gate + revision cycle) transfers to binary-document editing with only a new
tool layer (contracts/doc_tools.py) and new personas (contracts/personas.py). It deliberately does
NOT touch core/ or agents/, so the SDLC pipeline is unaffected.

Flow (mirrors the Lead → worker → Reviewer cycle in agents/lead.py):
    1. Drafter runs a multi-turn tool loop: read_docx → edit clause(s) → report.
    2. Counsel reviews intent (advisory).
    3. Reviewer reads the actual revised file and votes approve / reject.
    4. On reject, the Must-Fix notes feed back to the Drafter (bounded retries).

Modes:
    --dry-run   exercise the doc tools with NO LLM call (proves binary editing works offline).
    (default)   live: drives the loop with Anthropic. Needs ANTHROPIC_API_KEY.

Run:
    uv run python -m contracts.poc --dry-run
    uv run python -m contracts.poc --instruction "Extend the term from two (2) years to five (5) years."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from contracts.doc_tools import DocStore
from contracts.make_sample import make_sample_nda
from contracts import personas, llm

WORKSPACE = Path(__file__).parent / "workspace"
DOC_NAME = "sample_nda.docx"
MAX_TOOL_STEPS = 10
MAX_REVISION_CYCLES = 2


def _build_handlers(store: DocStore) -> dict:
    """Map tool name → callable(tool_input)->str. Same handler contract as base_agent."""
    return {
        "read_docx": lambda i: store.read_docx(i["path"]),
        "replace_docx_text": lambda i: store.replace_docx_text(i["path"], i["old"], i["new"]),
        "edit_docx_paragraph": lambda i: store.edit_docx_paragraph(i["path"], int(i["index"]), i["new_text"]),
        "read_pptx": lambda i: store.read_pptx(i["path"]),
        "edit_pptx_text": lambda i: store.edit_pptx_text(i["path"], int(i["slide"]), int(i["shape"]), i["new_text"]),
        "read_pdf": lambda i: store.read_pdf(i["path"]),
        "retitle_pdf": lambda i: store.retitle_pdf(i["path"], i["new_title"], i.get("top"), i.get("bottom")),
    }


# --------------------------------------------------------------------------------------
# Offline proof: no LLM, just drive the tools directly.
# --------------------------------------------------------------------------------------
def dry_run() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    doc_path = WORKSPACE / DOC_NAME
    make_sample_nda(doc_path)
    store = DocStore(WORKSPACE)
    print("=== BEFORE ===")
    print(store.read_docx(DOC_NAME))
    print("\n=== TOOL CALL: replace_docx_text (extend term 2y → 5y) ===")
    print(store.replace_docx_text(
        DOC_NAME,
        old="a period of two (2) years",
        new="a period of five (5) years",
    ))
    print("\n=== TOOL CALL: replace_docx_text (governing law CA → DE) ===")
    print(store.replace_docx_text(
        DOC_NAME,
        old="the State of California",
        new="the State of Delaware",
    ))
    print("\n=== AFTER (re-read from disk — proves the .docx was rewritten) ===")
    print(store.read_docx(DOC_NAME))


# --------------------------------------------------------------------------------------
# Live: drive a worker tool loop against Anthropic (shape mirrors base_agent.run_tool_loop).
# --------------------------------------------------------------------------------------
async def _tool_loop(client, system: str, user: str, tools: list[dict], handlers: dict,
                     max_steps: int = MAX_TOOL_STEPS) -> dict:
    is_ollama = llm.provider() == "ollama"
    messages = [{"role": "user", "content": user}]
    captured: dict = {}
    final_text = ""
    for _ in range(max_steps):
        if is_ollama:
            turn = await llm.chat_ollama(system, tools, messages)
        else:
            turn = await llm.chat_anthropic(client, system, tools, messages)
        messages.append(turn["assistant_msg"])
        final_text += turn["text"]
        pairs = []  # (call_id, output_str) for tool-result messages
        for call in turn["tool_calls"]:
            if call["name"] == "submit_review":
                captured = call["input"]
                out = "Review recorded."
            else:
                handler = handlers.get(call["name"])
                try:
                    out = handler(call["input"]) if handler else f"[unknown tool {call['name']}]"
                except Exception as e:  # never let a bad tool call kill the loop
                    out = f"[tool {call['name']} error: {e}]"
            print(f"  · {call['name']}({json.dumps(call['input'])[:90]}…) → {str(out)[:90]}")
            pairs.append((call["id"], str(out)))
        if not pairs:
            break
        if is_ollama:
            messages.extend(llm.tool_results_ollama(pairs))
        else:
            messages.append(llm.tool_results_anthropic(pairs))
    return {"final_text": final_text, "review": captured}


def _read_preview(store: DocStore, doc: str) -> str:
    """Provider-neutral 'read' for the BEFORE banner, dispatched on file type."""
    ext = doc.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return store.read_pdf(doc)
    if ext == "pptx":
        return store.read_pptx(doc)
    return store.read_docx(doc)


async def live_run(instruction: str, target: str | None, root: str | None) -> None:
    # Default target: generate the sample NDA under the POC workspace. Otherwise operate on an
    # existing file relative to --root (e.g. the Agents dir for test/mentally strong.pdf).
    if target:
        store = DocStore(root or ".")
        doc = target
    else:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        make_sample_nda(WORKSPACE / DOC_NAME)
        store = DocStore(WORKSPACE)
        doc = DOC_NAME

    handlers = _build_handlers(store)
    client = None
    if llm.provider() != "ollama":
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic()
    print(f"[provider={llm.provider()} model={llm.model()}]")
    print(f"Instruction: {instruction}\nDocument: {doc}\n")
    print("--- BEFORE ---")
    print(_read_preview(store, doc), "\n")

    notes = ""
    for cycle in range(1, MAX_REVISION_CYCLES + 1):
        print(f"=== Drafter (cycle {cycle}) ===")
        revision = (instruction if not notes
                    else f"{instruction}\n\nReviewer rejected the prior attempt. Must fix:\n{notes}")
        await _tool_loop(
            client, personas.SYSTEM_PROMPTS["drafter"],
            f"Revise the document '{doc}' per this instruction. Read it first with the right "
            f"read tool for its type.\n\nInstruction: {revision}",
            personas.DRAFTER_TOOLS, handlers,
        )

        print("\n=== Counsel (advisory) ===")
        counsel = await _tool_loop(
            client, personas.SYSTEM_PROMPTS["counsel"],
            f"Review the revised document '{doc}' against this intent: {instruction}",
            [personas.READ_DOCX_TOOL, personas.READ_PPTX_TOOL, personas.READ_PDF_TOOL], handlers,
        )
        print(f"  Counsel: {counsel['final_text'][:300]}")

        print("\n=== Reviewer (gate) ===")
        result = await _tool_loop(
            client, personas.SYSTEM_PROMPTS["reviewer"],
            f"Read '{doc}' and decide if this instruction is satisfied: {instruction}. "
            f"Call submit_review exactly once.",
            personas.REVIEWER_TOOLS, handlers,
        )
        review = result["review"]
        decision = review.get("decision", "reject")
        print(f"  Verdict: {decision.upper()} — {review.get('notes', '')}")
        if decision == "approve":
            print("\n--- AFTER (approved) ---")
            print(_read_preview(store, doc))
            return
        notes = review.get("must_fix", "") or review.get("notes", "")
        print(f"  Must-fix → looping back to Drafter: {notes}\n")

    print("\nMax revision cycles reached without approval.")


def main() -> None:
    try:  # match the main pipeline: read provider/model/keys from .env
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="Contract-revision agentic POC")
    ap.add_argument("--dry-run", action="store_true", help="Exercise doc tools without any LLM call")
    ap.add_argument("--instruction", default="Extend the term from two (2) years to five (5) years.",
                    help="The revision to apply")
    ap.add_argument("--target", help="Existing doc to revise (relative to --root). Omit to use the sample NDA.")
    ap.add_argument("--root", help="Sandbox root for --target (default current dir)")
    args = ap.parse_args()
    if args.dry_run:
        dry_run()
    else:
        asyncio.run(live_run(args.instruction, args.target, args.root))


if __name__ == "__main__":
    main()
