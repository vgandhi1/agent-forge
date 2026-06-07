import httpx
import pytest
from rich.console import Console

import agents.base_agent as base_agent
from agents.base_agent import BaseAgent, LLMUnavailableError
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


class _Agent(BaseAgent):
    async def run(self) -> None:
        pass


@pytest.mark.asyncio
async def test_ollama_unreachable_raises_clean_error(monkeypatch) -> None:
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(base_agent, "MAX_API_RETRIES", 1)

    async def no_sleep(*a, **k):
        return None

    monkeypatch.setattr(base_agent.asyncio, "sleep", no_sleep)

    async def boom(self, *a, **k):
        raise httpx.ConnectError("all connection attempts failed")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)

    agent = _Agent("backend", MessageBus(), ArtifactStore(), Console())

    with pytest.raises(LLMUnavailableError) as ei:
        await agent._call_ollama("hi")

    err = ei.value
    assert err.provider == "Ollama"
    assert "11434" in err.endpoint
    assert "docs/ollama.md" in err.hint
    # Original cause preserved for debugging.
    assert isinstance(err.__cause__, httpx.ConnectError)
