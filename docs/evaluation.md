# Evaluating AgentForge

This is an AgentForge-scoped adaptation of a 9-step agent-quality roadmap (originally a
generic Claude Code / BMAD checklist). It is rewritten for this repo: each step maps to a
concrete AgentForge capability — a preset, the Reviewer, the deploy gate, or the `evals/`
suite — rather than to third-party tools that AgentForge does not ship.

Two ideas frame everything below:

1. **The host assistant and AgentForge are separate models.** Steps 1–8 mostly improve the
   *assistant that launches* AgentForge. AgentForge runs its own LLM pass — the assistant
   should launch, monitor, and summarize, not duplicate the work.
2. **"Looks good" is not a pass.** Step 9 is where AgentForge measures end-to-end quality
   with pass/fail criteria instead of a human eyeballing the console.

Keep the two test layers distinct:

| Layer | Location | Purpose |
|-------|----------|---------|
| Unit tests | `tests/` (mocked LLM) | Plumbing: bus, handoff, tool loop, gates, paths |
| Agent evals | `evals/` | Pipeline outcomes: artifacts, document sections, review behavior, resume |

## Step 1: Plan before code

Write the spec before generating files. In AgentForge the PM agent owns this:
`--preset intake --goal "..."` produces `requirements.md` with acceptance criteria.

- **Today:** acceptance criteria live in the PM prompt and the requirements doc.
- **Gap:** those criteria are written but not yet *scored*. Add explicit success metrics so
  an eval can check them (see `evals/scenarios/intake_requirements.yaml`).

## Step 2: Rules before files

State the operating contract up front. For host assistants this is the dual-agent contract
in the README and the slash commands: *AgentForge runs its own LLM pass; your assistant only
launches, monitors, and summarizes.*

- **Today:** `.claude/commands/agentforge*.md` carry per-command guidance.
- **Gap:** a root `AGENTS.md` / `CLAUDE.md` would extend this to Cursor/Codex users.

## Step 3: Fresh context, plan first

Start each run from a clean slate and confirm the plan before building.

- `--dry-run` previews provider, models, gates, and phases without an API call.
- `--plan-gate` makes Backend propose a build plan for the Lead to confirm or redirect.
- `--resume` continues an interrupted run from `handoff/checkpoint.json`.

## Step 4: Structured I/O

Prefer typed, parseable output over free text.

- The Reviewer returns a structured verdict via `submit_review` (approve/reject/escalate).
- Handoffs are written as `handoff/<role>.md` plus a JSON `checkpoint.json`.
- `AGENTFORGE_JSON_LOG=1` emits one JSON event per line on stderr (`phase_complete`,
  `files_changed`, `review_verdict`, `pytest_result`, `exit_summary`) so a host assistant
  can consume results reliably. See `core/events.py` and
  [running-with-ai-clis.md](running-with-ai-clis.md).

## Step 5: Reuse integrations

The eval roadmap's "skills / MCP" step is **not applicable inside AgentForge's runtime by
design** — AgentForge is driven as a subprocess CLI, not as an MCP server. The host tool may
use MCP/skills to *launch* AgentForge; AgentForge itself stays a plain CLI.

## Step 6: Isolation and parallelism

The roadmap's "sub-agents / worktrees" step is what AgentForge *is*: the Lead splits work
across PM → Architect → Backend → QA → DevOps, each an isolated persona with its own memory.

- **Today:** phases run sequentially.
- **Gap:** parallel phases (with workspace locking) and an optional git worktree per sprint
  are deferred to a later phase.

## Step 7: Auto test / lint on change (guardrails)

Guardrails that run automatically keep quality from drifting. (The source roadmap spelled
this "gaurrails"; corrected here.)

- **Today:** the `--deploy-gate` runs a `pytest` smoke check before shipping; GitHub CI runs
  the unit suite.
- **Gap:** optional `.agentforge/hooks/pre-phase` / `post-phase` (lint, pytest smoke) to run
  guardrails per phase rather than only at the deploy gate.

## Step 8: Trusted long-term context

Memory and retrieval the agents can rely on across turns.

- **Today:** SQLite `AgentMemory` and `handoff/checkpoint.json` persist decisions and
  artifact references.
- **Gap:** no RAG over a target repo yet; add once `--target-repo` mode matures.

## Step 9: The eval suite (the largest gap, now scaffolded)

Measure end-to-end quality with pass/fail criteria, not "looks good." This lives in
[`../evals/`](../evals): declarative scenarios graded by `run_evals.py`.

```bash
uv run python evals/run_evals.py               # validate scenario schemas
uv run python evals/run_evals.py --workspace workspace   # grade a produced run
```

Current scenarios:

| Scenario | Checks |
|----------|--------|
| `intake_requirements` | `requirements.md` contains the mandatory PM sections |
| `full_pipeline_smoke` | each phase leaves `handoff/<role>.md`; core artifacts present |
| `reviewer_reject` | an incomplete fixture yields a structured **reject** verdict |
| `resume_checkpoint` | `--resume` skips phases marked done in the checkpoint |

### Pass / fail metrics

| Metric | Pass condition |
|--------|----------------|
| Phase completion | Each preset finishes without timeout; `handoff/<role>.md` exists |
| Artifact contract | Required paths exist under the workspace per preset |
| Review gate | Reviewer returns a structured verdict; silence → reject |
| Test smoke | `pytest -q` in the generated app exits 0 after a `test`/`full` preset |
| Deploy gate | `--deploy-gate` writes `reports/deploy_record.md` with a decision |
| Resume | `--resume` with the same goal skips completed phases in `checkpoint.json` |
| Quality debt | Flagged debt appears in the deploy summary (not a silent pass) |

### What is deferred

- **Live-LLM evals** (`live: true` scenarios) — run `main.py` and grade fresh output. Costly;
  a nightly/optional CI job. Skipped by the current fixture-based runner.
- The fixture-based suite above can ship before target-repo mode and live evals.
