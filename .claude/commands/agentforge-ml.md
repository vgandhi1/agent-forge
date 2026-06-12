---
description: AgentForge — build an industrial ML layer on validated data for a goal
argument-hint: [ML goal]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **ml** preset (PM intake → Data Engineer data layer → ML Engineer features + baseline/model
+ time-ordered eval + input-validating inference → QA verifies eval reproducibility and serving):

```bash
uv run python main.py --preset ml --goal "$ARGUMENTS"
```

Builds on contracts from `/agentforge-data`. For the full data + AI + API lifecycle use
`/agentforge-factory`. If `$ARGUMENTS` is empty, ask for the problem + success metric first.
