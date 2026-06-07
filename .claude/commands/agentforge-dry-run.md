---
description: AgentForge — show resolved config (provider, models, gates) without calling any API
argument-hint: [optional goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Show the resolved configuration (LLM provider, per-role models, gates, phases, goal) — **no API calls**.
Good first check before a real run:

```bash
uv run python main.py --dry-run --goal "${ARGUMENTS:-Build the MVP of DailyEase}"
```
