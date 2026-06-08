---
description: How to drive AgentForge from Cursor
alwaysApply: false
---

# AgentForge (Cursor rule)

AgentForge is a subprocess-driven multi-agent system that builds, tests, and hardens code.
It runs its **own** LLM pass. You (the Cursor assistant) should **not** duplicate its implementation
work — only launch it, monitor it, and summarize its results.

## Run it on the repo currently open

```bash
# From the AgentForge install dir; --target-repo points at THIS project.
uv run python main.py --preset <preset> --target-repo <abs-path-to-this-repo> --goal "<task>"
```

Common presets: `intake` `design` `implement` `test` `ship` `improve` `debug` `fix` `harden` `full`.

Examples:

```bash
# Reproduce → patch → re-verify a failing test in the open repo
uv run python main.py --preset debug --target-repo "$PWD" \
  --goal "pytest tests/test_auth.py::test_login fails with 401"

# Production-readiness pass on an existing app
uv run python main.py --preset harden --target-repo "$PWD" --goal "add health checks + CI"
```

## Useful flags

- `--target-repo PATH` — operate on an existing repo (metadata isolated under `<PATH>/.agentforge`).
- `--deploy-gate` — require sign-off before the deploy step.
- `--strict-review` — block deploy if any unresolved review finding (quality debt) remains.
- `--plan-gate` — backend shows a build plan before writing code.
- `--dry-run` — print provider, gates, and phases without running.
- `--resume` — skip phases already completed for the same goal.

## Consume results

Set `AGENTFORGE_JSON_LOG=1` and tail **stderr** — one JSON object per line
(`phase_complete`, `files_changed`, `review_verdict`, `pytest_result`, `exit_summary`).
Otherwise read `<repo>/.agentforge/handoff/*.md` and `<repo>/.agentforge/reports/qa_report.md`.
