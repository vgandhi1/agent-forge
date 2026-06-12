---
description: AgentForge — apply a known fix + covering test for a goal
argument-hint: [fix description]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **fix** preset (Backend applies the known fix → QA verifies + adds/updates tests) on an
existing repo. Point it at the repo with `--target-repo` (use `.` from inside it):

```bash
uv run python main.py --preset fix --target-repo . --goal "$ARGUMENTS"
```

Use this when the fix is already known; for an unknown bug use `/agentforge-debug`.
If `$ARGUMENTS` is empty, ask what to fix first.
