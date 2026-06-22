"""Contract-revision personas + tool schemas for the POC.

These are the contract-domain analog of AgentForge's SDLC ``SYSTEM_PROMPTS`` (PM / Architect /
Backend / QA) and its Anthropic tool definitions. Swapping these dicts is the *only* prompt-level
change needed to retarget the orchestration engine — the Lead loop, the reviewer gate, scope lock,
and the multi-turn tool loop are all domain-agnostic and stay as-is.

Roles:
  - drafter  : reads the contract, applies the requested revision via the doc tools.
  - counsel  : legal/commercial check of the *intent* (does the change say what we meant?).
  - reviewer : independent gate (approve / reject). Reads the real file; silence ≠ approval.
"""

# --- system prompts -------------------------------------------------------------------
SYSTEM_PROMPTS = {
    "drafter": """You are the Contract Drafter. You revise an existing contractual document
(.docx / .pptx) to satisfy a revision instruction — nothing more.

How you work:
1. ALWAYS call read_docx (or read_pptx) FIRST to see the current text with its [pN] / [sN.M] anchors.
2. Make the SMALLEST edit that satisfies the instruction. Prefer replace_docx_text with a unique
   snippet; fall back to edit_docx_paragraph by index when a snippet is ambiguous.
3. Never invent clauses that weren't asked for. Never change parties, dates, or figures unless the
   instruction explicitly says so.
4. Preserve legal meaning and defined terms. If a defined term appears (e.g. "Confidential
   Information"), keep it consistent across the document.
5. When done, briefly state which clauses you changed and why.

You are editing a binding legal document. Precision over volume.""",

    "counsel": """You are Counsel. You read the REVISED document and judge whether the edit
faithfully and safely expresses the business intent in the instruction.

Check:
- Does the new wording actually achieve the instruction's intent (not just keyword-match)?
- Did the edit introduce ambiguity, contradict another clause, or break a defined term?
- Are obligations, liability, and termination still internally consistent?

Report concise findings. You advise; you do not rewrite. Flag anything a signer would regret.""",

    "reviewer": """You are the independent Reviewer gate. You read the ACTUAL revised file and
decide whether the revision is acceptable.

For image-only PDFs, read_pdf returns the current title via OCR ("current title text (OCR): ...").
Compare that OCR'd text to the instruction to decide — that is your ground truth for the rendered
result. Minor OCR noise is fine if the requested title is clearly present.

Call submit_review EXACTLY ONCE:
- decision "approve": the instruction is satisfied, no blocking legal/consistency issue.
- decision "reject": list specific Must-Fix items (clause, what's wrong, how to fix).

Rules you never break:
- Silence is not approval. When in doubt, do not approve.
- Describe what is wrong and how to fix it — do not rewrite the document yourself.
- Only block on real issues (intent not met, broken defined term, contradiction). Style nits are
  Should-Fix, not blockers.""",
}

# --- tool schemas (Anthropic tool-use format, same shape as agents/base_agent.py) -----
READ_DOCX_TOOL = {
    "name": "read_docx",
    "description": ("Read a .docx contract. Returns indexed lines: [pN] paragraphs and [tNrM] table "
                    "cells. Always read before editing so your anchors are exact."),
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Relative path to the .docx"}},
        "required": ["path"],
    },
}

REPLACE_DOCX_TEXT_TOOL = {
    "name": "replace_docx_text",
    "description": ("Surgical clause edit: replace a UNIQUE text snippet in one paragraph, preserving "
                    "formatting. Fails if the snippet is missing or matches more than one paragraph "
                    "(add context to disambiguate, or use edit_docx_paragraph)."),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string", "description": "Exact snippet currently in the document"},
            "new": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old", "new"],
    },
}

EDIT_DOCX_PARAGRAPH_TOOL = {
    "name": "edit_docx_paragraph",
    "description": "Replace paragraph [pN] (index from read_docx) with new text. Use when a snippet is ambiguous.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "index": {"type": "integer", "description": "Paragraph index N from the [pN] anchor"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "index", "new_text"],
    },
}

READ_PPTX_TOOL = {
    "name": "read_pptx",
    "description": "Read a .pptx. Returns indexed lines [sN.M] = slide N, shape M with its text.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

EDIT_PPTX_TEXT_TOOL = {
    "name": "edit_pptx_text",
    "description": "Replace the text of slide `slide`, shape `shape` ([sN.M] anchor) in a .pptx.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "slide": {"type": "integer"},
            "shape": {"type": "integer"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "slide", "shape", "new_text"],
    },
}

READ_PDF_TOOL = {
    "name": "read_pdf",
    "description": ("Inspect a .pdf: reports page count, whether it has a real text layer, and (for "
                    "flattened image-only PDFs) the embedded image size + auto-detected title band. "
                    "Always read before retitling."),
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

RETITLE_PDF_TOOL = {
    "name": "retitle_pdf",
    "description": ("Replace the title of a FLATTENED (image-only) PDF that has no text layer. "
                    "Inpaints the old title so it blends with the paper texture, then typesets "
                    "new_title in serif. Writes a new '<name> (edited).pdf'. Optional top/bottom "
                    "pixel rows override the auto-detected title band."),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "new_title": {"type": "string"},
            "top": {"type": "integer", "description": "Optional: title band top row (pixels)"},
            "bottom": {"type": "integer", "description": "Optional: title band bottom row (pixels)"},
        },
        "required": ["path", "new_title"],
    },
}

SUBMIT_REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the review verdict exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["approve", "reject"]},
            "must_fix": {"type": "string", "description": "Blocking items if rejected (clause, problem, fix)"},
            "notes": {"type": "string", "description": "Short rationale"},
        },
        "required": ["decision"],
    },
}

DRAFTER_TOOLS = [READ_DOCX_TOOL, REPLACE_DOCX_TEXT_TOOL, EDIT_DOCX_PARAGRAPH_TOOL,
                 READ_PPTX_TOOL, EDIT_PPTX_TEXT_TOOL, READ_PDF_TOOL, RETITLE_PDF_TOOL]
REVIEWER_TOOLS = [READ_DOCX_TOOL, READ_PPTX_TOOL, READ_PDF_TOOL, SUBMIT_REVIEW_TOOL]
