import pytest
from rich.console import Console

from agents.lead import LeadAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus

GOAL = (
    "Deliver items for CLaimLens and QualityMind-RAG: add source_type to the ClaimNarrative "
    "model, extend evaluate.py, and update data/generate_sample_data.py."
)


def _lead(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("AGENTFORGE_SKIP_REVIEWER_PREFLIGHT", raising=False)
    monkeypatch.delenv("AGENTFORGE_SKIP_GROUNDING", raising=False)
    lead = LeadAgent("lead", MessageBus(), ArtifactStore(), Console())

    async def fake_write(path, content):
        return path

    async def fake_remember(*a, **k):
        return None

    monkeypatch.setattr(lead.artifacts, "write", fake_write)
    monkeypatch.setattr(lead.memory, "remember", fake_remember)
    return lead


# ----------------------------------------------------------------- reviewer preflight


@pytest.mark.asyncio
async def test_preflight_passes_when_reviewer_submits(monkeypatch):
    lead = _lead(monkeypatch)

    async def fake_review(**kwargs):
        return {"submitted": True, "decision": "approve", "must_fix": []}

    monkeypatch.setattr(lead.reviewer, "review", fake_review)
    assert await lead._reviewer_preflight() is True


@pytest.mark.asyncio
async def test_preflight_fails_when_reviewer_never_submits(monkeypatch):
    lead = _lead(monkeypatch)

    async def fake_review(**kwargs):
        # Mirrors reviewer.py's no-verdict fallback.
        return {"submitted": False, "decision": "reject",
                "must_fix": ["Reviewer did not submit a verdict — resubmit the artifact for review."]}

    monkeypatch.setattr(lead.reviewer, "review", fake_review)
    assert await lead._reviewer_preflight() is False


@pytest.mark.asyncio
async def test_preflight_skippable_via_env(monkeypatch):
    lead = _lead(monkeypatch)
    monkeypatch.setenv("AGENTFORGE_SKIP_REVIEWER_PREFLIGHT", "1")

    called = {"v": False}

    async def fake_review(**kwargs):
        called["v"] = True
        return {"submitted": False}

    monkeypatch.setattr(lead.reviewer, "review", fake_review)
    assert await lead._reviewer_preflight() is True
    assert called["v"] is False  # skipped → reviewer never invoked


# ----------------------------------------------------------------- grounding gate


@pytest.mark.asyncio
async def test_grounding_gate_rejects_off_domain_pm(monkeypatch):
    lead = _lead(monkeypatch)
    lead._goal = GOAL

    async def fake_read(path):
        return "# DailyEase\nA tasks, habits, finance and wellness app for busy people."

    monkeypatch.setattr(lead.artifacts, "read", fake_read)

    reviewer_called = {"v": False}

    async def fake_review(**kwargs):
        reviewer_called["v"] = True
        return {"submitted": True, "decision": "approve"}

    monkeypatch.setattr(lead.reviewer, "review", fake_review)

    approved = await lead._review_artifact("pm", {"primary_path": "docs/requirements.md"}, 0)
    assert approved is False
    assert reviewer_called["v"] is False  # short-circuited before spending a reviewer call


@pytest.mark.asyncio
async def test_grounding_gate_passes_on_topic_pm(monkeypatch):
    lead = _lead(monkeypatch)
    lead._goal = GOAL

    async def fake_read(path):
        return (
            "# CLaimLens Requirements\nAdd source_type to ClaimNarrative, extend evaluate.py, "
            "update generate_sample_data.py, integrate QualityMind-RAG."
        )

    monkeypatch.setattr(lead.artifacts, "read", fake_read)

    async def fake_review(**kwargs):
        return {"submitted": True, "decision": "approve", "summary": "ok", "must_fix": []}

    monkeypatch.setattr(lead.reviewer, "review", fake_review)
    monkeypatch.setattr(lead.memory, "recall_all", _empty)

    approved = await lead._review_artifact("pm", {"primary_path": "docs/requirements.md"}, 0)
    assert approved is True  # grounded → reviewer consulted → approved


@pytest.mark.asyncio
async def test_grounding_gate_skips_non_spec_roles(monkeypatch):
    lead = _lead(monkeypatch)
    lead._goal = GOAL

    # backend is not graded even with off-domain text; gate returns no gap.
    async def fake_read(path):
        return "totally unrelated"

    monkeypatch.setattr(lead.artifacts, "read", fake_read)
    assert await lead._grounding_gap("backend", {"primary_path": "x.py"}) == []


async def _empty(kind):
    return {}
