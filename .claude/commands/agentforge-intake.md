---
description: AgentForge — requirements intake (PM only) for a goal
argument-hint: [goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **intake** preset (Product Manager → `workspace/docs/requirements.md`) from the repo root:

```bash
uv run python main.py --preset intake --goal "$ARGUMENTS"
```

If `$ARGUMENTS` is empty, ask for the goal first.
