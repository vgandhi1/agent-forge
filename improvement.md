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

- **Multi-turn tool loop:** execute tool → return results → continue until stop (large code drops). **[done]** — see Ref gap #1 below.
- **Structured observability:** optional `AGENTFORGE_JSON_LOG` emitting one JSON object per line for phase/task events (beyond stderr logging).
- **Parallel phases** where safe (per `agents_plan` Phase 2).

---

## Reference gap analysis (vs. Three Man Team)

Gaps found by comparing AgentForge against `ref-agents/three-man-team` — a Claude Code
persona/methodology framework (human-in-loop, file handoffs, deploy gate). AgentForge is an
autonomous Python runtime (Anthropic/Ollama SDK, async bus, SQLite). This maps that framework's
*discipline* onto concrete AgentForge gaps. Ranked by impact.

### 1. Single-turn tool loop — highest priority **[done]**
**Where:** `agents/base_agent.py` — `_call_llm` / `_call_anthropic` / `_call_ollama`.
**Problem:** Each call did one `messages.create`, extracted `tool_use` blocks, stopped. No agentic
loop (execute tool → return `tool_result` → continue until `stop_reason != tool_use`). Backend was
asked to emit 23 files in one response (`backend_developer.py`) → model truncates, no in-turn recovery.
**Shipped:** Added `BaseAgent.run_tool_loop(user_message, tool_handlers, ..., max_steps)` —
calls the model, runs each requested tool via an async handler, feeds the result back as a
`tool_result` (Anthropic) or a follow-up user turn (Ollama), and repeats until the model stops
calling tools or `max_steps` is hit. Providers refactored into `_anthropic_create` / `_ollama_create`
operating on a growing messages list (system prompt + tools stay stable → prompt cache preserved).
Migrated all six file-writing agents (PM, Architect, Backend, QA, DevOps incl. revise paths) to the
loop. Tests: `tests/test_tool_loop.py` (iterate-then-stop, max_steps cap, handler-error surfaced).
*Unblocks #3 and #4.*

### 2. No human gate / deploy gate
**Where:** `lead.py` `run_development_cycle`, `devops_engineer.py`.
**Problem:** Fully autonomous, no human checkpoint, no deploy gate. DevOps writes Dockerfile/compose/CI
as artifacts but nothing commits, deploys, or confirms a deploy landed.
**Fix:** Optional approval pause before final phase (config-flagged); real commit/verify step in DevOps.

### 3. Lead review is a rubber stamp
**Where:** `lead.py` — `_review_artifact`.
**Problems:** reads only `content[:3000]` of one file (never the other ~22); `if not tool_used: approved = True`
(silence = pass); after `max_revisions` (3) auto-accepts regardless of quality.
**Fix:** Default to *reject* on silence; review the actual file set (ties to #1); max-revision fallthrough
becomes a flagged escalation, not a silent pass.

### 4. No independent reviewer role
**Where:** Agent roster (`agents/`), `lead.py`.
**Problem:** Lead is orchestrator AND reviewer (role conflict). QA only runs pytest; no spec-drift / correctness review.
**Fix:** Dedicated reviewer agent reading real files (not 3KB preview) for spec compliance, drift, security, logic.

### 5. No scope-lock / drift detection / Known-Gaps log
**Where:** All worker agents; review path in `lead.py`.
**Problem:** No drift check in review, nowhere to defer out-of-scope discoveries.
**Fix:** Persisted "known gaps" list; reviewer flags additions not in the task brief.

### 6. Crude context truncation vs. selective read
**Where:** `backend_developer.py` (`arch_content[:4000]`, `req_content[:2000]`), `lead.py` (`content_preview[:3000]`).
**Problem:** Hard byte-slicing drops information unpredictably.
**Fix:** Selective extraction (relevant sections / summaries) instead of fixed-length slices.

### 7. Personas are shallow
**Where:** `base_agent.py` — `SYSTEM_PROMPTS`.
**Problem:** Prompts are job descriptions, not characters. Reference argues persona > label ("vocabulary routing").
**Fix:** Add character framing per system prompt. Near-zero runtime cost (system blocks are cached).

### 8. No resumable, human-readable handoff artifacts
**Where:** Handoff is in-memory bus payloads + SQLite blob log.
**Problem:** No per-step brief / review / build-log on disk; no cross-session resume.
**Fix:** Emit per-phase markdown handoff files under `workspace/` + a checkpoint for multi-sprint resume
(also Phase 2 in `agents_plan.md`).

### 9. No "show plan before build" gate
**Where:** Worker agents jump from TASK_ASSIGN straight to producing artifacts.
**Fix:** Optional plan-confirm round between assignment and execution for non-trivial tasks.

### 10. No escalation channel
**Where:** `lead.py` decides everything; only signal back is reject notes.
**Fix:** Escalation message type so agents surface ambiguity instead of guessing.

### Recommended order
1. **#1 multi-turn tool loop** — foundational; complete artifacts.
2. **#3 + #4 real review** — meaningful only after #1.
3. **#2 deploy / human gate** — accountability before shipping.
4. **#5 scope lock** — drift control.
5. **#6–#10** — polish and resilience.

### Not adopting from Three Man Team
- **Exactly three agents** — AgentForge's six-role org is intentional; the reference's "resist a fourth"
  rule is about a different (single-session, human-driven) context.
- **GitHub release auto-update walkthrough** — reference-specific distribution mechanic, not relevant.

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
