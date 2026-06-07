---
description: AgentForge — implement the FastAPI app (Backend) for a goal
argument-hint: [goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **implement** preset (Backend → `workspace/dailyease/` app). Expects design docs to exist
(run `/agentforge-design` first, or use `/agentforge` for the full pipeline):

```bash
uv run python main.py --preset implement --goal "$ARGUMENTS"
```

Add `--plan-gate` to have the backend confirm a build plan before writing code.
