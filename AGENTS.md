# AGENTS.md — driving AgentForge from any coding agent

This snippet is for generic coding agents (Codex, Aider, Continue, Cline, Windsurf, plain shell).
Claude Code users also have `.claude/commands/agentforge*.md`; Cursor users have
`.cursor/rules/agentforge.md`; VS Code users have `.vscode/tasks.json`.

## Contract

> AgentForge runs its **own** LLM pass. Your assistant should **not** duplicate implementation
> work — only launch, monitor, and summarize.

The host assistant's model and AgentForge's model are separate. Do not "become" AgentForge; invoke
it as a subprocess and report its output.

## Invocation

```bash
uv run python main.py --preset <preset> --target-repo <abs-repo-path> --goal "<task>"
```

| Preset | Phases | Use case |
|--------|--------|----------|
| `intake` | pm | Capture requirements |
| `design` | pm → architect | Requirements + architecture |
| `implement` | backend | Build to an approved design |
| `test` | qa | Add/refresh tests, run suite |
| `ship` | devops | Dockerfile, CI, runbook |
| `improve` | backend → qa | Refactor / polish per goal |
| `debug` | qa → backend → qa | Reproduce → patch → re-verify a bug |
| `fix` | backend → qa | Apply a known fix |
| `harden` | qa → backend → devops | Production readiness on an existing app |
| `full` | pm → architect → backend → qa → devops | Greenfield lifecycle |

## Flags worth knowing

- `--target-repo PATH` — operate on an existing repo; AgentForge metadata stays under `<PATH>/.agentforge`.
- `--dry-run` — show provider, gates, and phases, then exit.
- `--deploy-gate` / `--strict-review` — require sign-off / block on unresolved review findings.
- `--plan-gate` — backend proposes a plan before writing code.
- `--resume` — skip phases already completed for the same goal.

## Reading results

- Machine-readable: set `AGENTFORGE_JSON_LOG=1`, tail **stderr** (one JSON object per line).
- Human-readable: `<repo>/.agentforge/handoff/*.md` and `<repo>/.agentforge/reports/qa_report.md`.
