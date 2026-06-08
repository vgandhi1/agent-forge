# Eval fixtures

Committed workspace trees used by `run_evals.py` to grade a scenario's
`expected_artifacts` / `expected_sections` **deterministically**, without a live
(costly, non-deterministic) pipeline run.

A scenario opts in with a `fixture:` key pointing at a directory under this folder:

```yaml
fixture: fixtures/full_pipeline
```

When no `--workspace` is passed, the runner grades the scenario against its fixture
tree. With `--workspace PATH`, the workspace wins (grade a real run instead).

These trees are minimal, hand-authored representations of what a passing run produces
— enough to assert the artifact contract in CI. They are **not** generated output and
should be edited by hand when the contract changes.

| Fixture | Scenario | Asserts |
|---------|----------|---------|
| `full_pipeline/` | `full_pipeline_smoke` | one `handoff/<role>.md` per phase + `reports/qa_report.md` |
| `intake_requirements/` | `intake_requirements` | `docs/requirements.md` with the mandatory PM sections |
| `resume_checkpoint/` | `resume_checkpoint` | `handoff/checkpoint.json` present |
