from pathlib import Path

import pytest
from rich.console import Console

from core import deploy
from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


def _lead(monkeypatch, debts):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    lead = LeadAgent("lead", MessageBus(), ArtifactStore(), Console())

    writes: list[tuple[str, str]] = []

    async def fake_write(path, content):
        writes.append((path, content))
        return Path("/tmp") / path

    async def fake_recall_all(kind):
        return dict(debts)

    async def fake_remember(*args, **kwargs):
        return None

    monkeypatch.setattr(lead.artifacts, "write", fake_write)
    monkeypatch.setattr(lead.memory, "recall_all", fake_recall_all)
    monkeypatch.setattr(lead.memory, "remember", fake_remember)

    async def verify_pass():
        return ("pass", "all good")

    lead._verify_fn = verify_pass
    return lead, writes


def _record(writes):
    recs = [c for p, c in writes if p == "reports/deploy_record.md"]
    assert recs, "no deploy record written"
    return recs[-1]


@pytest.mark.asyncio
async def test_strict_review_blocks_deploy_on_debt(monkeypatch):
    lead, writes = _lead(monkeypatch, {"quality_debt_backend": "router not reviewed"})

    commit_called = {"v": False}

    async def fake_commit(target, message, **kw):
        commit_called["v"] = True
        return True, "abc"

    monkeypatch.setattr(deploy, "git_commit_dir", fake_commit)

    await lead._finalize_sprint(
        "build X", deploy_gate=True, auto_approve=True, deploy_commit=True, strict_review=True
    )

    assert "Decision: blocked (strict-review)" in _record(writes)
    assert commit_called["v"] is False  # blocked → never commits


@pytest.mark.asyncio
async def test_strict_review_allows_deploy_when_clean(monkeypatch):
    lead, writes = _lead(monkeypatch, {})  # no quality debt

    async def fake_commit(target, message, **kw):
        return True, "deadbee"

    monkeypatch.setattr(deploy, "git_commit_dir", fake_commit)

    await lead._finalize_sprint(
        "build X", deploy_gate=True, auto_approve=True, deploy_commit=True, strict_review=True
    )

    rec = _record(writes)
    assert "Decision: approved (auto)" in rec


@pytest.mark.asyncio
async def test_debt_ships_without_strict_flag(monkeypatch):
    lead, writes = _lead(monkeypatch, {"quality_debt_qa": "edge cases skipped"})

    async def fake_commit(target, message, **kw):
        return True, "feed"

    monkeypatch.setattr(deploy, "git_commit_dir", fake_commit)

    # Default (no strict_review): debt is flagged but does not block.
    await lead._finalize_sprint(
        "build X", deploy_gate=True, auto_approve=True, deploy_commit=True
    )

    assert "Decision: approved (auto)" in _record(writes)
