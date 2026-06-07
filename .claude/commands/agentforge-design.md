---
description: AgentForge — design (PM + Architect) for a goal
argument-hint: [goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **design** preset (PM + Architect → requirements + `workspace/docs/architecture.md`):

```bash
uv run python main.py --preset design --goal "$ARGUMENTS"
```

If `$ARGUMENTS` is empty, ask for the goal first.
