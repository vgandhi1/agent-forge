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
7. Personas over labels — **[partial]** — six named roles; further persona depth open
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

## Per-phase guardrail hooks

- Optional `.agentforge/hooks/pre-phase` / `post-phase` executables run around every phase
  (eval roadmap step 7). Opt-in by presence, advisory (non-zero exit is surfaced, not fatal).
  **[done]** — `core/hooks.py`, wired in `LeadAgent._run_phase`; `tests/test_hooks.py`.

## Deferred (Phase C)

> See `feedback.md` Part 8 for advisability, dependencies, and recommended order. Implement
> individually on concrete pain, not as a batch.


- Parallel phases (needs workspace locking)
- Web search for API docs
- Optional container build smoke in the deploy gate
- Cost caps, webhooks, hosted orchestrator
- RAG / memory over the target repo (after `--target-repo` matures)
- Live-LLM evals (`pytest -m live`) as an optional nightly CI job
