"""Tests for the agentic core: execution tools (act→observe) and the Lead's adaptive
planning / re-routing / goal self-check.

These exercise the new opt-in capabilities in isolation (LLM calls are faked), so they run
fast and deterministically without a provider.
"""

from types import SimpleNamespace

import pytest
from rich.console import Console

from agents.base_agent import BaseAgent, _EXEC_TOOLS
from agents.lead import LeadAgent
from core import deploy
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


# --------------------------------------------------------------------------- helpers


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str, tool_input: dict, _id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=_id)


def _response(blocks: list, stop_reason: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=blocks, usage=usage, stop_reason=stop_reason)


class _DummyAgent(BaseAgent):
    async def run(self) -> None:  # pragma: no cover - not used
        pass


def _dummy(monkeypatch) -> _DummyAgent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")  # no Anthropic client / API key
    return _DummyAgent("backend", MessageBus(), ArtifactStore(), Console())


def _lead(monkeypatch) -> LeadAgent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    lead = LeadAgent("lead", MessageBus(), ArtifactStore(), Console())

    async def _empty(kind):
        return {}

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(lead.memory, "recall_all", _empty)
    monkeypatch.setattr(lead.memory, "remember", _noop)
    return lead


# ----------------------------------------------------------------- execution tools


@pytest.mark.asyncio
async def test_exec_tools_run_tests_invoked(monkeypatch):
    """run_tool_loop(exec_tools=True) injects run_tests and feeds its output back."""
    agent = _dummy(monkeypatch)

    captured = {"verify": False}

    async def fake_verify(root, cmd, timeout=180.0):
        captured["verify"] = True
        return "pass", "3 passed"

    monkeypatch.setattr(deploy, "run_verify", fake_verify)

    calls = {"n": 0}

    async def fake_ollama_create(messages, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # tool names available to the model must include the injected exec tools
            names = {t["name"] for t in (tools or [])}
            assert "run_tests" in names and "run_lint" in names
            return _response([_tool_block("run_tests", {})], stop_reason="tool_use")
        return _response([_text_block("done")])

    monkeypatch.setattr(agent, "_ollama_create", fake_ollama_create)

    result = await agent.run_tool_loop(
        user_message="build",
        tool_handlers={},
        tools=[],
        exec_tools=True,
        max_steps=4,
    )

    assert captured["verify"] is True
    assert any(name == "run_tests" for name, _ in result["tool_calls"])
    # the run_verify result string is fed back as a tool result
    assert any("pass" in r for _, _, r in result["results"])


def test_exec_tools_definition_shape():
    names = {t["name"] for t in _EXEC_TOOLS}
    assert names == {"run_tests", "run_lint"}


@pytest.mark.asyncio
async def test_run_lint_handler_no_lint_cmd(monkeypatch):
    agent = _dummy(monkeypatch)
    # DEFAULT_PROFILE has lint_cmd=None → handler should no-op gracefully, not crash.
    out = await agent._run_lint_handler({})
    assert "No lint command" in out


# ----------------------------------------------------------------- adaptive planning


def test_normalize_plan_filters_invalid_entries(monkeypatch):
    lead = _lead(monkeypatch)
    raw = [
        {"role": "pm", "objective": "requirements"},
        {"role": "bogus", "objective": "nope"},   # invalid role
        {"role": "backend"},                        # missing objective
        {"role": "qa", "objective": "tests"},
        "not-a-dict",
    ]
    assert lead._normalize_plan(raw) == [("pm", "requirements"), ("qa", "tests")]


@pytest.mark.asyncio
async def test_plan_phases_uses_proposed_plan(monkeypatch):
    lead = _lead(monkeypatch)

    async def fake_call_llm(*, user_message, dynamic_context="", tools=None):
        return _response([
            _tool_block("propose_plan", {"phases": [
                {"role": "pm", "objective": "a"},
                {"role": "backend", "objective": "b"},
            ]}),
        ])

    monkeypatch.setattr(lead, "_call_llm", fake_call_llm)
    out = await lead._plan_phases("goal", [("pm", "seed")])
    assert out == [("pm", "a"), ("backend", "b")]


@pytest.mark.asyncio
async def test_plan_phases_falls_back_to_seed(monkeypatch):
    lead = _lead(monkeypatch)

    async def fake_call_llm(*, user_message, dynamic_context="", tools=None):
        return _response([_text_block("I have no tools")])  # no propose_plan call

    monkeypatch.setattr(lead, "_call_llm", fake_call_llm)
    seed = [("pm", "reqs"), ("backend", "build")]
    assert await lead._plan_phases("goal", seed) == seed


@pytest.mark.asyncio
async def test_plan_phases_falls_back_on_llm_error(monkeypatch):
    lead = _lead(monkeypatch)

    async def boom(*, user_message, dynamic_context="", tools=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(lead, "_call_llm", boom)
    seed = [("pm", "reqs")]
    assert await lead._plan_phases("goal", seed) == seed


# ----------------------------------------------------------------- adaptive re-routing


@pytest.mark.asyncio
async def test_replan_no_budget_returns_empty(monkeypatch):
    lead = _lead(monkeypatch)
    lead._replan_budget = 0
    out = await lead._replan_after_phase("qa", {"quality_debt": True}, "goal")
    assert out == []


@pytest.mark.asyncio
async def test_replan_no_signal_returns_empty(monkeypatch):
    lead = _lead(monkeypatch)
    lead._replan_budget = 3

    async def fail(*a, **k):
        raise AssertionError("should not consult the LLM without a signal")

    monkeypatch.setattr(lead, "_call_llm", fail)
    out = await lead._replan_after_phase("qa", {"approved": True}, "goal")
    assert out == []


@pytest.mark.asyncio
async def test_replan_inserts_phase_on_quality_debt(monkeypatch):
    lead = _lead(monkeypatch)
    lead._replan_budget = 2

    async def fake_call_llm(*, user_message, dynamic_context="", tools=None):
        return _response([
            _tool_block("adjust_plan", {
                "action": "insert_phase",
                "role": "backend",
                "objective": "fix the failing validation",
                "reason": "QA found a defect",
            }),
        ])

    monkeypatch.setattr(lead, "_call_llm", fake_call_llm)
    out = await lead._replan_after_phase("qa", {"quality_debt": True}, "goal")
    assert out == [("backend", "fix the failing validation")]
    assert lead._replan_budget == 1  # consumed one unit


@pytest.mark.asyncio
async def test_replan_continue_returns_empty(monkeypatch):
    lead = _lead(monkeypatch)
    lead._replan_budget = 2

    async def fake_call_llm(*, user_message, dynamic_context="", tools=None):
        return _response([_tool_block("adjust_plan", {"action": "continue"})])

    monkeypatch.setattr(lead, "_call_llm", fake_call_llm)
    out = await lead._replan_after_phase("qa", {"escalated": True}, "goal")
    assert out == []
    assert lead._replan_budget == 2  # not consumed


# ----------------------------------------------------------------- goal self-check


@pytest.mark.asyncio
async def test_verify_goal_met_true(monkeypatch):
    lead = _lead(monkeypatch)
    lead._approved_artifacts = {"backend_artifact": "app/main.py"}

    async def fake_call_llm(*, user_message, dynamic_context="", tools=None):
        return _response([_text_block("MET")])

    monkeypatch.setattr(lead, "_call_llm", fake_call_llm)
    met, gaps = await lead._verify_goal_met("goal")
    assert met is True and gaps == ""


@pytest.mark.asyncio
async def test_verify_goal_met_unmet_extracts_gaps(monkeypatch):
    lead = _lead(monkeypatch)

    async def fake_call_llm(*, user_message, dynamic_context="", tools=None):
        return _response([_text_block("UNMET: missing the inference serving module")])

    monkeypatch.setattr(lead, "_call_llm", fake_call_llm)
    met, gaps = await lead._verify_goal_met("goal")
    assert met is False
    assert "inference serving" in gaps


@pytest.mark.asyncio
async def test_verify_goal_met_error_defaults_met(monkeypatch):
    lead = _lead(monkeypatch)

    async def boom(*, user_message, dynamic_context="", tools=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(lead, "_call_llm", boom)
    met, gaps = await lead._verify_goal_met("goal")
    assert met is True and gaps == ""  # never block the run on a hiccup
