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

### 2. No human gate / deploy gate **[done]**
**Where:** `agents/lead.py` `_finalize_sprint`, `core/deploy.py` (new), `cli.py`.
**Problem:** Fully autonomous, no human checkpoint, no deploy gate. DevOps wrote Dockerfile/compose/CI
as artifacts but nothing verified, committed, or confirmed a deploy.
**Shipped:** After all phases the Lead runs a deploy gate (`_finalize_sprint`):
1. **Verify** — `core.deploy.run_pytest_smoke` runs the generated app's tests as a smoke check
   (pass / fail / skipped).
2. **Human sign-off** — opt-in via `--deploy-gate` / `AGENTFORGE_DEPLOY_GATE`. Presents a summary
   (accepted artifacts, quality-debt flags, open escalations, verify result) and asks go/no-go.
   No TTY → does not approve (fail-safe); `--auto-approve` for unattended deploys. Default off →
   existing autonomous behavior unchanged.
3. **Commit** — opt-in via `--deploy-commit` / `AGENTFORGE_DEPLOY_COMMIT`: commits the generated
   `workspace/dailyease` app to its own git repo (init if needed; never touches the AgentForge repo).
4. **Record** — writes `reports/deploy_record.md` (timestamp, decision, verify status, commit, summary)
   and remembers the deploy decision. Declined deploys are recorded as `aborted` and ship nothing.
Tests: `tests/test_deploy_gate.py` (autonomous, declined, auto-approve+commit).

### 3. Lead review is a rubber stamp **[done]**
**Where:** `lead.py` — `_review_artifact`.
**Problems:** read only `content[:3000]` of one file (never the other ~22); `if not tool_used: approved = True`
(silence = pass); after `max_revisions` (3) auto-accepted regardless of quality.
**Shipped:** `_review_artifact` now delegates to the independent Reviewer (see #4), which reads the
actual file set. A missing verdict defaults to **reject** (silence is not approval). The max-revision
fallthrough in `_run_phase` no longer silently passes — it records a `quality_debt_<role>` decision,
logs a warning, and accepts with an explicit `ACCEPTED WITH UNRESOLVED REVIEW FINDINGS` flag so the
debt is visible. Reviewer `escalate` verdicts are recorded and bounced back with an escalation note.

### 4. No independent reviewer role **[done]**
**Where:** `agents/reviewer.py` (new), `lead.py`, `agents/base_agent.py` (persona).
**Problem:** Lead was orchestrator AND reviewer (role conflict). QA only runs pytest; no spec-drift / correctness review.
**Shipped:** New `ReviewerAgent` with its own persona prompt and model (`AGENTFORGE_MODEL_REVIEWER` /
`AGENTFORGE_OLLAMA_MODEL_REVIEWER`). It uses a `read_file` tool inside the multi-turn loop to read
only the files it needs, then `submit_review` with a structured verdict (approve / reject / escalate
+ must_fix / should_fix). Distinct from QA's test execution. The Lead instantiates it and consults it
at the approval gate. Tests in `tests/test_reviewer.py`.

### 5. No scope-lock / drift detection / Known-Gaps log **[done]**
**Where:** `core/known_gaps.py` (new), `agents/base_agent.py` (`run_tool_loop`), `agents/reviewer.py`, `agents/lead.py`.
**Problem:** No drift check in review, nowhere to defer out-of-scope discoveries.
**Shipped:** Persisted Known-Gaps log at `reports/known_gaps.md` (`core.known_gaps.log_gap`).
`run_tool_loop` now auto-injects a `log_known_gap` tool and a scope-lock instruction (default on;
`scope_lock=False` opts out) so any agent defers out-of-scope work instead of expanding the task.
The Reviewer's verdict gained a `drift` field — anything added beyond the brief is routed to the
Known-Gaps log. The Lead's deploy summary lists the deferred gaps. Tests in `tests/test_scope_lock.py`.

### 6. Crude context truncation vs. selective read **[done]**
**Where:** `core/context.py` (new), `backend_developer.py`, `architect.py`, `qa_engineer.py`, `devops_engineer.py`.
**Problem:** Hard byte-slicing (`arch_content[:4000]`, …) silently drops the entire tail of a doc.
**Shipped:** `core.context.condense_markdown` keeps whole Markdown sections, prioritizing those relevant
to the task (keyword-scored), fills remaining budget in document order, and labels what it dropped.
Wired into the backend/architect/qa/devops reads. (Lead's review preview gap was already removed in #3/#4.)
Tests in `tests/test_context.py`.

### 7. Personas are shallow **[done]**
**Where:** `base_agent.py` — `SYSTEM_PROMPTS`.
**Problem:** Prompts were job descriptions, not characters.
**Shipped:** Each role prompt now opens with a named persona + brief backstory and values (Mara/Priya/
Sol/Devon/Quinn/Ravi; Reviewer already had one). Responsibilities unchanged; system prompts are cached
so the framing is near-zero cost.

### 8. No resumable, human-readable handoff artifacts **[done]**
**Where:** `core/handoff.py` (new), `agents/lead.py`, `cli.py`.
**Problem:** Handoff was in-memory only — no per-step record, no cross-session resume.
**Shipped:** Each completed phase writes `handoff/<role>.md` (brief, files, review summary) and updates
`handoff/checkpoint.json` (goal fingerprint + completed phases + artifact refs; resets on goal change).
`--resume` skips phases already done for the same goal and restores their artifact refs. Tests in
`tests/test_handoff.py`.

### 9. No "show plan before build" gate **[done]**
**Where:** `agents/lead.py` (`_handle_plan_gate`), `agents/backend_developer.py` (`_propose_plan`), `cli.py`.
**Problem:** The backend jumped from TASK_ASSIGN straight to writing 20+ files.
**Shipped:** With `--plan-gate` / `AGENTFORGE_PLAN_GATE` (default off), the backend proposes a concise
build plan (CONSULT_REQUEST), the Lead approves or redirects (CONSULT_RESPONSE), and the backend folds
redirect notes in before writing code. Fail-open to avoid deadlock. Tests in `tests/test_plan_gate.py`.

### 10. No escalation channel **[done]**
**Where:** `agents/base_agent.py` (`request_decision` tool), `agents/lead.py`, `core/message_types.py`.
**Problem:** Agents could only guess; the Lead decided everything.
**Shipped:** `run_tool_loop` auto-injects a `request_decision` tool (alongside scope lock). A worker
escalates an ambiguous decision instead of guessing: it records the question + its stated assumption,
publishes a `MessageType.ESCALATION`, and proceeds with the labeled assumption. Escalations surface in
the deploy summary. Tests in `tests/test_escalation.py`.

### Recommended order
1. ~~**#1 multi-turn tool loop** — foundational; complete artifacts.~~ **[done]**
2. ~~**#3 + #4 real review** — meaningful only after #1.~~ **[done]**
3. ~~**#2 deploy / human gate** — accountability before shipping.~~ **[done]**
4. ~~**#5 scope lock** — drift control.~~ **[done]**
5. ~~**#6–#10** — polish and resilience.~~ **[done]**

**All 10 reference gaps shipped.**

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
