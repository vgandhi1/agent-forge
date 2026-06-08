"""Reviewer paginated read (roadmap B2): large files must be pageable, not truncated.

The reviewer's read_file_handler delegates to ArtifactStore.read_paginated, returning a
window of numbered lines plus a "… N more lines" footer instead of hard-cutting at 8k chars.
These tests build a real workspace tree and drive the handler the reviewer registers.
"""
import pytest
from rich.console import Console

import core.artifact_store as artifact_store
from agents.reviewer import ReviewerAgent, _DEFAULT_READ_LIMIT
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    """Point the workspace at a temp dir so ArtifactStore.read_paginated hits real files."""
    monkeypatch.setattr(artifact_store, "WORKSPACE", tmp_path)
    monkeypatch.setattr(artifact_store, "METADATA_ROOT", tmp_path)
    monkeypatch.setattr(ArtifactStore, "WORKSPACE", tmp_path)
    (tmp_path / "dailyease").mkdir()
    return tmp_path


def _reviewer(monkeypatch) -> ReviewerAgent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return ReviewerAgent("reviewer", MessageBus(), ArtifactStore(), Console())


async def _read_handler(agent: ReviewerAgent):
    """Capture the read_file handler the reviewer registers in run_tool_loop."""
    captured: dict = {}

    async def fake_loop(self, *, tool_handlers, **kwargs):
        captured.update(tool_handlers)
        return None

    orig = ReviewerAgent.run_tool_loop
    ReviewerAgent.run_tool_loop = fake_loop  # type: ignore[assignment]
    try:
        await agent.review(phase_role="backend", summary="s", files=["dailyease/big.py"])
    finally:
        ReviewerAgent.run_tool_loop = orig  # type: ignore[assignment]
    return captured["read_file"]


@pytest.mark.asyncio
async def test_read_file_returns_paginated_window_with_footer(ws, monkeypatch) -> None:
    (ws / "dailyease" / "big.py").write_text("\n".join(f"line {i}" for i in range(1000)))
    handler = await _read_handler(_reviewer(monkeypatch))

    out = await handler({"path": "dailyease/big.py"})
    lines = out.splitlines()
    # First window is the default limit of numbered lines, not a char-truncated blob.
    assert lines[0] == "1\tline 0"
    assert lines[_DEFAULT_READ_LIMIT - 1] == f"{_DEFAULT_READ_LIMIT}\tline {_DEFAULT_READ_LIMIT - 1}"
    # Footer points at the next window rather than the old "[truncated for review]" marker.
    assert "…[truncated for review]" not in out
    assert f"{1000 - _DEFAULT_READ_LIMIT} more lines (use offset={_DEFAULT_READ_LIMIT})" in out


@pytest.mark.asyncio
async def test_read_file_offset_returns_later_window(ws, monkeypatch) -> None:
    (ws / "dailyease" / "big.py").write_text("\n".join(f"line {i}" for i in range(1000)))
    handler = await _read_handler(_reviewer(monkeypatch))

    out = await handler({"path": "dailyease/big.py", "offset": 500, "limit": 100})
    lines = out.splitlines()
    assert lines[0] == "501\tline 500"
    assert lines[99] == "600\tline 599"
    assert "more lines (use offset=600)" in out


@pytest.mark.asyncio
async def test_read_file_missing_returns_not_found_marker(ws, monkeypatch) -> None:
    handler = await _read_handler(_reviewer(monkeypatch))
    out = await handler({"path": "dailyease/missing.py"})
    assert out.startswith("[File not found:")


@pytest.mark.asyncio
async def test_read_file_small_file_no_footer(ws, monkeypatch) -> None:
    (ws / "dailyease" / "small.py").write_text("def f():\n    return 1")
    handler = await _read_handler(_reviewer(monkeypatch))

    out = await handler({"path": "dailyease/small.py"})
    assert out == "1\tdef f():\n2\t    return 1"
    assert "more lines" not in out
