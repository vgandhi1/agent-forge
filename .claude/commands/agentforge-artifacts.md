---
description: AgentForge — list generated artifacts under workspace/
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

List everything AgentForge has written to `workspace/` (docs, the DailyEase app, reports, handoff):

```bash
uv run python main.py --list-artifacts
```
