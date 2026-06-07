---
description: Run the AgentForge multi-agent pipeline (full lifecycle) for a goal
argument-hint: [goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run AgentForge's **full pipeline** (PM → Architect → Backend → QA → DevOps, with reviewer gating)
from the repository root.

```bash
uv run python main.py --goal "$ARGUMENTS"
```

- If `$ARGUMENTS` is empty, ask the Project Owner for the goal first (or run with the built-in default).
- First time? Ensure `uv sync` has run and `.env` is configured (Anthropic key or `AGENTFORGE_LLM_PROVIDER=ollama`).
- Local models are slow (minutes per phase) — let it run; artifacts land under `workspace/`.
- Preview without API calls: append `--dry-run`.

Sibling commands: `/agentforge-intake`, `/agentforge-design`, `/agentforge-implement`,
`/agentforge-test`, `/agentforge-ship`, `/agentforge-improve`, `/agentforge-resume`,
`/agentforge-artifacts`, `/agentforge-dry-run`.

Setup, flags, and local-model help: [USAGE.md](../../docs/USAGE.md) ·
[running-with-ai-clis.md](../../docs/running-with-ai-clis.md) · [ollama.md](../../docs/ollama.md).
