"""Tiny provider adapter for the POC — Anthropic or Ollama, same as AgentForge supports.

Normalizes one chat turn to: given (system, tools, native messages), return
``{"text", "tool_calls": [{id,name,input}], "assistant_msg"}`` and append the assistant turn +
tool results in the provider's native message shape. Keeps poc.py provider-agnostic.
"""

from __future__ import annotations

import json
import os

import httpx


def provider() -> str:
    return os.getenv("AGENTFORGE_LLM_PROVIDER", "anthropic").strip().lower()


def model() -> str:
    if provider() == "ollama":
        return os.getenv("AGENTFORGE_OLLAMA_MODEL", "qwen2.5:7b-instruct")
    return os.getenv("AGENTFORGE_MODEL", "claude-opus-4-8")


# --- Anthropic --------------------------------------------------------------------------
async def chat_anthropic(client, system, tools, messages) -> dict:
    resp = await client.messages.create(
        model=model(), max_tokens=4000, system=system, tools=tools, messages=messages,
    )
    text, calls = "", []
    for block in resp.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use":
            calls.append({"id": block.id, "name": block.name, "input": block.input})
    return {"text": text, "tool_calls": calls, "assistant_msg": {"role": "assistant", "content": resp.content}}


def tool_results_anthropic(pairs) -> dict:
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": cid, "content": out} for cid, out in pairs
    ]}


# --- Ollama -----------------------------------------------------------------------------
def _to_ollama_tools(tools) -> list:
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["input_schema"],
    }} for t in tools]


async def chat_ollama(system, tools, messages) -> dict:
    host = os.getenv("AGENTFORGE_OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": model(),
        "messages": [{"role": "system", "content": system}] + messages,
        "tools": _to_ollama_tools(tools),
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{host}/api/chat", json=payload)
        r.raise_for_status()
        msg = r.json()["message"]
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc["function"]
        args = fn["arguments"]
        if isinstance(args, str):
            args = json.loads(args or "{}")
        calls.append({"id": fn["name"], "name": fn["name"], "input": args})
    return {"text": msg.get("content", ""), "tool_calls": calls,
            "assistant_msg": {"role": "assistant", "content": msg.get("content", ""),
                              "tool_calls": msg.get("tool_calls") or []}}


def tool_results_ollama(pairs) -> list:
    # Ollama takes one message per tool result.
    return [{"role": "tool", "tool_name": cid, "content": out} for cid, out in pairs]
