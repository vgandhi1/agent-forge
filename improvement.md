# AgentForge — improvement opportunities

Reviewed against the current codebase. Update this file as items ship.

---

## Completed (shipped)

| Item | Notes |
|------|--------|
| `--goal-file` validation | `cli._load_goal_file` — exists, file, readable; exit code 2 with safe messaging. |
| `--verbose` / `--log-file` | Root + `agentforge` loggers; stderr and optional file. |
| Anthropic resilience | Retries with backoff in `BaseAgent._call_anthropic` (`RateLimitError`, `APIConnectionError`, `APITimeoutError`, 5xx `APIStatusError`); `AGENTFORGE_API_RETRIES`. |
| Message `message_log` | `log_bus_message` in `core/memory.py`; called from `MessageBus.publish`. |
| Structured / machine-readable events | Initial step: `logging` on bus (debug) and Lead (phase_start); JSON event stream still optional. |
| Tests for AgentForge | `tests/test_cli_phases.py`, `test_artifact_store.py`, `test_message_bus.py` (pytest + pytest-asyncio). |
| Web UI error codes | `INVALID_JSON`, `INVALID_PRESET`, `EMPTY_GOAL`, `GOAL_TOO_LONG`, `MAIN_PY_MISSING`, `PROCESS_START_FAILED`. |
| TUI cancel + exit hints | `c` kills subprocess; exit code 1 hints API key / errors. |
| `agents_plan` bus + diagram | Implementation notes + Mermaid Lead↔worker sequence. |
| README troubleshooting | Short blurb → USAGE §7. |
| CHANGELOG | User-facing release notes in `CHANGELOG.md`; no need to log internal-only naming refactors (e.g. orchestrator symbol/logger names). |
| **LICENSE** | Root `LICENSE` (MIT) + `pyproject.toml` `license` metadata. |
| **CI** | `.github/workflows/ci.yml` (`uv sync --group dev`, `pytest`); README badge. |

**Still open (see sections below):** multi-turn tool loop, full JSON event stream, Bootstrap/Tailwind web UI, web auth when not loopback, TUI activity spinner, structured WebSocket progress.

---

## Review notes (accuracy)

| Item in prior list | Verdict |
|--------------------|--------|
| Web UI “wait for entire process” | **Partially wrong:** `web_ui.py` already streams **stdout line-by-line** over the WebSocket. A real gap is **structured progress** (phase name, agent role, Lead review) rather than only raw log lines. |
| README troubleshooting / preset examples | **Partially redundant:** [USAGE.md](USAGE.md) already covers troubleshooting and presets; README links there. Optional: one **short** “Common issues” blurb in README that points to USAGE. |
| `cli.py` phase validation | **Already present:** unknown roles in `--phases` fail in `_resolve_phases()`. |
| `goal-file` handling | **Done:** validated in CLI (see Completed). |

---

## High impact (core product)

- **Multi-turn tool loop:** execute tool → return results → continue until stop (large code drops).
- **Structured observability:** optional `AGENTFORGE_JSON_LOG` emitting one JSON object per line for phase/task events (beyond stderr logging).
- **Parallel phases** where safe (per `agents_plan` Phase 2).

---

## `web_ui.py`

- **Structured progress channel** if CLI emits phase events (typed WebSocket messages alongside `line`).
- **UX polish:** optional CSS framework; mobile-friendly log panel.
- **Security hardening if `--web-host` is non-loopback:** token gate or reverse-proxy note in docs.

---

## `cli.py` / `main.py`

- **`main.py`:** keep thin entry; docs in README/USAGE.

---

## `tui_main.py`

- **Activity indicator:** spinner while waiting on first line of output (optional).

---

## `agents_plan.md`

- Deeper **production / operations** for Phase 3 (orchestrator hosting, secrets, cost caps).

---

## `README.md`

- (Done: CI badge + MIT link.) Optional: add coverage or docs badges later.

---

## General / process

- Gather feedback and trim this list as items complete.

---

## Completed / intentionally out of scope (track elsewhere)

- See **Completed (shipped)** table at the top.
