from types import SimpleNamespace

import pytest
from rich.console import Console

from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus
from core.message_types import Message, MessageType


def _lead(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    bus = MessageBus()
    lead = LeadAgent("lead", bus, ArtifactStore(), Console())
    lead._current_brief = "build the API"

    async def no_context():
        return ""

    async def fake_remember(*a, **k):
        return None

    monkeypatch.setattr(lead, "_build_dynamic_context", no_context)
    monkeypatch.setattr(lead.memory, "remember", fake_remember)
    return lead, bus


def _llm_text(text):
    async def fake(user_message, dynamic_context="", tools=None):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
    return fake


async def _send_plan(bus):
    await bus.publish(Message(
        type=MessageType.CONSULT_REQUEST,
        sender="backend",
        recipient="lead",
        payload={"kind": "build_plan", "plan": "create models, schemas, routers"},
        priority=2,
    ))


@pytest.mark.asyncio
async def test_plan_gate_approves(monkeypatch) -> None:
    lead, bus = _lead(monkeypatch)
    monkeypatch.setattr(lead, "_call_llm", _llm_text("APPROVE"))

    await _send_plan(bus)
    await lead._handle_plan_gate("backend")

    resp = await bus.receive("backend", timeout=2.0)
    assert resp is not None
    assert resp.type == MessageType.CONSULT_RESPONSE
    assert resp.payload["approved"] is True


@pytest.mark.asyncio
async def test_plan_gate_redirects(monkeypatch) -> None:
    lead, bus = _lead(monkeypatch)
    monkeypatch.setattr(lead, "_call_llm", _llm_text("REDIRECT: split services from routers"))

    await _send_plan(bus)
    await lead._handle_plan_gate("backend")

    resp = await bus.receive("backend", timeout=2.0)
    assert resp.type == MessageType.CONSULT_RESPONSE
    assert resp.payload["approved"] is False
    assert "split services" in resp.payload["notes"]


@pytest.mark.asyncio
async def test_plan_gate_fail_open_on_unexpected_message(monkeypatch) -> None:
    lead, bus = _lead(monkeypatch)
    monkeypatch.setattr(lead, "_call_llm", _llm_text("APPROVE"))

    # A non-plan message arrives → fail open (proceed, no CONSULT_RESPONSE published).
    await bus.publish(Message(
        type=MessageType.TASK_COMPLETE, sender="backend", recipient="lead", payload={}, priority=2,
    ))
    await lead._handle_plan_gate("backend")
    resp = await bus.receive("backend", timeout=0.5)
    assert resp is None
