"""Diff-only reviews: a bounded unified diff lets the Reviewer focus on the change on revision
attempts instead of re-reading whole files (component-level enhancement)."""

import pytest
from rich.console import Console

from agents.lead import LeadAgent
from agents.reviewer import ReviewerAgent
from core import artifact_store
from core.artifact_store import ArtifactStore
from core.diffs import unified_diff
from core.message_bus import MessageBus


# --------------------------------------------------------------------------- pure diff util


def test_unified_diff_empty_when_unchanged():
    assert unified_diff("same\n", "same\n", "f.py") == ""


def test_unified_diff_shows_change_and_path():
    d = unified_diff("a = 1\n", "a = 2\n", "mod.py")
    assert "mod.py" in d
    assert "-a = 1" in d and "+a = 2" in d


def test_unified_diff_truncates():
    old = "x\n" * 1000
    new = "y\n" * 1000
    d = unified_diff(old, new, "big.py", max_chars=200)
    assert len(d) <= 260
    assert "diff truncated" in d


# --------------------------------------------------------------------------- Lead snapshot/diffs


@pytest.fixture
def roots(tmp_path):
    orig_ws, orig_md = artifact_store.WORKSPACE, artifact_store.METADATA_ROOT
    artifact_store.configure_roots(tmp_path, tmp_path)
    yield tmp_path
    artifact_store.configure_roots(orig_ws, orig_md)


@pytest.mark.asyncio
async def test_collect_diffs_first_then_change(monkeypatch, roots):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    lead = LeadAgent("lead", MessageBus(), ArtifactStore(), Console())

    await lead.artifacts.write("svc.py", "def f():\n    return 1\n")
    # First review of the file: snapshot taken, no diff to show.
    assert await lead._collect_diffs(["svc.py"]) == ""

    await lead.artifacts.write("svc.py", "def f():\n    return 2\n")
    diff = await lead._collect_diffs(["svc.py"])
    assert "-    return 1" in diff and "+    return 2" in diff


# --------------------------------------------------------------------------- reviewer prompt wiring


@pytest.mark.asyncio
async def test_review_includes_diff_block_when_provided(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    reviewer = ReviewerAgent("reviewer", MessageBus(), ArtifactStore(), Console())

    captured: dict = {}

    async def fake_loop(*args, **kwargs):
        captured["user_message"] = kwargs.get("user_message", "")
        return {}

    monkeypatch.setattr(reviewer, "run_tool_loop", fake_loop)

    await reviewer.review(
        phase_role="backend", summary="s", files=["a.py"],
        diffs="--- a/a.py\n+++ b/a.py\n-x\n+y\n",
    )
    assert "This is a revision" in captured["user_message"]
    assert "```diff" in captured["user_message"]


@pytest.mark.asyncio
async def test_review_no_diff_block_without_diffs(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    reviewer = ReviewerAgent("reviewer", MessageBus(), ArtifactStore(), Console())

    captured: dict = {}

    async def fake_loop(*args, **kwargs):
        captured["user_message"] = kwargs.get("user_message", "")
        return {}

    monkeypatch.setattr(reviewer, "run_tool_loop", fake_loop)

    await reviewer.review(phase_role="backend", summary="s", files=["a.py"])
    assert "This is a revision" not in captured["user_message"]
