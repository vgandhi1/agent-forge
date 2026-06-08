# AgentForge evals

This directory holds **agent evals** — pipeline-outcome checks — as distinct from the
**unit tests** in `tests/`.

| Layer | Location | Purpose |
|-------|----------|---------|
| Unit tests | `tests/` (mocked LLM) | Plumbing: message bus, handoff, tool loop, gates, paths |
| Agent evals | `evals/` (this dir) | Pipeline outcomes: required artifacts, document sections, Reviewer verdicts, resume behavior |

Unit tests answer "do the parts work in isolation?" Evals answer "did a run produce the
right *outcome*?" — the artifacts a preset is contracted to produce, the sections a
document must contain, and the verdict the Reviewer must return. This is the concrete
form of step 9 in [`../docs/evaluation.md`](../docs/evaluation.md).

## Layout

```
evals/
  README.md
  run_evals.py            # validates scenarios; grades artifacts against a workspace
  scenarios/
    intake_requirements.yaml   # goal -> requirements.md must contain sections X, Y, Z
    full_pipeline_smoke.yaml   # full run -> handoff/<role>.md + core artifacts present
    reviewer_reject.yaml       # incomplete fixture -> expect reject verdict
    resume_checkpoint.yaml     # --resume skips completed phases
```

Each scenario is a **declarative data file**: it describes the checks, it is not a live
run. A scenario can set `live: true` to mark itself as needing real LLM execution (gated
behind a future live runner — currently skipped).

## Scenario schema

| Key | Required | Meaning |
|-----|----------|---------|
| `name` | yes | Unique scenario id (defaults to file stem) |
| `description` | yes | One-line summary |
| `preset` | yes | One of `full/intake/design/implement/test/ship/improve/debug/fix/harden` |
| `goal` | yes | The goal string a real run would use |
| `expected_artifacts` | no | Paths that must exist under the grading root |
| `expected_sections` | no | `{file: [headings]}` that must appear in that file |
| `expected_verdict` | no | `approve` / `reject` / `escalate` / null |
| `fixture` | no | Committed tree under `evals/fixtures/` graded when no `--workspace` is given |
| `live` | no | `true` if the scenario needs a real LLM run (skipped for now) |

## Running

```bash
# Validate every scenario's schema (no LLM, no workspace needed)
uv run python evals/run_evals.py

# Grade a produced workspace against the declared artifacts + sections
uv run python evals/run_evals.py --workspace workspace

# Help
uv run python evals/run_evals.py --help
```

A scenario passes when its schema is valid and every declared artifact exists and every
required section is present in the **grading root** — `--workspace PATH` if given, else the
scenario's committed `fixture:` tree under `evals/fixtures/`. Fixtures make the suite
deterministic in CI without a live run. The runner exits non-zero if any scenario fails, so
it gates CI (`.github/workflows/ci.yml` runs it after the unit suite).

## What is not here yet (TODO)

- **Live-LLM evals** — actually running `main.py` and grading fresh output (costly; a
  nightly/optional CI job). Scenarios marked `live: true` are skipped until that lands.
- **Reviewer fixture execution** — `reviewer_reject.yaml` declares the expected verdict;
  feeding the fixture to a real Reviewer call is part of the live runner.

See [`../docs/evaluation.md`](../docs/evaluation.md) for the full evaluation roadmap and
the pass/fail metrics table.
