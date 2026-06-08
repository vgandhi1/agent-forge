# Changelog

Document **user-visible** changes (CLI flags, behavior, public docs, breaking renames of user-facing concepts). **Skip** entries for internal-only refactors—e.g. module/symbol renames or log identifiers that do not change how users run AgentForge.

## Unreleased — operator soak & eval hardening (P1 + P2)

Follow-through on the `feedback.md` P1/P2 action plan. All additive and backward compatible.

- **Per-phase guardrail hooks:** drop an executable at `.agentforge/hooks/pre-phase` or
  `.agentforge/hooks/post-phase` and AgentForge runs it around every phase, with
  `AGENTFORGE_PHASE_ROLE` and `AGENTFORGE_HOOK_STAGE` in the environment — for a lint or
  pytest smoke without waiting for the deploy gate. Opt-in by presence and advisory: a
  non-zero exit is surfaced but does not abort the sprint. (`core/hooks.py`)
- **Mid-sprint escalation pause:** with `--deploy-gate`, when a phase escalates an ambiguous
  decision the Lead now invites operator guidance mid-sprint (recorded for the team) instead
  of only surfacing it at the deploy gate. Without a TTY it records nothing and continues, so
  unattended runs never block.
- **Web UI typed progress:** the browser UI launches the run with `AGENTFORGE_JSON_LOG=1` and
  parses the JSON events on stderr (`phase_complete`, `review_verdict`, `files_changed`, …)
  into structured `event` messages, instead of streaming only raw log lines. The Lead now
  emits `phase_complete` and `review_verdict` events per phase.
- **Deterministic eval grading:** scenarios with an artifact contract commit a fixture tree
  under `evals/fixtures/` and reference it with a `fixture:` key, so `evals/run_evals.py`
  grades the real artifact/section contract in CI without a live run. `--workspace` still
  overrides to grade a produced run. CI now runs the eval suite after the unit tests, and
  `KNOWN_PRESETS` recognizes `debug` / `fix` / `harden`.
- **Eval path fix:** `intake_requirements` now grades `docs/requirements.md` (the path runs
  actually produce), not `requirements.md`.
- **Debug-preset integration test:** a committed fixture repo with a known failing test
  (`tests/fixtures/broken_calc/`) verifies the reproduce → patch → re-verify loop against a
  real `verify_cmd` (`tests/test_debug_integration.py`).
- **Docs:** `docs/evaluation.md` steps 2, 7, 8, 9 refreshed (hooks shipped, fixtures, CI eval,
  `AGENTS.md` present, target-repo shipped); `README.md` links `docs/evaluation.md` and
  `evals/README.md`; `improvement.md` synced (escalation done, hooks, eval fixtures).
- **Tests:** unit suite grows from 126 to 143 (hooks, escalation pause, Web UI event parsing,
  debug integration).

## Planned / Unreleased — Phase C (deferred)

Held until there is a clear need; see `improvement.md` and `feedback.md` for rationale ("defer until A+B").

- **Container build smoke (next candidate, opt-in):** `--container-smoke` / `AGENTFORGE_CONTAINER_SMOKE` — at the deploy gate, `docker build` the target repo (and optionally start it + hit a health endpoint), recording pass/fail in `deploy_record.md`. Skipped cleanly when off, when no Docker daemon, or when no `Dockerfile`. Lowest-risk Phase-C slice: additive and gated, no concurrency or inbound-network surface.
- **Parallel phases:** run independent phases concurrently. Needs workspace locking and reworked handoff/checkpoint ordering; deferred for race-safety.
- **Web search:** let agents fetch API docs. Deferred for security (SSRF / prompt-injection from fetched pages) and eval nondeterminism; will require an allowlist + sandbox.
- **Cost caps, webhooks, hosted orchestrator:** spend limits, outbound notifications, and a long-running service front-end. Separate product surface (auth, persistence, deploy) beyond the CLI.

## 0.3.0 — 2026-06-07

**Universal codebase operator.** AgentForge can now read, diagnose, and patch an **arbitrary existing repo**, not only generate the DailyEase sandbox. Default behavior (no new flags) is unchanged and backward compatible.

