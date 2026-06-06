from types import SimpleNamespace

import pytest
from rich.console import Console

from agents.reviewer import ReviewerAgent
from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus
from core.message_types import MessageType


def _tool_use(name: str, tool_input: dict, block_id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _response(blocks: list, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def _reviewer(monkeypatch) -> ReviewerAgent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return ReviewerAgent("reviewer", MessageBus(), ArtifactStore(), Console())


def _script(monkeypatch, agent, responses: list) -> None:
    async def fake_create(messages, tools=None):
        return responses.pop(0)

    monkeypatch.setattr(agent, "_ollama_create", fake_create)


@pytest.mark.asyncio
async def test_reviewer_approve(monkeypatch) -> None:
    agent = _reviewer(monkeypatch)
    _script(monkeypatch, agent, [
        _response([_tool_use("submit_review", {"decision": "approve", "summary": "meets brief"})], "tool_use"),
        _response([_text("done")], "end_turn"),
    ])
    verdict = await agent.review(phase_role="pm", summary="reqs", files=["docs/x.md"])
    assert verdict["decision"] == "approve"
    assert verdict["summary"] == "meets brief"


@pytest.mark.asyncio
async def test_reviewer_no_verdict_defaults_to_reject(monkeypatch) -> None:
    agent = _reviewer(monkeypatch)
    _script(monkeypatch, agent, [
        _response([_text("looks fine to me")], "end_turn"),
    ])
    verdict = await agent.review(phase_role="backend", summary="impl", files=["dailyease/main.py"])
    assert verdict["decision"] == "reject"
    assert verdict["must_fix"]  # non-empty default reason


@pytest.mark.asyncio
async def test_reviewer_reads_files_then_rejects(monkeypatch) -> None:
    agent = _reviewer(monkeypatch)
    reads: list[str] = []

    async def fake_read(path):
        reads.append(str(path))
        return "def f(): pass"

    monkeypatch.setattr(agent.artifacts, "read", fake_read)
    _script(monkeypatch, agent, [
        _response([_tool_use("read_file", {"path": "dailyease/main.py"})], "tool_use"),
        _response([_tool_use("submit_review", {
            "decision": "reject",
            "summary": "missing error handling",
            "must_fix": ["dailyease/main.py — no try/except — wrap DB calls"],
        })], "tool_use"),
        _response([_text("submitted")], "end_turn"),
    ])
    verdict = await agent.review(phase_role="backend", summary="impl", files=["dailyease/main.py"])
    assert reads == ["dailyease/main.py"]
    assert verdict["decision"] == "reject"
    assert len(verdict["must_fix"]) == 1


@pytest.mark.asyncio
async def test_lead_gate_rejects_on_reviewer_reject(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    bus = MessageBus()
    lead = LeadAgent("lead", bus, ArtifactStore(), Console())
    lead._current_brief = "build X"

    async def no_context():
        return ""

    monkeypatch.setattr(lead, "_build_dynamic_context", no_context)

    async def fake_review(**kwargs):
        return {
            "decision": "reject",
            "summary": "bad",
            "must_fix": ["file.py — wrong — fix it"],
            "should_fix": [],
            "escalation_question": "",
        }

    monkeypatch.setattr(lead.reviewer, "review", fake_review)

    approved = await lead._review_artifact("backend", {"primary_path": "dailyease/main.py", "files": ["x"], "summary": "s"}, 0)
    assert approved is False
    msg = await bus.receive("backend", timeout=2.0)
    assert msg is not None
    assert msg.type == MessageType.ARTIFACT_REJECTED
    assert "Must fix" in msg.payload["revision_notes"]


@pytest.mark.asyncio
async def test_lead_gate_approves_on_reviewer_approve(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    bus = MessageBus()
    lead = LeadAgent("lead", bus, ArtifactStore(), Console())
    lead._current_brief = "build X"

    async def no_context():
        return ""

    monkeypatch.setattr(lead, "_build_dynamic_context", no_context)

    async def fake_review(**kwargs):
        return {"decision": "approve", "summary": "good", "must_fix": [], "should_fix": [], "escalation_question": ""}

    monkeypatch.setattr(lead.reviewer, "review", fake_review)

    approved = await lead._review_artifact("pm", {"primary_path": "docs/requirements.md", "files": ["x"], "summary": "s"}, 0)
    assert approved is True
    msg = await bus.receive("pm", timeout=2.0)
    assert msg is not None
    assert msg.type == MessageType.ARTIFACT_APPROVED
