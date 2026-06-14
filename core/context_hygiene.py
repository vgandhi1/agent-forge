"""Context hygiene: keep AgentForge's own runtime/config out of product artifacts.

Recorded "decisions" are replayed into every worker's dynamic context (see
``BaseAgent._build_dynamic_context``). A weak model sometimes records a decision about its
*execution environment* — the Ollama host, the WSL gateway, the LLM provider — which then
bleeds into a downstream brief and lands in the product spec (agentforge-failure.md, F4:
"focusing on integrating Ollama within Windows using WSL"). The framework's runtime is never
part of the product, so we strip those entries before they reach a worker.

Pure functions only (no I/O) so they are unit-testable.
"""
from __future__ import annotations

import re

# Markers of AgentForge's *own* execution environment — never part of any product spec.
# Deliberately narrow (framework infra, not generic infrastructure words like "windows" or
# "server") to avoid filtering legitimate product decisions.
_RUNTIME_MARKERS = re.compile(
    r"""(?ix)
    \bagentforge[_-] |        # AGENTFORGE_* env vars / config keys
    \bollama\b |
    \bwsl2?\b |
    \banthropic[_ ]?api[_ ]?key\b |
    \bllm[ _]provider\b |
    \bollama[ _]integration\b |
    \b127\.0\.0\.1\b |
    \blocalhost:\d+ |
    :11434\b |                # default Ollama port
    \bgguf\b |
    \bquant(?:ization|ized)\b |
    \bqwen[\d.]* |
    \bllama[\d.]+ |
    \bclaude-[a-z0-9-]+        # model tags
    """
)


def is_runtime_context(text: str) -> bool:
    """True if ``text`` references AgentForge's own runtime/config (model, host, provider, env)."""
    return bool(_RUNTIME_MARKERS.search(text or ""))


def sanitize_decisions(decisions: dict[str, str]) -> dict[str, str]:
    """Drop decision entries whose key or value leaks AgentForge's runtime/config.

    Returns a new dict with only product-relevant decisions. Entries that mention the model,
    Ollama/WSL host, provider, ports, or AGENTFORGE_* config are removed so they cannot be
    replayed into a worker's brief and copied into the product artifact (F4).
    """
    clean: dict[str, str] = {}
    for key, value in decisions.items():
        if is_runtime_context(str(key)) or is_runtime_context(str(value)):
            continue
        clean[key] = value
    return clean
