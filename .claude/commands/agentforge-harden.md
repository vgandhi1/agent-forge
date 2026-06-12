---
description: AgentForge — production-readiness pass for an existing app
argument-hint: [hardening goal]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **harden** preset (QA audit & test → Backend patch gaps → DevOps production readiness) on an
existing repo. Point it at the repo with `--target-repo` (use `.` from inside it):

```bash
uv run python main.py --preset harden --target-repo . --goal "$ARGUMENTS"
```

Closes reliability, edge-case, error-handling, and operational gaps without changing intended
behavior. If `$ARGUMENTS` is empty, ask for the hardening focus first.
