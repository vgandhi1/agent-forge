from types import SimpleNamespace

import pytest
from rich.console import Console

import core.known_gaps as known_gaps
from core.known_gaps import GAPS_PATH, log_gap
from agents.base_agent import BaseAgent
from agents.reviewer import ReviewerAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


class _FakeStore:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    async def read(self, path):
        return self.files.get(str(path), "[File not found]")

    async def write(self, path, content):
        self.files[str(path)] = content


def _tool_use(name, tool_input, block_id="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class _Agent(BaseAgent):
    async def run(self) -> None:
        pass


def _agent(monkeypatch) -> _Agent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return _Agent("backend", MessageBus(), ArtifactStore(), Console())


@pytest.mark.asyncio
async def test_log_gap_creates_and_appends() -> None:
    store = _FakeStore()
    await log_gap(store, "backend", "bug", "auth endpoint missing rate limit")
    await log_gap(store, "qa", "tech-debt", "no test for timezone edge case")
    content = store.files[GAPS_PATH]
    assert content.startswith("# Known Gaps")
    assert "**backend** (bug): auth endpoint missing rate limit" in content
    assert "**qa** (tech-debt): no test for timezone edge case" in content
    assert content.count("- [") == 2


@pytest.mark.asyncio
async def test_scope_lock_injects_log_known_gap(monkeypatch) -> None:
    agent = _agent(monkeypatch)
    logged: list[tuple] = []

    async def fake_log_gap(store, source, category, description):
        logged.append((source, category, description))

    monkeypatch.setattr(known_gaps, "log_gap", fake_log_gap)

    responses = [
        _response([_tool_use("log_known_gap", {"category": "bug", "description": "found unrelated bug"})], "tool_use"),
        _response([_text("done")], "end_turn"),
    ]

    async def fake_create(messages, tools=None):
        return responses.pop(0)

    monkeypatch.setattr(agent, "_ollama_create", fake_create)

    result = await agent.run_tool_loop(
        user_message="do task",
        tool_handlers={},  # caller did NOT provide a handler; scope lock supplies one
        tools=[],
        max_steps=6,
    )
    # handled by injected handler, not the "no handler" fallback
    _, _, res = result["results"][0]
    assert "Known gap recorded" in res
    assert logged == [("backend", "bug", "found unrelated bug")]


@pytest.mark.asyncio
async def test_scope_lock_disabled_has_no_handler(monkeypatch) -> None:
    agent = _agent(monkeypatch)

    responses = [
        _response([_tool_use("log_known_gap", {"description": "x"})], "tool_use"),
        _response([_text("done")], "end_turn"),
    ]

    async def fake_create(messages, tools=None):
        return responses.pop(0)

    monkeypatch.setattr(agent, "_ollama_create", fake_create)

    result = await agent.run_tool_loop(
        user_message="do task",
        tool_handlers={},
        tools=[],
        max_steps=6,
        scope_lock=False,
    )
    _, _, res = result["results"][0]
    assert "no handler" in res.lower()


@pytest.mark.asyncio
async def test_reviewer_routes_drift_to_known_gaps(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    reviewer = ReviewerAgent("reviewer", MessageBus(), ArtifactStore(), Console())

    logged: list[tuple] = []

    async def fake_log_gap(store, source, category, description):
        logged.append((source, category, description))

    monkeypatch.setattr(known_gaps, "log_gap", fake_log_gap)

    responses = [
        _response([_tool_use("submit_review", {
            "decision": "approve",
            "summary": "ok",
            "drift": ["added an unrequested /admin endpoint"],
        })], "tool_use"),
        _response([_text("done")], "end_turn"),
    ]

    async def fake_create(messages, tools=None):
        return responses.pop(0)

    monkeypatch.setattr(reviewer, "_ollama_create", fake_create)

    verdict = await reviewer.review(phase_role="backend", summary="impl", files=["dailyease/main.py"])
    assert verdict["decision"] == "approve"
    assert logged == [("reviewer:backend", "drift", "added an unrequested /admin endpoint")]
