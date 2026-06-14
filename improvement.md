# AgentForge Improvement Roadmap

Living checklist of improvements. Status keys: **[done]**, **[partial]**, **[open]**.

## Universal codebase operator (top priority)

The highest-leverage gap: make AgentForge operate on the caller's existing repo, not only the
greenfield `workspace/` sandbox.

| # | Item | Status |
|---|------|--------|
| A1 | `--target-repo` + split metadata vs code roots | **[done]** — `core/paths.resolve_roots`; metadata isolated under `<repo>/.agentforge` |
| A2 | `read_file` / `list_files` / `grep_code` on workers | **[done]** — injected via `BaseAgent.run_tool_loop(read_tools=True)` |
| A3 | Project profiles (`.agentforge/profile.yaml`) | **[done]** — `core/profile.py` |
| A4 | `debug` / `fix` / `harden` presets | **[partial]** — presets shipped; reproduce→patch→re-verify covered by `tests/test_debug_integration.py` (fixture repo with a known failing test); multi-stack soak still maturing |
| A5 | Profile-driven `verify_cmd` + commit target repo | **[partial]** — pytest path done (`tests/test_deploy_verify.py`, `tests/test_debug_integration.py`); npm/go soak open |

> **Now implemented:** A1 (target-repo mode), A2 (worker read/grep tools), project profiles
> (A3), and the preset surface (A4). These unblock real-world, repo-agnostic use.

## Core engineering checklist

1. Multi-turn tool loop — **[done]**
2. Independent Reviewer (reads real files; silence ≠ approval) — **[done]**
3. Deploy gate (verify → sign-off → commit) — **[done]**
4. Scope lock + Known Gaps log — **[done]**
5. Escalation channel for ambiguity — **[done]**
6. Context truncation → selective condensing — **[done]** — `condense_markdown` plus
   `doc_reference` (path-first: small digest + `read_file` pointer instead of large inlined blobs;
   `core/context.py`, wired into the backend worker)
7. Personas over labels — **[partial]** — eight named roles (PM, Architect, Backend, QA, DevOps,
   Data Engineer, AI/ML Engineer) + Reviewer; further persona depth open
8. File handoffs (`handoff/<role>.md` + checkpoint) — **[done]**
9. Plan-before-build gate (`--plan-gate`) — **[done]**
10. Escalation routing — **[done]** — recorded, surfaced at the deploy gate, and (with
    `--deploy-gate`) the Lead now pauses mid-phase for operator guidance
    (`LeadAgent._handle_escalation`; `tests/test_escalation_pause.py`)

## New roadmap items

11. **Target repo mode** — `--target-repo PATH`; resolve read/write/test/commit against the
    target tree, metadata under `<repo>/.agentforge`, path allowlist. **[done]**
12. **Worker read/grep tools** — `read_file` / `list_files` / `grep_code` on implementation
    agents so they can inspect before patching (bug-find / refactor). **[done]**
13. **Project profiles** — `.agentforge/profile.yaml` (stack, app_root, test_cmd, lint_cmd);
    `default` (DailyEase) and `discover` (infer from pyproject/package.json). **[done]**
14. **debug / fix / harden presets** — reproduce → localize → patch → verify workflows.
    **[partial]** — integration test on a fixture repo with a known failing test landed
    (`tests/test_debug_integration.py`); multi-stack soak still open.
15. **Agent eval suite** — `evals/` scenarios + `docs/evaluation.md`; maps to the eval
    roadmap's step 9 (pipeline outcomes, not just unit plumbing). **[done]** — fixture-based
    scenarios + committed `evals/fixtures/` trees graded deterministically by `run_evals.py`
    (now in CI); live-LLM evals deferred to Phase C.
16. **Host assistant rules** — `AGENTS.md` + adapted eval-roadmap steps 1–2 for Cursor/Codex
    users; dual-agent contract in README and slash commands. **[done]** — dual-agent
    contract in README; `AGENTS.md`, `.cursor/rules/agentforge.md`, and `.vscode/tasks.json`
    shipped.

## Structured machine output

- `AGENTFORGE_JSON_LOG` — one JSON event per line on stderr (`phase_complete`, `files_changed`,
  `review_verdict`, `pytest_result`, `exit_summary`) for host-assistant consumption.
  **[done]** — `core/events.py`; emitted by the Lead per phase/review; documented in
  `docs/running-with-ai-clis.md`. The Web UI parses these into typed progress
  (`web_ui._parse_event_line`; `tests/test_web_events.py`).

