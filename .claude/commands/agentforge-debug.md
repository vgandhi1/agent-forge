---
description: AgentForge — reproduce, patch, and re-verify a bug for a goal
argument-hint: [bug description]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **debug** preset (QA reproduce → Backend localize & patch → QA re-verify + regression test)
on an existing repo. Point it at the repo with `--target-repo` (use `.` from inside it):

```bash
uv run python main.py --preset debug --target-repo . --goal "$ARGUMENTS"
```

If `$ARGUMENTS` is empty, ask for the failing behavior / test first.
