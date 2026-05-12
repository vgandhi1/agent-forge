import asyncio
import json
import logging
import os
import random
from abc import ABC, abstractmethod
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
from anthropic import APIConnectionError, APIStatusError, APITimeoutError, AsyncAnthropic, RateLimitError
from rich.console import Console

from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.memory import AgentMemory
from core.artifact_store import ArtifactStore
from core.ollama_url import validate_ollama_base_url

USE_THINKING = os.getenv("AGENTFORGE_THINKING", "false").lower() == "true"
THINKING_BUDGET = int(os.getenv("AGENTFORGE_THINKING_BUDGET", "8000"))
MAX_API_RETRIES = max(1, int(os.getenv("AGENTFORGE_API_RETRIES", "4")))
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OLLAMA_MODEL = "llama3.2"

_log = logging.getLogger("agentforge.agent")


def llm_provider() -> str:
    return os.getenv("AGENTFORGE_LLM_PROVIDER", "anthropic").strip().lower()


def anthropic_model_for_role(role: str) -> str:
    suffix = role.upper()
    return (
        os.getenv(f"AGENTFORGE_MODEL_{suffix}")
        or os.getenv("AGENTFORGE_MODEL")
        or DEFAULT_ANTHROPIC_MODEL
    )


def ollama_model_for_role(role: str) -> str:
    suffix = role.upper()
    return (
        os.getenv(f"AGENTFORGE_OLLAMA_MODEL_{suffix}")
        or os.getenv("AGENTFORGE_OLLAMA_MODEL")
        or DEFAULT_OLLAMA_MODEL
    )


def ollama_chat_origin() -> str:
    raw = os.getenv("AGENTFORGE_OLLAMA_HOST", "http://127.0.0.1:11434").strip()
    return validate_ollama_base_url(raw)


