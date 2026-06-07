---
description: AgentForge — ship (DevOps: Docker, CI, deploy runbook) for a goal
argument-hint: [goal text]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **ship** preset (DevOps → Dockerfile, docker-compose, CI workflow, `docs/deployment.md`):

```bash
uv run python main.py --preset ship --goal "$ARGUMENTS"
```

Add `--deploy-gate` to require human sign-off, `--deploy-commit` to version the generated app.
