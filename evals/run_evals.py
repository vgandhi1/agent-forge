#!/usr/bin/env python
"""AgentForge eval runner (fixture-based, no live LLM).

This is the concrete form of step 9 in docs/evaluation.md: pipeline-outcome checks
that complement the unit tests in ``tests/`` (which cover plumbing). Each scenario in
``evals/scenarios/*.yaml`` declares what a passing run looks like — expected artifacts,
required document sections, and the Reviewer verdict.

Today this runner does two things, neither of which calls an LLM:

1. **Schema validation** — every scenario file parses and has the required keys.
2. **Workspace assertions** — when ``--workspace PATH`` is given, declared
   ``expected_artifacts`` are checked for existence and ``expected_sections`` for the
   required headings. This lets you point the runner at a ``workspace/`` produced by a
   real ``main.py`` run and grade it.

Live-LLM execution (actually running ``main.py`` and grading fresh output) is **TODO**
and is skipped here; scenarios marked ``live: true`` would be gated behind that.

Run::

    uv run python evals/run_evals.py --help
    uv run python evals/run_evals.py                 # validate scenario schemas
    uv run python evals/run_evals.py --workspace workspace   # + grade artifacts
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

# Keys every scenario must define; ``str`` means required+typed, tuple means any-of.
REQUIRED_KEYS: dict[str, Any] = {
    "name": str,
    "description": str,
    "preset": str,
    "goal": str,
}
KNOWN_PRESETS = {
    "full",
    "intake",
    "design",
    "implement",
    "test",
    "ship",
    "improve",
}


def load_scenarios(directory: Path | None = None) -> list[dict[str, Any]]:
    """Parse every ``*.yaml`` under the scenarios dir into a list of dicts.

    Raises ``yaml.YAMLError`` if any file is malformed (callers/tests rely on this to
    catch bad scenario data early).
    """
    directory = directory or SCENARIOS_DIR
    scenarios: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"{path.name}: scenario must be a YAML mapping")
        data.setdefault("name", path.stem)
        data["__file__"] = path.name
        scenarios.append(data)
    return scenarios


def validate_scenario(scenario: dict[str, Any]) -> list[str]:
    """Return a list of structural errors for one scenario ([] means valid)."""
    errors: list[str] = []
    for key, typ in REQUIRED_KEYS.items():
        if key not in scenario:
            errors.append(f"missing required key '{key}'")
        elif not isinstance(scenario[key], typ):
            errors.append(f"key '{key}' must be {typ.__name__}")
    preset = scenario.get("preset")
    if preset is not None and preset not in KNOWN_PRESETS:
        errors.append(f"unknown preset '{preset}' (expected one of {sorted(KNOWN_PRESETS)})")
    verdict = scenario.get("expected_verdict")
    if verdict not in (None, "approve", "reject", "escalate"):
        errors.append(f"expected_verdict '{verdict}' not in approve/reject/escalate/null")
    sections = scenario.get("expected_sections", {})
    if sections and not isinstance(sections, dict):
        errors.append("expected_sections must be a mapping of file -> [headings]")
    artifacts = scenario.get("expected_artifacts", [])
    if artifacts and not isinstance(artifacts, list):
        errors.append("expected_artifacts must be a list of paths")
    return errors


def check_workspace(scenario: dict[str, Any], workspace: Path) -> list[str]:
    """Grade a scenario's declared artifacts/sections against a real workspace.

    Returns a list of failure messages ([] means all declared checks passed).
    """
    failures: list[str] = []
    for rel in scenario.get("expected_artifacts", []) or []:
        if not (workspace / rel).exists():
            failures.append(f"missing artifact: {rel}")
    for rel, headings in (scenario.get("expected_sections") or {}).items():
        target = workspace / rel
        if not target.exists():
            failures.append(f"missing artifact for section check: {rel}")
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        for heading in headings:
            if heading not in text:
                failures.append(f"{rel}: missing section '{heading}'")
    return failures


def run(workspace: Path | None, scenarios_dir: Path | None = None) -> int:
    """Validate all scenarios (and grade against ``workspace`` if given).

    Returns a process exit code: 0 = all checks passed, 1 = at least one failure.
    """
    try:
        scenarios = load_scenarios(scenarios_dir)
    except (yaml.YAMLError, ValueError) as exc:
        print(f"FAIL: could not load scenarios: {exc}", file=sys.stderr)
        return 1

    if not scenarios:
        print("FAIL: no scenarios found", file=sys.stderr)
        return 1

    failed = 0
    for scenario in scenarios:
        name = scenario.get("name", scenario.get("__file__", "?"))
        errors = validate_scenario(scenario)
        if errors:
            failed += 1
            print(f"FAIL  {name}: " + "; ".join(errors))
            continue

        if scenario.get("live"):
            # Live-LLM grading runs main.py and inspects fresh output — not implemented.
            print(f"SKIP  {name}: live-LLM eval (TODO)")
            continue

        if workspace is not None:
            ws_failures = check_workspace(scenario, workspace)
            if ws_failures:
                failed += 1
                print(f"FAIL  {name}: " + "; ".join(ws_failures))
                continue
            print(f"PASS  {name}: schema + workspace artifacts")
        else:
            print(f"OK    {name}: schema valid (no --workspace; artifact checks skipped)")

    total = len(scenarios)
    print(f"\n{total - failed}/{total} scenarios passed.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_evals.py",
        description="Validate AgentForge eval scenarios and grade them against a workspace.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Path to a produced workspace/ to grade expected_artifacts/sections against. "
        "Omit to only validate scenario schemas.",
    )
    parser.add_argument(
        "--scenarios-dir",
        type=Path,
        default=None,
        help="Override the scenarios directory (default: evals/scenarios).",
    )
    args = parser.parse_args(argv)
    return run(args.workspace, args.scenarios_dir)


if __name__ == "__main__":
    raise SystemExit(main())
