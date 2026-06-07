import pytest
from rich.console import Console

from agents.base_agent import BaseAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus
from core.message_types import Message, MessageType


class _Agent(BaseAgent):
    async def run(self) -> None:
        pass


def _agent(monkeypatch) -> _Agent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return _Agent("backend", MessageBus(), ArtifactStore(), Console())


async def _put(bus, mtype, notes=""):
    await bus.publish(Message(
        type=mtype, sender="lead", recipient="backend",
        payload={"revision_notes": notes}, priority=1,
    ))


@pytest.mark.asyncio
async def test_handles_multiple_rejections(monkeypatch) -> None:
    agent = _agent(monkeypatch)
    calls: list[str] = []

    async def revise(notes):
        calls.append(notes)

    # Two rejects then an approve — the worker must revise twice, not stall on the 2nd.
    await _put(agent.bus, MessageType.ARTIFACT_REJECTED, "fix A")
    await _put(agent.bus, MessageType.ARTIFACT_REJECTED, "fix B")
    await _put(agent.bus, MessageType.ARTIFACT_APPROVED)

    await agent._await_reviews("Backend", revise, timeout=2.0)
    assert calls == ["fix A", "fix B"]


@pytest.mark.asyncio
async def test_approve_first_no_revision(monkeypatch) -> None:
    agent = _agent(monkeypatch)
    calls: list[str] = []

    async def revise(notes):
        calls.append(notes)

    await _put(agent.bus, MessageType.ARTIFACT_APPROVED)
    await agent._await_reviews("Backend", revise, timeout=2.0)
    assert calls == []


@pytest.mark.asyncio
async def test_shutdown_stops_wait(monkeypatch) -> None:
    agent = _agent(monkeypatch)

    async def revise(notes):
        raise AssertionError("should not revise on shutdown")

    await _put(agent.bus, MessageType.SHUTDOWN)
    await agent._await_reviews("Backend", revise, timeout=2.0)  # returns cleanly


@pytest.mark.asyncio
async def test_timeout_stops_without_hang(monkeypatch) -> None:
    agent = _agent(monkeypatch)

    async def revise(notes):
        raise AssertionError("no message → no revise")

    # empty mailbox → returns at timeout, does not hang
    await agent._await_reviews("Backend", revise, timeout=0.3)
