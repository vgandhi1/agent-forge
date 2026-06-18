"""Context-decay guards: bounded decisions replay (rolling_state_block) + tool-loop circuit breaker.

Mitigates token exhaustion / "lost in the middle" during long adaptive loops without mutating
provider message history in unsafe ways — the breaker drops whole oldest tool exchanges.
"""

import pytest
from rich.console import Console

from agents.data_engineer import DataEngineerAgent
from core.artifact_store import ArtifactStore
from core.context import estimate_tokens, rolling_state_block
from core.message_bus import MessageBus


def _agent(monkeypatch) -> DataEngineerAgent:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return DataEngineerAgent("data_engineer", MessageBus(), ArtifactStore(), Console())


# --------------------------------------------------------------------------- pure helpers


def test_estimate_tokens_roughly_quarter_chars():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 4) == 1
    assert estimate_tokens("a" * 400) == 100


def test_rolling_state_block_verbatim_when_small():
    entries = {"k1": "v1", "k2": "v2"}
    assert rolling_state_block(entries, max_chars=1000) == "- k1: v1\n- k2: v2"


def test_rolling_state_block_empty():
    assert rolling_state_block({}, max_chars=1000) == ""


def test_rolling_state_block_condenses_and_keeps_recent():
    entries = {f"k{i}": "v" * 50 for i in range(40)}
    out = rolling_state_block(entries, max_chars=600, keep_recent=5)
    # Bounded, flags condensing, and keeps the most recent keys verbatim.
    assert len(out) <= 800  # ~max_chars + the condensed marker line
    assert "earlier decision(s) condensed" in out
    assert "k39" in out and "k38" in out


# --------------------------------------------------------------------------- circuit breaker


def _pairs(messages: list, n: int, size: int) -> list:
    for _ in range(n):
        messages.append({"role": "assistant", "content": "a" * size})
        messages.append({"role": "user", "content": "b" * size})
    return messages


def test_compact_messages_noop_under_budget(monkeypatch):
    agent = _agent(monkeypatch)
    agent._context_char_budget = 100_000
    messages = _pairs([{"role": "user", "content": "seed"}], 3, 50)
    out, dropped = agent._compact_messages(messages, initial_len=1)
    assert dropped == 0
    assert out is messages


def test_compact_messages_drops_oldest_pairs_keeps_head_and_tail(monkeypatch):
    agent = _agent(monkeypatch)
    agent._context_char_budget = 300
    messages = _pairs([{"role": "user", "content": "seed"}], 10, 60)
    out, dropped = agent._compact_messages(messages, initial_len=1)

    assert dropped > 0
    assert out[0]["content"] == "seed"          # seed brief preserved
    assert out[-1]["content"] == "b" * 60       # most recent turn preserved
    # Either we got under budget or we stopped at the minimum (head + last pair).
    assert agent._messages_size(out) <= agent._context_char_budget or len(out) == 3


@pytest.mark.asyncio
async def test_build_dynamic_context_bounds_decisions(monkeypatch):
    agent = _agent(monkeypatch)
    agent._decisions_budget_chars = 400
    big = {f"decision_{i}": "x" * 60 for i in range(50)}

    async def fake_recall_all(kind):
        return dict(big) if kind == "decision" else {}

    monkeypatch.setattr(agent.memory, "recall_all", fake_recall_all)
    ctx = await agent._build_dynamic_context()

    assert "## Sprint Decisions" in ctx
    assert "earlier decision(s) condensed" in ctx
    # Bounded — not the full 50×~70-char replay.
    assert len(ctx) < 1500
