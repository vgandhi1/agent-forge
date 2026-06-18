"""Escalation safe-pause timeout: if no operator responds within the window, defer to the deploy
gate instead of blocking the run forever (component-level enhancement)."""

import time

import pytest
from rich.console import Console

from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


def _lead(monkeypatch) -> LeadAgent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return LeadAgent("lead", MessageBus(), ArtifactStore(), Console())


@pytest.mark.asyncio
async def test_safe_pause_on_timeout(monkeypatch):
    lead = _lead(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    lead._escalation_timeout = 0.05
    lead._read_guidance = lambda: (time.sleep(0.5) or "")  # slower than the timeout

    remembered: list[tuple] = []

    async def fake_remember(key, value, kind="context"):
        remembered.append((key, value, kind))

    monkeypatch.setattr(lead.memory, "remember", fake_remember)
    await lead._default_escalation_pause("backend", "JWT or sessions?")

    keys = [k for k, _, _ in remembered]
    assert any(k.startswith("escalation_timeout_backend") for k in keys)
    assert not any(k.startswith("escalation_guidance") for k in keys)


@pytest.mark.asyncio
async def test_guidance_recorded_when_answered(monkeypatch):
    lead = _lead(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    lead._escalation_timeout = 5.0
    lead._read_guidance = lambda: "use JWT"

    remembered: list[tuple] = []

    async def fake_remember(key, value, kind="context"):
        remembered.append((key, value, kind))

    monkeypatch.setattr(lead.memory, "remember", fake_remember)
    await lead._default_escalation_pause("backend", "JWT or sessions?")

    assert ("escalation_guidance_backend", "use JWT", "decision") in remembered
