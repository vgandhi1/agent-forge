# Changelog

Document **user-visible** changes (CLI flags, behavior, public docs, breaking renames of user-facing concepts). **Skip** entries for internal-only refactors—e.g. module/symbol renames or log identifiers that do not change how users run AgentForge.

## 0.2.4 — 2026-06-06

- **Agents:** Multi-turn tool loop. Agents now execute a tool, feed the result back to the model, and continue across turns until the work is done — so large jobs (e.g. the Backend's 20+ files) complete in full instead of being truncated into a single response. All six file-writing roles (PM, Architect, Backend, QA, DevOps) use the loop, including revision passes. Works on both Anthropic and Ollama; prompt caching preserved.

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
