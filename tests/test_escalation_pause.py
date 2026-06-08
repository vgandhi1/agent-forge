"""Mid-sprint escalation pause: with --deploy-gate, the Lead invites operator guidance
when a phase escalates, instead of only surfacing it at the deploy gate.

Closes feedback.md Part 3 (#3): escalation was recorded but the Lead did not pause mid-phase.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus
from core.message_types import Message, MessageType


def _lead(monkeypatch) -> LeadAgent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return LeadAgent("lead", MessageBus(), ArtifactStore(), Console())


def _escalation_msg() -> Message:
    return Message(
        type=MessageType.ESCALATION,
        sender="backend",
        recipient="lead",
        payload={"question": "JWT or session cookies for auth?", "role": "backend"},
        priority=1,
    )


@pytest.mark.asyncio
async def test_pause_invoked_when_deploy_gate_on(monkeypatch):
    lead = _lead(monkeypatch)
    lead._deploy_gate = True

    seen: list[tuple[str, str]] = []

    async def fake_pause(role: str, question: str) -> None:
        seen.append((role, question))

    lead._escalation_pause_fn = fake_pause
    await lead._handle_escalation("backend", _escalation_msg())

    assert seen == [("backend", "JWT or session cookies for auth?")]


@pytest.mark.asyncio
async def test_pause_skipped_when_deploy_gate_off(monkeypatch):
    lead = _lead(monkeypatch)
    lead._deploy_gate = False

    seen: list[tuple[str, str]] = []

    async def fake_pause(role: str, question: str) -> None:
        seen.append((role, question))

    lead._escalation_pause_fn = fake_pause
    await lead._handle_escalation("backend", _escalation_msg())

    assert seen == []


@pytest.mark.asyncio
async def test_default_pause_no_tty_records_nothing(monkeypatch):
    """Without a TTY the default pause must not block and must not invent guidance."""
    lead = _lead(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    remembered: list[tuple] = []

    async def fake_remember(key, value, kind="context"):
        remembered.append((key, value, kind))

    monkeypatch.setattr(lead.memory, "remember", fake_remember)
    await lead._default_escalation_pause("backend", "ambiguous?")
    assert remembered == []
