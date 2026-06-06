from types import SimpleNamespace

import pytest
from rich.console import Console

from agents.base_agent import BaseAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus
from core.message_types import MessageType


def _tool_use(name, tool_input, block_id="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class _Agent(BaseAgent):
    async def run(self) -> None:
        pass


@pytest.mark.asyncio
async def test_request_decision_records_and_publishes(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    bus = MessageBus()
    agent = _Agent("backend", bus, ArtifactStore(), Console())

    remembered: list[tuple] = []

    async def fake_remember(key, value, kind="context"):
        remembered.append((key, value, kind))

    monkeypatch.setattr(agent.memory, "remember", fake_remember)

    responses = [
        _response([_tool_use("request_decision", {
            "question": "Use JWT or session cookies for auth?",
            "assumption": "JWT",
        })], "tool_use"),
        _response([_text("continuing with JWT")], "end_turn"),
    ]

    async def fake_create(messages, tools=None):
        return responses.pop(0)

    monkeypatch.setattr(agent, "_ollama_create", fake_create)

    result = await agent.run_tool_loop(
        user_message="implement auth",
        tool_handlers={},  # scope lock supplies request_decision
        tools=[],
        max_steps=6,
    )

    _, _, res = result["results"][0]
    assert "Escalation recorded" in res

    assert len(remembered) == 1
    key, value, kind = remembered[0]
    assert key.startswith("escalation_backend_")
    assert kind == "decision"
    assert "JWT" in value

    msg = await bus.receive("lead", timeout=2.0)
    assert msg is not None
    assert msg.type == MessageType.ESCALATION
    assert msg.payload["role"] == "backend"


@pytest.mark.asyncio
async def test_request_decision_absent_when_scope_lock_off(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    agent = _Agent("backend", MessageBus(), ArtifactStore(), Console())

    responses = [
        _response([_tool_use("request_decision", {"question": "x"})], "tool_use"),
        _response([_text("done")], "end_turn"),
    ]

    async def fake_create(messages, tools=None):
        return responses.pop(0)

    monkeypatch.setattr(agent, "_ollama_create", fake_create)

    result = await agent.run_tool_loop(
        user_message="task",
        tool_handlers={},
        tools=[],
        max_steps=6,
        scope_lock=False,
    )
    _, _, res = result["results"][0]
    assert "no handler" in res.lower()