- **Operate on your repo — `--target-repo PATH` / `AGENTFORGE_TARGET_REPO`:** point AgentForge at an existing project; all read/write/grep/verify/commit resolve against that tree. AgentForge's own bookkeeping is isolated under `<repo>/.agentforge` (handoff, reports), and the SQLite DB stays under `AGENTFORGE_ROOT` — it never writes its metadata into your source tree. Without the flag, the `workspace/` sandbox behaves as before.
- **Bug-fix / hardening presets:** `--preset debug` (reproduce → localize → patch → re-verify), `--preset fix` (apply a known fix → verify), `--preset harden` (audit → patch → production-readiness). Complements the existing `intake` / `design` / `implement` / `test` / `ship` / `improve` / `full`.
- **Project profiles:** drop the DailyEase-specific assumptions. A `.agentforge/profile.yaml` (`name`, `stack`, `app_root`, `test_cmd`, `lint_cmd`, `verify_cmd`) drives worker prompts and verification; with no profile, the stack is auto-discovered from `pyproject.toml` / `package.json` / `go.mod`, falling back to the DailyEase default. Workers write to `profile.app_root` and use `profile.stack` for tech choices.
- **Workers can inspect existing code:** implementation and QA agents now have `read_file` (paginated), `list_files` (glob), and `grep_code` (regex) — bounded, path-safe — so they read and localize before patching instead of writing blind. Required for real bug-find and refactor work.
- **Profile-driven verify + real-repo commit:** the deploy gate runs the profile's `verify_cmd` (`pytest -q`, `npm test`, `go test ./...`, …) against the actual project. `--deploy-commit` commits the **target repo** with a conventional-commit message; new `--deploy-branch NAME` checks out/creates a branch first for a PR workflow.
- **`--strict-review`:** block the deploy when any unresolved review finding (quality debt) remains, instead of shipping with it merely flagged (`AGENTFORGE_STRICT_REVIEW`). Default off — existing runs still ship with debt recorded in the deploy summary.
- **Structured event log — `AGENTFORGE_JSON_LOG`:** emit one JSON object per line on **stderr** (`phase_complete`, `files_changed`, `review_verdict`, `pytest_result`, `exit_summary`) so host assistants (Cursor / Codex / Claude Code) can parse progress reliably. Off by default; human console output is unchanged.
- **Reviewer paginated read:** the Reviewer pages through large files (`offset` / `limit`, numbered lines) instead of hard-truncating at 8k characters, so review quality holds on big files.
- **Leaner upstream context:** workers now receive upstream docs path-first — a short digest plus a `read_file` pointer to the full document — instead of a large inlined blob, so condensing no longer silently drops the rest of a doc.
- **Run from any directory:** install once (`uv tool install .` or `pipx install .`) and run `agentforge --target-repo . --goal "…"` from inside any project. When installed and run outside the AgentForge source tree, the sandbox/DB default to `~/.agentforge` (override with `AGENTFORGE_HOME` / `AGENTFORGE_ROOT`) instead of polluting the current directory.
- **Cross-tool integration templates:** `.cursor/rules/agentforge.md`, `.vscode/tasks.json` (debug / test / harden / dry-run tasks), and an `AGENTS.md` snippet for Codex/generic agents — each carrying the dual-agent contract (*AgentForge runs its own LLM pass; your assistant launches, monitors, and summarizes — it does not duplicate the work*).
- **Evaluation:** new `evals/` suite — fixture-based scenarios (`intake_requirements`, `full_pipeline_smoke`, `reviewer_reject`, `resume_checkpoint`) + `run_evals.py`, kept separate from the unit tests (plumbing) in `tests/`. New `docs/evaluation.md` maps a 9-step quality roadmap onto AgentForge presets, gates, and metrics.
- **Docs:** `docs/running-with-ai-clis.md` gains a "Work on your existing repo" section; `README.md` carries the dual-agent contract; `improvement.md` tracks roadmap status.
- **Tests:** unit suite grows from 44 to 126 (target-repo routing, read tools, profiles, presets, deploy verify, strict-review, events, paginated read, path resolution).

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
