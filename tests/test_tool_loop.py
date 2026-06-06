from types import SimpleNamespace

import pytest
from rich.console import Console

from agents.base_agent import BaseAgent
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


def _tool_use(name: str, tool_input: dict, block_id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _response(blocks: list, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class _Agent(BaseAgent):
    async def run(self) -> None:  # abstract stub
        pass


def _make_agent(monkeypatch) -> _Agent:
    # ollama provider avoids constructing an Anthropic client (no API key needed).
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    return _Agent("backend", MessageBus(), ArtifactStore(), Console())


@pytest.mark.asyncio
async def test_tool_loop_iterates_then_stops(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)

    scripted = [
        _response([_tool_use("write_file", {"path": "a.py", "content": "1"}, "t1")], "tool_use"),
        _response([_tool_use("write_file", {"path": "b.py", "content": "22"}, "t2")], "tool_use"),
        _response([_text("all done")], "end_turn"),
    ]
    calls: list[int] = []

    async def fake_create(messages, tools=None):
        calls.append(len(messages))  # snapshot length; messages is mutated in place
        return scripted.pop(0)

    monkeypatch.setattr(agent, "_ollama_create", fake_create)

    written: list[str] = []

    async def handler(tool_input: dict) -> str:
        written.append(tool_input["path"])
        return f"wrote {tool_input['path']}"

    result = await agent.run_tool_loop(
        user_message="build it",
        tool_handlers={"write_file": handler},
        tools=[{"name": "write_file"}],
        max_steps=10,
    )

    assert written == ["a.py", "b.py"]
    assert result["steps"] == 3
    assert result["stop"] == "done"
    assert len(result["tool_calls"]) == 2
    assert result["final_text"] == "all done"
    # Loop fed tool results back: each turn grows the message list.
    assert calls[1] > calls[0]


@pytest.mark.asyncio
async def test_tool_loop_respects_max_steps(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)

    async def always_tool(messages, tools=None):
        return _response([_tool_use("write_file", {"path": "x.py", "content": "x"})], "tool_use")

    monkeypatch.setattr(agent, "_ollama_create", always_tool)

    async def handler(tool_input: dict) -> str:
        return "ok"

    result = await agent.run_tool_loop(
        user_message="loop forever",
        tool_handlers={"write_file": handler},
        tools=[{"name": "write_file"}],
        max_steps=3,
    )

    assert result["steps"] == 3
    assert result["stop"] == "max_steps"


@pytest.mark.asyncio
async def test_tool_loop_handler_error_surfaced(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)

    scripted = [
        _response([_tool_use("write_file", {"path": "a.py", "content": "1"})], "tool_use"),
        _response([_text("stopped")], "end_turn"),
    ]

    async def fake_create(messages, tools=None):
        return scripted.pop(0)

    monkeypatch.setattr(agent, "_ollama_create", fake_create)

    async def boom(tool_input: dict) -> str:
        raise RuntimeError("disk full")

    result = await agent.run_tool_loop(
        user_message="build",
        tool_handlers={"write_file": boom},
        tools=[{"name": "write_file"}],
    )

    assert result["stop"] == "done"
    name, _input, res = result["results"][0]
    assert name == "write_file"
    assert "ERROR" in res and "disk full" in res
