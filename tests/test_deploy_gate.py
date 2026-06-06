from pathlib import Path

import pytest
from rich.console import Console

from core import deploy
from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


def _lead(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    lead = LeadAgent("lead", MessageBus(), ArtifactStore(), Console())

    writes: list[tuple[str, str]] = []

    async def fake_write(path, content):
        writes.append((path, content))
        return Path("/tmp") / path

    async def fake_recall_all(kind):
        return {}

    async def fake_remember(*args, **kwargs):
        return None

    monkeypatch.setattr(lead.artifacts, "write", fake_write)
    monkeypatch.setattr(lead.memory, "recall_all", fake_recall_all)
    monkeypatch.setattr(lead.memory, "remember", fake_remember)

    async def verify_pass():
        return ("pass", "all good")

    lead._verify_fn = verify_pass
    return lead, writes


def _record(writes: list[tuple[str, str]]) -> str:
    recs = [c for p, c in writes if p == "reports/deploy_record.md"]
    assert recs, "no deploy record written"
    return recs[-1]


@pytest.mark.asyncio
async def test_gate_disabled_is_autonomous(monkeypatch) -> None:
    lead, writes = _lead(monkeypatch)
    called = {"approval": False}

    async def approval(summary):
        called["approval"] = True
        return False

    lead._approval_fn = approval

    await lead._finalize_sprint("build X", deploy_gate=False, auto_approve=False, deploy_commit=False)

    assert called["approval"] is False  # no human prompt in autonomous mode
    assert "Decision: autonomous" in _record(writes)


@pytest.mark.asyncio
async def test_gate_declined_aborts(monkeypatch) -> None:
    lead, writes = _lead(monkeypatch)

    async def approval(summary):
        return False

    lead._approval_fn = approval

    commit_called = {"v": False}

    async def fake_commit(target, message):
        commit_called["v"] = True
        return True, "abc"

    monkeypatch.setattr(deploy, "git_commit_dir", fake_commit)

    await lead._finalize_sprint("build X", deploy_gate=True, auto_approve=False, deploy_commit=True)

    assert "Decision: aborted" in _record(writes)
    assert commit_called["v"] is False  # declined → never commits


@pytest.mark.asyncio
async def test_gate_auto_approve_commits(monkeypatch) -> None:
    lead, writes = _lead(monkeypatch)

    async def approval(summary):  # should not be called when auto_approve
        raise AssertionError("approval prompt should be skipped on auto-approve")

    lead._approval_fn = approval

    async def fake_commit(target, message):
        return True, "deadbee"

    monkeypatch.setattr(deploy, "git_commit_dir", fake_commit)

    await lead._finalize_sprint("build X", deploy_gate=True, auto_approve=True, deploy_commit=True)

    rec = _record(writes)
    assert "Decision: approved (auto)" in rec
    assert "committed deadbee" in rec
