import json

import pytest
from rich.console import Console

from core import handoff
from core.handoff import CHECKPOINT_PATH, goal_fingerprint, record_phase
from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


class _FakeStore:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    async def read(self, path):
        return self.files.get(str(path), "[File not found]")

    async def write(self, path, content):
        self.files[str(path)] = content


@pytest.mark.asyncio
async def test_record_phase_writes_handoff_and_checkpoint() -> None:
    store = _FakeStore()
    await record_phase(store, goal="build app", role="pm", brief="reqs",
                       files=["docs/requirements.md"], review_summary="approved")
    assert "# Handoff — pm" in store.files["handoff/pm.md"]
    assert "docs/requirements.md" in store.files["handoff/pm.md"]
    cp = json.loads(store.files[CHECKPOINT_PATH])
    assert cp["goal_fp"] == goal_fingerprint("build app")
    assert cp["completed"] == ["pm"]
    assert cp["artifacts"]["pm_artifact"] == "docs/requirements.md"


@pytest.mark.asyncio
async def test_checkpoint_resets_on_goal_change() -> None:
    store = _FakeStore()
    await record_phase(store, goal="goal one", role="pm", brief="", files=["a.md"], review_summary="")
    await record_phase(store, goal="goal two", role="architect", brief="", files=["b.md"], review_summary="")
    cp = json.loads(store.files[CHECKPOINT_PATH])
    assert cp["goal_fp"] == goal_fingerprint("goal two")
    assert cp["completed"] == ["architect"]  # pm dropped — different goal


@pytest.mark.asyncio
async def test_resume_skips_completed_phases(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    lead = LeadAgent("lead", MessageBus(), ArtifactStore(), Console())

    goal = "build app"
    ran: list[str] = []

    async def fake_run_phase(role, desc, g):
        ran.append(role)

    async def fake_finalize(*a, **k):
        return None

    async def fake_remember(*a, **k):
        return None

    async def fake_load_checkpoint(store):
        return {"goal_fp": goal_fingerprint(goal), "completed": ["pm", "architect"],
                "artifacts": {"pm_artifact": "docs/requirements.md"}}

    monkeypatch.setattr(lead, "_run_phase", fake_run_phase)
    monkeypatch.setattr(lead, "_finalize_sprint", fake_finalize)
    monkeypatch.setattr(lead.memory, "remember", fake_remember)
    monkeypatch.setattr(handoff, "load_checkpoint", fake_load_checkpoint)

    phases = [("pm", "x"), ("architect", "x"), ("backend", "x"), ("qa", "x")]
    await lead.run_development_cycle(goal, phases=phases, resume=True)

    assert ran == ["backend", "qa"]  # pm + architect skipped
    assert lead._approved_artifacts["pm_artifact"] == "docs/requirements.md"


@pytest.mark.asyncio
async def test_no_resume_runs_all(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    lead = LeadAgent("lead", MessageBus(), ArtifactStore(), Console())
    ran: list[str] = []

    async def fake_run_phase(role, desc, g):
        ran.append(role)

    async def fake_finalize(*a, **k):
        return None

    async def fake_remember(*a, **k):
        return None

    monkeypatch.setattr(lead, "_run_phase", fake_run_phase)
    monkeypatch.setattr(lead, "_finalize_sprint", fake_finalize)
    monkeypatch.setattr(lead.memory, "remember", fake_remember)

    phases = [("pm", "x"), ("backend", "x")]
    await lead.run_development_cycle("g", phases=phases, resume=False)
    assert ran == ["pm", "backend"]
