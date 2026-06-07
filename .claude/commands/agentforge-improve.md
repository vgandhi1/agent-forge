---
description: AgentForge — improvements pass (Backend + QA) for a goal
argument-hint: [goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **improve** preset (Backend refactor/perf + QA re-verify) on an existing app:

```bash
uv run python main.py --preset improve --goal "$ARGUMENTS"
```

If `$ARGUMENTS` is empty, ask what to improve first.
