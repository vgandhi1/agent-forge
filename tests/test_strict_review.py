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

    assert "Decision: blocked (unresolved review findings)" in _record(writes)
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
async def test_debt_blocks_deploy_by_default(monkeypatch):
    """Fail-closed default (F5 fix): quality debt blocks the deploy with no flags."""
    lead, writes = _lead(monkeypatch, {"quality_debt_qa": "edge cases skipped"})

    commit_called = {"v": False}

    async def fake_commit(target, message, **kw):
        commit_called["v"] = True
        return True, "feed"

    monkeypatch.setattr(deploy, "git_commit_dir", fake_commit)

    await lead._finalize_sprint(
        "build X", deploy_gate=True, auto_approve=True, deploy_commit=True
    )

    assert "Decision: blocked (unresolved review findings)" in _record(writes)
    assert commit_called["v"] is False  # blocked → never commits
    assert lead._deploy_blocked is True


@pytest.mark.asyncio
async def test_debt_blocks_autonomous_run(monkeypatch):
    """Even an autonomous run (no deploy gate) must fail closed on quality debt (F5)."""
    lead, writes = _lead(monkeypatch, {"quality_debt_architect": "stub, no design"})

    await lead._finalize_sprint(
        "build X", deploy_gate=False, auto_approve=False, deploy_commit=False
    )

    assert "Decision: blocked (unresolved review findings)" in _record(writes)
    assert lead._deploy_blocked is True


@pytest.mark.asyncio
async def test_thin_doc_blocks_deploy(monkeypatch):
    """F3 backstop: a thin/placeholder spec doc blocks the deploy even with no quality debt."""
    lead, writes = _lead(monkeypatch, {})  # no quality debt
    lead._approved_artifacts = {"architect_artifact": "docs/architecture.md"}

    async def fake_read(path):
        return "# Architecture\n\nDetails will be documented separately in a future ticket.\n"

    monkeypatch.setattr(lead.artifacts, "read", fake_read)

    await lead._finalize_sprint("build X", deploy_gate=False, auto_approve=False, deploy_commit=False)

    rec = _record(writes)
    assert "Decision: blocked (thin or placeholder artifacts)" in rec
    assert lead._deploy_blocked is True


@pytest.mark.asyncio
async def test_allow_quality_debt_ships_with_thin_doc(monkeypatch):
    """--allow-quality-debt also overrides the thin-doc backstop."""
    lead, writes = _lead(monkeypatch, {})
    lead._approved_artifacts = {"architect_artifact": "docs/architecture.md"}

    async def fake_read(path):
        return "# Architecture\n\nTODO.\n"

    monkeypatch.setattr(lead.artifacts, "read", fake_read)

    await lead._finalize_sprint(
        "build X", deploy_gate=False, auto_approve=False, deploy_commit=False,
        allow_quality_debt=True,
    )

    assert "Decision: autonomous" in _record(writes)
    assert lead._deploy_blocked is False


@pytest.mark.asyncio
async def test_allow_quality_debt_ships_with_debt(monkeypatch):
    """Explicit --allow-quality-debt is the escape hatch: ship with the debt flagged."""
    lead, writes = _lead(monkeypatch, {"quality_debt_qa": "edge cases skipped"})

    async def fake_commit(target, message, **kw):
        return True, "feed"

    monkeypatch.setattr(deploy, "git_commit_dir", fake_commit)

    await lead._finalize_sprint(
        "build X", deploy_gate=True, auto_approve=True, deploy_commit=True,
        allow_quality_debt=True,
    )

    assert "Decision: approved (auto)" in _record(writes)
    assert lead._deploy_blocked is False
