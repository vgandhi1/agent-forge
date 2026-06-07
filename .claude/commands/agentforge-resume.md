---
description: AgentForge — resume a goal, skipping phases already completed
argument-hint: [the same goal text as the original run]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Resume the full pipeline, skipping phases already completed for **this goal** (reads
`workspace/handoff/checkpoint.json`). The goal must match the original run:

```bash
uv run python main.py --resume --goal "$ARGUMENTS"
```

If `$ARGUMENTS` is empty, ask for the goal (it must match the interrupted run).