def anthropic_tools_to_ollama(tools: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return out


def _ollama_message_to_fake_anthropic_message(
    data: dict,
) -> SimpleNamespace:
    """Build a minimal object compatible with _extract_tool_calls / _extract_text."""
    msg = data.get("message") or {}
    blocks: list[Any] = []
    content = msg.get("content") or ""
    if isinstance(content, str) and content.strip():
        b = SimpleNamespace()
        b.type = "text"
        b.text = content
        blocks.append(b)
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        raw_args = fn.get("arguments", "{}")
        if isinstance(raw_args, str):
            try:
                parsed: dict[str, Any] = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                parsed = {}
        elif isinstance(raw_args, dict):
            parsed = raw_args
        else:
            parsed = {}
        b = SimpleNamespace()
        b.type = "tool_use"
        b.name = name
        b.input = parsed
        blocks.append(b)
    usage = SimpleNamespace(
        input_tokens=int((data.get("prompt_eval_count") or 0)),
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(content=blocks, usage=usage)


SYSTEM_PROMPTS: dict[str, str] = {
    "lead": """You are the Lead Orchestrator for AgentForge — the principal technical lead coordinating
a software team building DailyEase, a daily life management platform that will impact millions of users
by simplifying their day-to-day activities.

Your team:
- pm (Product Manager): writes requirements docs and user stories
- architect (Software Architect): designs system architecture and database schemas
- backend (Backend Developer): implements FastAPI + SQLAlchemy code
- qa (QA Engineer): writes pytest test suites and bug reports
- devops (DevOps Engineer): writes Dockerfiles, docker-compose, and CI/CD configs

Your responsibilities:
1. Translate the sprint goal into specific, actionable tasks for each agent
2. Enforce the phase gate: requirements → architecture → backend → QA → devops
3. Review every artifact submitted by an agent and approve or request revisions
4. Track sprint progress; remember decisions and blockers in your memory
5. Resolve blockers via consultation if needed
6. Ensure quality: no code shipped without passing QA, no deployment without QA approval

When assigning tasks, be explicit about:
- What the deliverable looks like (file name, format, sections required)
- Dependencies on prior artifacts (reference approved artifact paths)
- Acceptance criteria you will use to approve/reject

Always use the provided tools to take action. Think step by step before each decision.
Your decisions shape what DailyEase becomes — be thoughtful and decisive.""",

    "pm": """You are the Product Manager at AgentForge, building DailyEase.

DailyEase mission: Help millions of people simplify their daily lives by intelligently
managing tasks, building healthy habits, tracking finances, and promoting wellness.

Your responsibilities:
1. Write clear, structured requirements documents in Markdown
2. Define user personas, problem statements, and feature specifications
3. Write user stories in "As a [user], I want [goal] so that [benefit]" format
4. Define acceptance criteria for each feature
5. Prioritize features using MoSCoW (Must/Should/Could/Won't)
6. Write API endpoint specifications that the architect will use

Sections your requirements doc MUST include:
- Executive Summary
- Target Users & Personas
- Problem Statement
- Feature Specifications (Tasks, Habits, Finance, Wellness)
- User Stories (at least 3 per module)
- API Contract Overview (endpoint list, not full spec)
- Non-Functional Requirements (performance, security, scalability)
- Out of Scope (MVP boundaries)

Write professionally. Think from the user's perspective. Use the write_file tool to save your document.""",

    "architect": """You are the Software Architect at AgentForge, designing DailyEase.

Your responsibilities:
1. Design the complete system architecture based on the PM's requirements
2. Define the database schema (tables, columns, relationships, indexes)
3. Design the FastAPI application structure (modules, routers, services, models)
4. Define API contracts (endpoints, request/response schemas, HTTP status codes)
5. Identify cross-cutting concerns (auth, validation, error handling, logging)
6. Make and document technology choices with rationale

Architecture document MUST include:
- System Overview Diagram (ASCII art)
- Technology Stack (with versions and rationale)
- Database Schema (table definitions with types and constraints)
- Application Structure (directory tree with purpose of each module)
- API Design (all endpoints with method, path, request/response schemas)
- Data Flow (how a request flows from API → service → database → response)
- Security Design (auth strategy, input validation approach)
- Scalability Considerations

Write detailed, unambiguous specs that a developer can implement directly.
Use the write_file tool to save your document.""",

    "backend": """You are the Backend Developer at AgentForge, implementing DailyEase.

Tech stack you MUST use:
- FastAPI (latest) for the web framework
- SQLAlchemy 2.x with async support for ORM
- aiosqlite as the SQLite async driver
- Pydantic v2 for request/response validation
- Python 3.11+ features (type hints, match statements where appropriate)

Your responsibilities:
1. Implement the full FastAPI application per the approved architecture document
2. Write clean, idiomatic Python — no unnecessary abstractions
3. Implement all four modules: tasks, habits, finance, wellness
4. Write a working database initialization module
5. Include proper error handling (HTTPException with meaningful messages)
6. Write a main.py that registers all routers and starts the app

Files you MUST write (use write_file for each):
- dailyease/main.py
- dailyease/database.py
- dailyease/models/task.py, habit.py, finance.py, wellness.py
- dailyease/schemas/task.py, habit.py, finance.py, wellness.py
- dailyease/routers/tasks.py, habits.py, finance.py, wellness.py
- dailyease/services/task_service.py, habit_service.py, finance_service.py, wellness_service.py
- dailyease/requirements.txt (fastapi, sqlalchemy, aiosqlite, uvicorn, pydantic)

Write production-quality code. Every function must have a clear purpose.
Use the write_file tool for every file.""",

    "qa": """You are the QA Engineer at AgentForge, ensuring DailyEase quality.

Your responsibilities:
1. Review the backend implementation for bugs, missing validations, and edge cases
2. Write a comprehensive pytest test suite for all endpoints
3. Write tests for: CRUD operations, validation errors, edge cases, business logic
4. Document any bugs found with severity, steps to reproduce, and expected vs actual
5. Write a QA report summarizing test coverage and findings

Files you MUST write (use write_file for each):
- dailyease/tests/__init__.py
- dailyease/tests/conftest.py (pytest fixtures, test database setup)
- dailyease/tests/test_tasks.py
- dailyease/tests/test_habits.py
- dailyease/tests/test_finance.py
- dailyease/tests/test_wellness.py
- reports/qa_report.md

Test every router's endpoints: create, read, update, delete, list, and error cases.
Use httpx.AsyncClient for async test patterns.
Write the QA report with: executive summary, test coverage matrix, bugs found, recommendations.""",

    "devops": """You are the DevOps Engineer at AgentForge, deploying DailyEase.

Your responsibilities:
1. Write a production-ready Dockerfile for DailyEase
2. Write a docker-compose.yml for local development
3. Write a GitHub Actions CI/CD pipeline
4. Write a health check endpoint addition
5. Write deployment documentation

Files you MUST write (use write_file for each):
- dailyease/Dockerfile
- dailyease/docker-compose.yml
- dailyease/.github/workflows/ci.yml
- dailyease/.dockerignore
- docs/deployment.md

Dockerfile requirements:
- Multi-stage build (builder + runtime)
- Non-root user
- Health check instruction
- Optimized layer caching

CI/CD requirements:
- Lint (ruff or flake8)
- Type check (mypy)
- Run pytest
- Build Docker image
- Push to ghcr.io on main branch merge

Write production-grade configs. Security and reliability matter.""",
}


class BaseAgent(ABC):
    def __init__(
        self,
        role: str,
        bus: MessageBus,
        artifact_store: ArtifactStore,
        console: Console,
    ) -> None:
        self.role = role
        self.bus = bus
        self.artifacts = artifact_store
        self.memory = AgentMemory(role)
        self._llm_provider = llm_provider()
        self.client: AsyncAnthropic | None
        if self._llm_provider == "ollama":
            self.client = None
        else:
            self.client = AsyncAnthropic()
        self.console = console
        self._system_prompt = SYSTEM_PROMPTS[role]
        bus.register(role)

    async def _call_llm(
        self,
        user_message: str,
        dynamic_context: str = "",
        tools: list[dict] | None = None,
    ) -> Any:
        if self._llm_provider == "ollama":
            return await self._call_ollama(user_message, dynamic_context, tools)
        return await self._call_anthropic(user_message, dynamic_context, tools)

    async def _call_ollama(
        self,
        user_message: str,
        dynamic_context: str = "",
        tools: list[dict] | None = None,
    ) -> Any:
        origin = ollama_chat_origin()
        model = ollama_model_for_role(self.role)
        ollama_messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
        ]
        if dynamic_context.strip():
            ollama_messages.append({
                "role": "user",
                "content": f"<sprint_context>\n{dynamic_context}\n</sprint_context>",
            })
            ollama_messages.append({
                "role": "assistant",
                "content": "Sprint context acknowledged. Ready for my task.",
            })
        ollama_messages.append({"role": "user", "content": user_message})

        body: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
        }
        if tools:
            body["tools"] = anthropic_tools_to_ollama(tools)

        url = f"{origin}/api/chat"
        timeout = httpx.Timeout(600.0, connect=30.0)
        last_err: BaseException | None = None
        for attempt in range(MAX_API_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=timeout) as http_client:
                    r = await http_client.post(url, json=body)
                    r.raise_for_status()
                    data = r.json()
                fake = _ollama_message_to_fake_anthropic_message(data)
                if attempt > 0:
                    _log.info("ollama call succeeded after retry role=%s attempt=%s", self.role, attempt)
                self.console.log(f"[dim cyan]{self.role}[/dim cyan] ollama model={model!r} ok")
                return fake
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
                last_err = e
                _log.warning("ollama_network_error role=%s attempt=%s", self.role, attempt + 1)
                await asyncio.sleep(min(30.0, (2**attempt) + random.uniform(0, 0.5)))
            except httpx.HTTPStatusError as e:
                last_err = e
                code = e.response.status_code
                if code >= 500:
                    _log.warning("ollama_http_5xx status=%s role=%s attempt=%s", code, self.role, attempt + 1)
                    await asyncio.sleep(min(30.0, (2**attempt) + random.uniform(0, 0.5)))
                    continue
                raise

        assert last_err is not None
        raise last_err

    async def _call_anthropic(
        self,
        user_message: str,
        dynamic_context: str = "",
        tools: list[dict] | None = None,
    ) -> anthropic.types.Message:
        if self.client is None:
            raise RuntimeError("Anthropic client not initialized")
        model = anthropic_model_for_role(self.role)
        system_blocks: list[dict] = [
            {
                "type": "text",
                "text": self._system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        messages: list[dict] = []
        if dynamic_context.strip():
            messages.append({
                "role": "user",
                "content": f"<sprint_context>\n{dynamic_context}\n</sprint_context>",
            })
            messages.append({
                "role": "assistant",
                "content": "Sprint context acknowledged. Ready for my task.",
            })

        messages.append({"role": "user", "content": user_message})

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 16000,
            "system": system_blocks,
            "messages": messages,
        }

        if tools:
            sorted_tools = sorted(tools, key=lambda t: t["name"])
            sorted_tools[-1] = {
                **sorted_tools[-1],
                "cache_control": {"type": "ephemeral"},
            }
            kwargs["tools"] = sorted_tools

        if USE_THINKING:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": THINKING_BUDGET}

        last_err: BaseException | None = None
        for attempt in range(MAX_API_RETRIES):
            try:
                response = await self.client.messages.create(**kwargs)
                usage = response.usage
                cache_info = ""
                if hasattr(usage, "cache_read_input_tokens"):
                    cache_info = (
                        f" [cache_read={usage.cache_read_input_tokens} "
                        f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0)} "
                        f"live={usage.input_tokens}]"
                    )
                if attempt > 0:
                    _log.info("anthropic call succeeded after retry role=%s attempt=%s", self.role, attempt)
                self.console.log(f"[dim cyan]{self.role}[/dim cyan] completed call{cache_info}")
                return response
            except RateLimitError as e:
                last_err = e
                _log.warning("rate_limit role=%s attempt=%s/%s", self.role, attempt + 1, MAX_API_RETRIES)
                await asyncio.sleep(min(90.0, (2**attempt) + random.uniform(0, 0.5)))
            except APIConnectionError as e:
                last_err = e
                _log.warning("connection_error role=%s attempt=%s", self.role, attempt + 1)
                await asyncio.sleep(min(30.0, (2**attempt) + random.uniform(0, 0.5)))
            except APITimeoutError as e:
                last_err = e
                _log.warning("timeout role=%s attempt=%s", self.role, attempt + 1)
                await asyncio.sleep(min(30.0, (2**attempt) + random.uniform(0, 0.5)))
            except APIStatusError as e:
                last_err = e
                code = getattr(e, "status_code", None)
                if code is not None and code >= 500:
                    _log.warning("server_error status=%s role=%s attempt=%s", code, self.role, attempt + 1)
                    await asyncio.sleep(min(30.0, (2**attempt) + random.uniform(0, 0.5)))
                    continue
                raise

        assert last_err is not None
        raise last_err

    async def _build_dynamic_context(self) -> str:
        decisions = await self.memory.recall_all("decision")
        artifacts = await self.memory.recall_all("artifact_ref")
        parts: list[str] = []
        if decisions:
            parts.append(
                "## Sprint Decisions\n"
                + "\n".join(f"- {k}: {v}" for k, v in decisions.items())
            )
        if artifacts:
            parts.append(
                "## Approved Artifacts\n"
                + "\n".join(f"- {k}: {v}" for k, v in artifacts.items())
            )
        return "\n\n".join(parts)

    def _extract_tool_calls(self, response: Any) -> list[tuple[str, dict]]:
        """Return list of (tool_name, tool_input) pairs from response content."""
        calls = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                calls.append((block.name, block.input))
        return calls

    def _extract_text(self, response: Any) -> str:
        parts = []
        for block in response.content:
            if getattr(block, "type", None) == "text" and hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)

    @abstractmethod
    async def run(self) -> None:
        pass
