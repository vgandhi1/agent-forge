# Changelog

Document **user-visible** changes (CLI flags, behavior, public docs, breaking renames of user-facing concepts). **Skip** entries for internal-only refactors—e.g. module/symbol renames or log identifiers that do not change how users run AgentForge.

## 0.2.4 — 2026-06-06

- **Agents:** Multi-turn tool loop. Agents now execute a tool, feed the result back to the model, and continue across turns until the work is done — so large jobs (e.g. the Backend's 20+ files) complete in full instead of being truncated into a single response. All file-writing roles (PM, Architect, Backend, QA, DevOps) use the loop, including revision passes. Works on both Anthropic and Ollama; prompt caching preserved.
- **Review gate:** New independent Reviewer agent. It reads the actual files an agent produced (not a truncated preview) and returns a structured verdict (approve / reject / escalate with specific fixes). The Lead now consults the Reviewer at the approval gate instead of self-approving. Unclear or missing verdicts default to *reject*; artifacts accepted after the max revision cycles are explicitly flagged as carrying unresolved findings rather than passing silently. Reviewer model is configurable per role (`AGENTFORGE_MODEL_REVIEWER` / `AGENTFORGE_OLLAMA_MODEL_REVIEWER`).
- **Plan gate:** With `--plan-gate` / `AGENTFORGE_PLAN_GATE`, the backend proposes a build plan for the Lead to confirm or redirect before writing code (default off).
- **Resume:** `--resume` skips phases already completed for the same goal, reading `handoff/checkpoint.json`. Each phase now writes a human-readable `handoff/<role>.md`.
- **Escalation:** Agents can escalate an ambiguous decision (`request_decision`) instead of guessing — recorded and surfaced at the deploy gate — and proceed with a labeled assumption so work isn't blocked.
- **Personas:** Each role prompt now has a named persona and values for richer behavior (cached, near-zero cost).
- **Context:** Upstream docs are condensed by relevant Markdown section instead of blunt byte slicing.
- **Scope lock:** Agents now defer out-of-scope discoveries instead of expanding the task. Every agentic step gets a `log_known_gap` tool and a scope-lock instruction; deferred items accumulate in `reports/known_gaps.md`. The Reviewer flags scope drift (work added beyond the brief) into the same log, and the deploy summary lists the deferred gaps.
- **Deploy gate:** After all phases, AgentForge runs a deploy gate — a pytest smoke verification of the generated app, an optional human sign-off (`--deploy-gate` / `AGENTFORGE_DEPLOY_GATE`, with `--auto-approve` for unattended runs), an optional commit of the generated `workspace/dailyease` app to its own git repo (`--deploy-commit` / `AGENTFORGE_DEPLOY_COMMIT`), and a `reports/deploy_record.md` record. Default is off, so existing autonomous runs are unchanged; a declined deploy ships nothing.

## 0.2.3 — 2026-05-10

- **README:** Clone/`cd agent-forge` example instead of a placeholder path.

## 0.2.2 — 2026-05-10

- **License:** MIT `LICENSE`; package metadata in `pyproject.toml`.
- **CI:** GitHub Actions workflow runs `uv sync --group dev` and `pytest`; README status badge.

## 0.2.1 — 2026-05-10

- **CLI:** Validate `--goal-file` (exists, regular file, readable); add `--verbose` / `--log-file` for `agentforge` logging.
- **Agents:** Retry Anthropic calls on rate limits, timeouts, connection errors, and 5xx (`AGENTFORGE_API_RETRIES`, default 4).
- **Bus:** Persist each published message to SQLite `message_log`; debug logs on publish.
- **Lead:** Phase-start logging (`agentforge.lead`).
- **Web UI:** Error responses include `code` + actionable `message` for clients.
- **TUI:** Cancel running job with `c`; clearer messages for exit codes 1 and signals.
- **Tests:** `tests/` with pytest for phases resolution, artifact path rules, message bus priority.
- **Docs:** Message bus notes + Mermaid sequence in `agents_plan.md`; troubleshooting blurb in `README.md`.
