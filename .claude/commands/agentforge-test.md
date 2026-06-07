---
description: AgentForge — QA tests + pytest run for a goal
argument-hint: [goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **test** preset (QA → pytest suite under `workspace/dailyease/tests` + `reports/qa_report.md`;
runs pytest and fixes failures). Expects the app to exist (`/agentforge-implement` or `/agentforge`):

```bash
uv run python main.py --preset test --goal "$ARGUMENTS"
```
