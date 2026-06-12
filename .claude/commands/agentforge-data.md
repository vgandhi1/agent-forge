---
description: AgentForge — build a validated factory data layer for a goal
argument-hint: [data goal]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **data** preset (PM intake → Data Engineer builds ingestion, data contracts, ETL/ELT, and
quality validation → QA verifies the pipeline + quarantines bad rows):

```bash
uv run python main.py --preset data --goal "$ARGUMENTS"
```

Contract-first foundation for `/agentforge-ml` and `/agentforge-factory`.
If `$ARGUMENTS` is empty, ask for the data sources + downstream use first.