## Factory data & AI engineering team

- Two domain personas extend the org so AgentForge can build factory/industrial data & AI apps
  (predictive maintenance, anomaly detection, quality prediction). **[done]**
  - `data_engineer` — ingestion (streaming + batch), data contracts, idempotent ETL/ELT,
    storage model, data-quality validation (`agents/data_engineer.py`).
  - `ml_engineer` — feature engineering, baseline + model, leakage-free evaluation,
    input-validating inference on the data contracts (`agents/ml_engineer.py`).
  - Presets `data`, `ml`, `factory`; both roles profile-aware (`--target-repo`); wired into
    `VALID_ROLES`, the Lead `assign_task` enum, `cli.agents_map`, `web_ui.AGENT_ROLES`, eval
    `KNOWN_PRESETS`, and `agents/__init__.py` exports. Tests: `tests/test_factory_team.py`.
  - Eval coverage: `data_pipeline` scenario + committed fixture (`evals/fixtures/data_pipeline/`)
    grades the `data` preset's design-doc contract in CI (suite now 5/5).
- Open: domain-specific verify profiles (e.g. a `factory` profile with a data/ML `verify_cmd`),
  an `ml`-preset eval fixture, and a fixture-repo integration soak for `data`/`ml` (parallels A4).

## Per-phase guardrail hooks

- Optional `.agentforge/hooks/pre-phase` / `post-phase` executables run around every phase
  (eval roadmap step 7). Opt-in by presence, advisory (non-zero exit is surfaced, not fatal).
  **[done]** — `core/hooks.py`, wired in `LeadAgent._run_phase`; `tests/test_hooks.py`.

## Phase D: agentic core (shipped 2026-06-13)

Turns the orchestrator from a fixed-pipeline executor into an adaptive agent. All opt-in and
backward compatible (default = the old fixed pipeline). Suite green: 193 passed (14 new in
`tests/test_agentic.py`).

| # | Item | Status |
|---|------|--------|
| D1 | Execution feedback for all builders — `run_tests` / `run_lint` tools (`run_tool_loop(exec_tools=True)`), profile-driven, sandboxed to configured commands; wired into backend / data_engineer / ml_engineer | **[done]** — `agents/base_agent.py`, `core/deploy.run_verify` |
| D2 | Dynamic planning — Lead proposes the phase sequence from the goal (`_plan_phases` + `propose_plan` tool), seeded by the preset, fail-safe to seed | **[done]** — `agents/lead.py` |
| D3 | Adaptive re-routing — insert a follow-up phase on unresolved review findings / escalation (`_replan_after_phase` + `adjust_plan` tool); bounded by a replan budget + hard phase cap | **[done]** — `agents/lead.py` |
| D4 | Goal self-check — verify the goal is met before finishing, enqueue one bounded remediation round (`_verify_goal_met`) | **[done]** — `agents/lead.py` |
| D5 | CLI surface — `--adaptive` / `AGENTFORGE_ADAPTIVE=1`, shown in `--dry-run` | **[done]** — `cli.py` |

> Builders are now self-correcting (write → run_tests → read failures → fix → re-run), and the
> Lead plans/re-routes/goal-checks instead of executing a static list. This is the bridge from
> "multi-agent pipeline" to "agentic system". Factory presets (`data`/`ml`/`factory`) benefit
> directly: the data/ML builders can run their validation and reproducible-eval tests and iterate.

### Phase D — still open
- Patch-based edits (`edit_file` / `apply_patch`) instead of full-file rewrites (cheaper, safer on `--target-repo`).
- Semantic memory: top-k retrieval over the flat decisions log (`_build_dynamic_context`) instead of full replay.
- Parallel independent phases (needs workspace locking) and dynamic sub-agent spawning.

## Deferred (Phase C)

> See `feedback.md` Part 8 for advisability, dependencies, and recommended order. Implement
> individually on concrete pain, not as a batch.


- Parallel phases (needs workspace locking)
- Web search for API docs
- Optional container build smoke in the deploy gate
- Cost caps, webhooks, hosted orchestrator
- RAG / memory over the target repo (after `--target-repo` matures)
- Live-LLM evals (`pytest -m live`) as an optional nightly CI job
