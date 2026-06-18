"""Tests for the LLM-as-a-Judge eval layer (evals/judge.py + run_evals --judge).

The judge's *core* is pure, so we test it deterministically with a fake completer
(no network). A single opt-in live test exercises the real provider and is skipped
unless ``AGENTFORGE_RUN_LIVE=1``.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

import judge as J  # evals/ is on pythonpath via pyproject

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- fixtures / helpers -----------------------------------------------------------

CRITERIA = [
    J.Criterion("completeness", "all sections present", weight=2.0),
    J.Criterion("clarity", "specific and testable", weight=1.0),
]


def fake_completer(payload: str):
    """Return a completer that always responds with ``payload`` (ignores the prompt)."""
    return lambda _prompt: payload


def load_runner():
    runner_path = REPO_ROOT / "evals" / "run_evals.py"
    spec = importlib.util.spec_from_file_location("agentforge_run_evals", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- parse_criteria ---------------------------------------------------------------

def test_parse_criteria_reads_weights_and_defaults():
    crit = J.parse_criteria([
        {"key": "a", "description": "x", "weight": 3},
        {"key": "b", "description": "y"},
    ])
    assert [c.key for c in crit] == ["a", "b"]
    assert crit[0].weight == 3.0
    assert crit[1].weight == 1.0


def test_parse_criteria_rejects_bad_items():
    with pytest.raises(J.JudgeError):
        J.parse_criteria([{"key": "a"}])  # missing description
    with pytest.raises(J.JudgeError):
        J.parse_criteria([])  # empty
    with pytest.raises(J.JudgeError):
        J.parse_criteria([{"key": "a", "description": "x", "weight": 0}])  # bad weight


# --- build_prompt -----------------------------------------------------------------

def test_build_prompt_includes_each_criterion_and_truncates():
    prompt = J.build_prompt(
        "the goal", "docs/x.md", "B" * 9000, CRITERIA, max_chars=100
    )
    assert "completeness" in prompt and "clarity" in prompt
    assert "the goal" in prompt
    assert "truncated for judging" in prompt
    # Artifact body is bounded.
    assert prompt.count("B") <= 200


# --- _extract_json / parse_verdict ------------------------------------------------

def test_extract_json_tolerates_fences_and_prose():
    raw = 'Sure!\n```json\n{"scores": {"completeness": 5, "clarity": 4}}\n```\nHope that helps.'
    scores, _ = J.parse_verdict(raw, CRITERIA)
    assert scores == {"completeness": 5, "clarity": 4}


def test_parse_verdict_clamps_out_of_range():
    raw = '{"scores": {"completeness": 9, "clarity": 0}}'
    scores, _ = J.parse_verdict(raw, CRITERIA, scale=5)
    assert scores == {"completeness": 5, "clarity": 1}


def test_parse_verdict_requires_all_criteria():
    with pytest.raises(J.JudgeError):
        J.parse_verdict('{"scores": {"completeness": 4}}', CRITERIA)


def test_parse_verdict_errors_on_garbage():
    with pytest.raises(J.JudgeError):
        J.parse_verdict("no json here", CRITERIA)
    with pytest.raises(J.JudgeError):
        J.parse_verdict('{"scores": {"completeness": "high", "clarity": 4}}', CRITERIA)


# --- weighted_score ---------------------------------------------------------------

def test_weighted_score_normalises_and_weights():
    # perfect scores -> 1.0
    assert J.weighted_score({"completeness": 5, "clarity": 5}, CRITERIA) == pytest.approx(1.0)
    # floor scores -> 0.0
    assert J.weighted_score({"completeness": 1, "clarity": 1}, CRITERIA) == pytest.approx(0.0)
    # weighting matters: completeness has weight 2 of total 3
    # completeness=5 (1.0), clarity=1 (0.0) -> (2*1 + 1*0)/3 = 0.667
    val = J.weighted_score({"completeness": 5, "clarity": 1}, CRITERIA)
    assert val == pytest.approx(2 / 3, abs=1e-6)


# --- judge() end-to-end with a fake completer -------------------------------------

def test_judge_passes_above_threshold():
    res = J.judge(
        "goal", "x.md", "body", CRITERIA,
        fake_completer('{"scores": {"completeness": 5, "clarity": 4}, '
                       '"rationale": {"completeness": "thorough", "clarity": "clear"}}'),
        threshold=0.7,
    )
    assert res.passed is True
    assert res.weighted > 0.7
    assert res.rationale["completeness"] == "thorough"


def test_judge_fails_below_threshold():
    res = J.judge(
        "goal", "x.md", "body", CRITERIA,
        fake_completer('{"scores": {"completeness": 2, "clarity": 1}}'),
        threshold=0.7,
    )
    assert res.passed is False
    assert res.weighted < 0.7


# --- run_evals --judge integration (fake completer) -------------------------------

def test_run_evals_judge_path_grades_fixture():
    runner = load_runner()
    scenarios = runner.load_scenarios()
    intake = next(s for s in scenarios if s["name"] == "intake_requirements")
    assert intake.get("rubric"), "intake scenario should carry a rubric"

    grade_root = runner.EVALS_DIR / intake["fixture"]
    ok, msg = runner.judge_scenario(
        intake, grade_root,
        fake_completer('{"scores": {"completeness": 5, "clarity": 5, "scope_discipline": 5}}'),
    )
    assert ok is True
    assert "judge PASS" in msg


def test_run_evals_judge_path_reports_failure():
    runner = load_runner()
    intake = next(s for s in runner.load_scenarios() if s["name"] == "intake_requirements")
    grade_root = runner.EVALS_DIR / intake["fixture"]
    ok, msg = runner.judge_scenario(
        intake, grade_root,
        fake_completer('{"scores": {"completeness": 1, "clarity": 1, "scope_discipline": 1}}'),
    )
    assert ok is False
    assert "judge FAIL" in msg


def test_run_full_suite_with_injected_completer_returns_zero():
    runner = load_runner()
    # Inject a generous completer; full run (schema + fixtures + judge) should pass.
    rc = runner.run(
        None,
        use_judge=True,
        completer=fake_completer(
            '{"scores": {"completeness": 5, "clarity": 5, "scope_discipline": 5}}'
        ),
    )
    assert rc == 0


# --- opt-in live smoke test -------------------------------------------------------

@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("AGENTFORGE_RUN_LIVE") != "1",
    reason="live LLM test; set AGENTFORGE_RUN_LIVE=1 (and a provider/API key) to run",
)
def test_judge_live_smoke():
    completer = J.default_completer()
    res = J.judge(
        "Write a one-line greeting.",
        "greeting.txt",
        "Hello, welcome to AgentForge!",
        [J.Criterion("relevance", "greets the reader", weight=1.0)],
        completer,
        threshold=0.4,
    )
    assert 0.0 <= res.weighted <= 1.0
