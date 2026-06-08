"""Tests for core.events (structured JSON event log) and the evals scaffold.

The emitter must be a no-op by default (so default human output is unchanged), emit
exactly one valid JSON line per call when enabled, and never raise. The env var is read
at call time, so monkeypatch.setenv/delenv toggles behavior without reimport.
"""

import json
import sys
from pathlib import Path

import pytest

from core import events

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv("AGENTFORGE_JSON_LOG", raising=False)
    yield


def test_disabled_by_default_writes_nothing(capsys, monkeypatch):
    monkeypatch.delenv("AGENTFORGE_JSON_LOG", raising=False)
    events.emit("phase_complete", phase="backend")
    events.emit("files_changed", role="qa", count=3)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_falsey_value_writes_nothing(capsys, monkeypatch):
    for val in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("AGENTFORGE_JSON_LOG", val)
        events.emit("phase_complete", phase="backend")
    assert capsys.readouterr().err == ""


def test_enabled_writes_single_valid_json_line(capsys, monkeypatch):
    monkeypatch.setenv("AGENTFORGE_JSON_LOG", "1")
    events.emit("files_changed", role="backend", count=23)
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "files_changed"
    assert record["role"] == "backend"
    assert record["count"] == 23
    assert "ts" in record


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "on"])
def test_truthy_variants_enable(capsys, monkeypatch, val):
    monkeypatch.setenv("AGENTFORGE_JSON_LOG", val)
    assert events.enabled() is True
    events.emit("exit_summary", status="ok")
    assert capsys.readouterr().err.strip() != ""


def test_each_event_type_roundtrips(capsys, monkeypatch):
    monkeypatch.setenv("AGENTFORGE_JSON_LOG", "1")
    for etype in events.EVENT_TYPES:
        events.emit(etype, sample=1)
    err = capsys.readouterr().err
    records = [json.loads(ln) for ln in err.splitlines() if ln.strip()]
    assert [r["event"] for r in records] == list(events.EVENT_TYPES)
    assert all("ts" in r for r in records)


def test_reserved_keys_are_not_overridden(capsys, monkeypatch):
    monkeypatch.setenv("AGENTFORGE_JSON_LOG", "1")
    events.emit("review_verdict", event="HACK", ts="HACK", decision="reject")
    record = json.loads(capsys.readouterr().err.strip())
    assert record["event"] == "review_verdict"
    assert record["ts"] != "HACK"
    assert record["decision"] == "reject"


def test_emit_never_raises_on_unserializable(capsys, monkeypatch):
    monkeypatch.setenv("AGENTFORGE_JSON_LOG", "1")

    class Weird:
        pass

    # default=str keeps this serializable; emit must not raise regardless.
    events.emit("pytest_result", obj=Weird(), passed=1)
    record = json.loads(capsys.readouterr().err.strip())
    assert record["event"] == "pytest_result"
    assert record["passed"] == 1


def test_emit_swallows_stderr_write_failure(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_JSON_LOG", "1")

    class BrokenStderr:
        def write(self, *_a, **_k):
            raise OSError("stderr closed")

        def flush(self):
            raise OSError("stderr closed")

    monkeypatch.setattr(sys, "stderr", BrokenStderr())
    # Must not raise even when stderr is broken.
    events.emit("exit_summary", status="ok")


# --- evals scaffold sanity: scenarios parse and the runner is importable ---

def test_run_evals_parses_all_scenarios():
    import importlib.util

    runner_path = REPO_ROOT / "evals" / "run_evals.py"
    spec = importlib.util.spec_from_file_location("agentforge_run_evals", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    scenarios = module.load_scenarios()
    names = {s["name"] for s in scenarios}
    for required in (
        "intake_requirements",
        "full_pipeline_smoke",
        "reviewer_reject",
        "resume_checkpoint",
    ):
        assert required in names, f"missing scenario {required}"
    # Every scenario must pass structural validation.
    for scenario in scenarios:
        errors = module.validate_scenario(scenario)
        assert errors == [], f"{scenario.get('name')}: {errors}"
