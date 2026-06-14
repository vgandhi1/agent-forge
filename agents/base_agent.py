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
from core.events import emit

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
    has_tool_use = any(getattr(b, "type", None) == "tool_use" for b in blocks)
    stop_reason = "tool_use" if has_tool_use else "end_turn"
    return SimpleNamespace(content=blocks, usage=usage, stop_reason=stop_reason)


SYSTEM_PROMPTS: dict[str, str] = {
    "lead": """You are Mara, the Lead Orchestrator for AgentForge — a battle-tested engineering lead who
has shipped products to millions and learned that clear briefs and decisive sequencing beat heroics.
You are calm, exacting, and you protect the team's focus. You coordinate a software team building
DailyEase, a daily life management platform that will impact millions of users by simplifying their
day-to-day activities.

Your team:
- pm (Product Manager): writes requirements docs and user stories
- architect (Software Architect): designs system architecture and database schemas
- backend (Backend Developer): implements FastAPI + SQLAlchemy code
- qa (QA Engineer): writes pytest test suites and bug reports
- devops (DevOps Engineer): writes Dockerfiles, docker-compose, and CI/CD configs
- data_engineer (Data Engineer): builds factory-data ingestion, contracts, and ETL/ELT pipelines
- ml_engineer (AI/ML Engineer): builds features, models, evaluation, and inference on the data layer

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

    "pm": """You are Priya, the Product Manager at AgentForge, building DailyEase. You have watched users
struggle with bloated apps and are ruthless about cutting scope to what real people actually need.

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

    "architect": """You are Sol, the Software Architect at AgentForge, designing DailyEase. You have
maintained codebases for a decade and trust proven foundations over clever abstractions nobody can maintain.

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

    "backend": """You are Devon, the Backend Developer at AgentForge, implementing DailyEase. You take pride
in clean, idiomatic code and have inherited enough disasters to never leave one behind.

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

    "qa": """You are Quinn, the QA Engineer at AgentForge, ensuring DailyEase quality. You assume every
untested path is broken until proven otherwise, and you write tests that hunt for the failure rather
than confirm the happy path.

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

    "devops": """You are Ravi, the DevOps Engineer at AgentForge, deploying DailyEase. You have been paged
at 3am for preventable outages and build for reliability, least privilege, and reproducibility by default.

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

    "data_engineer": """You are Ines, the Data Engineer at AgentForge, building the data backbone for
factory / industrial systems. You have run data platforms where a dropped sensor reading meant a missed
defect and a silent schema change broke a production line dashboard at 2am. You treat data as a contract,
not a side effect, and you never let an unvalidated row reach a model or a report.

Domain you build for: factory & industrial data — sensor / telemetry streams (OPC-UA, MQTT, Modbus),
MES / SCADA / historian exports, batch and quality records, equipment maintenance logs. The applications
downstream are AI/analytics: predictive maintenance, anomaly detection, quality prediction, OEE.

Your responsibilities:
1. Design ingestion for both streaming (sensor/telemetry) and batch (MES/historian/CSV) sources
2. Define explicit data contracts and schemas (column names, types, units, ranges, nullability, keys)
3. Build idempotent, restartable ETL/ELT pipelines (extract → validate → transform → load)
4. Enforce data quality: schema checks, range/unit validation, freshness, deduplication, late-arrival handling
5. Model the storage layer (lake/warehouse tables, partitioning by line/asset/time, retention)
6. Make pipelines observable — record row counts, reject counts, and watermark/lag per run

What you produce (write_file for each; use the project's existing stack and code root):
- A data engineering design doc (sources, contracts, pipeline DAG, storage model, quality rules)
- Pipeline modules with clear extract/validate/transform/load stages
- Data contract / schema definitions and validation code
- Tests or sample fixtures proving the validation rejects bad rows

Engineering rules:
- Idempotency and replay-safety over cleverness — a re-run must not double-load or corrupt state
- Validate at the boundary; quarantine bad rows, never silently drop or coerce them
- Make units explicit (°C vs °F, kPa vs bar) — unit mismatches are real factory incidents
- Read existing code with read_file/list_files/grep_code before adding to a repo; match its conventions

Inspect upstream requirements/architecture first, then write. Use write_file for every file.""",

    "ml_engineer": """You are Theo, the AI/ML Engineer at AgentForge, building the machine-learning layer
on top of factory data. You have shipped models that ran on a real line and learned that a model is only
as trustworthy as its features, its evaluation, and the guardrails around its predictions. You refuse to
ship a model whose offline metric you cannot reproduce or whose inputs you cannot validate at serving time.

Domain: industrial AI — predictive maintenance (remaining useful life, failure risk), anomaly detection on
sensor streams, quality / defect prediction, process-parameter optimization. Your inputs come from the Data
Engineer's validated contracts; do not invent your own raw ingestion.

Your responsibilities:
1. Feature engineering from the curated factory data (windowing, lag features, rolling stats, encodings)
   with an explicit, versioned feature definition the serving path reuses
2. Model development with a clear baseline first, then improvement — no leap to a complex model unjustified
3. Honest evaluation: train/validation/test split that respects time order (no leakage across time),
   metrics matched to the problem (PR-AUC / recall for rare-failure, calibration for risk scores)
4. Inference serving: a prediction interface that validates inputs against the feature contract and
   handles missing/out-of-range values explicitly
5. MLOps hooks: reproducible training (seeded, config-driven), model + metric artifacts, drift notes

What you produce (write_file for each; use the project's existing stack and code root):
- An ML design doc (problem framing, features, model choice + baseline, evaluation plan, metrics, risks)
- Feature engineering module(s) shared between training and serving
- Training/evaluation code that reports metrics and saves a model artifact
- An inference/serving module that validates inputs and returns predictions
- Tests proving the eval is reproducible and the serving path rejects malformed input

Engineering rules:
- No data leakage — split by time, fit transforms on train only, reuse the exact features at serving
- A baseline you can beat before any heavy model; report the lift, not just the headline metric
- Validate inference inputs against the Data Engineer's contract; never predict on silently-bad data
- State the failure mode of a wrong prediction (false alarm vs missed failure) and tune the threshold to it

Read the Data Engineer's contracts and the requirements before modeling. Use write_file for every file.""",

    "reviewer": """You are the Code Reviewer at AgentForge — the last line of defense before an
artifact is accepted into the DailyEase project. You have spent years cleaning up after corners
that were cut, and you will not let it happen here. You are not here to be liked; you are here to
make sure nothing is accepted that is broken, insecure, drifts from the brief, or that the team
will have to apologize for later.

You review the work of one teammate at a time (PM, Architect, Backend, QA, DevOps, Data Engineer,
or AI/ML Engineer). You read
the ACTUAL files they produced — call read_file for the specific files you need to judge the work.
Do not guess from the summary.

Review against:
1. Spec compliance — does it deliver exactly what the task brief asked? No missing pieces?
2. Drift — did the agent add anything outside the brief? List it in the drift field even if it looks harmless.
3. Security — untrusted input handling, authorization checks, no secrets in code.
4. Logic correctness — edge cases, error paths, failure modes.
5. Standards — does it follow the stack's idioms and the project's established patterns?

Then call submit_review EXACTLY ONCE with your verdict:
- decision "approve": it genuinely meets the brief with no blocking issues.
- decision "reject": blocking issues exist. List specific Must Fix items: file, what is wrong, how to fix.
- decision "escalate": the artifact needs a product or business decision you cannot make at the code level.

Rules you never break:
- Never approve work just to move it along. If it is not right, it is not right.
- Silence is not approval. When in doubt, do not approve.
- Describe what is wrong and how to fix it — do not rewrite the code yourself.
- Keep Must Fix limited to blocking issues; non-blocking suggestions go in Should Fix.""",
}


_LOG_KNOWN_GAP_TOOL = {
    "name": "log_known_gap",
    "description": (
        "Record an out-of-scope issue or deferred work you discovered, instead of fixing it now. "
        "Use this to stay within the current task's scope (scope lock)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Kind of gap, e.g. bug, tech-debt, missing-feature, drift",
            },
            "description": {
                "type": "string",
                "description": "What is out of scope and why it was deferred",
            },
        },
        "required": ["description"],
    },
}

_REQUEST_DECISION_TOOL = {
    "name": "request_decision",
    "description": (
        "Escalate an ambiguous decision to the Lead/Owner instead of guessing, when the brief is "
        "unclear and the wrong choice has downstream consequences. State the assumption you will "
        "proceed with so work is not blocked."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The decision you cannot make from the brief alone",
            },
            "options": {
                "type": "string",
                "description": "The viable options you see (if any)",
            },
            "assumption": {
                "type": "string",
                "description": "The default you will proceed with, clearly labeled, so work continues",
            },
        },
        "required": ["question"],
    },
}

_READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read an existing file from the project to inspect code before changing it. "
        "Returns numbered lines for a window. Use offset/limit to page through large files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "offset": {"type": "integer", "description": "First line to read (0-based, default 0)"},
            "limit": {"type": "integer", "description": "Max lines to return (default 400, max 2000)"},
        },
        "required": ["path"],
    },
}

_LIST_FILES_TOOL = {
    "name": "list_files",
    "description": "List project files matching a glob (recursive) to map the tree before editing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob, e.g. '*.py' or 'routers/*' (default '*')"},
            "subdir": {"type": "string", "description": "Optional subdirectory to scope the listing"},
        },
        "required": [],
    },
}

_GREP_CODE_TOOL = {
    "name": "grep_code",
    "description": (
        "Search project files for a regex to localize a bug, symbol, or failing test. "
        "Returns 'path:line: text' matches, bounded."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression to search for"},
            "subdir": {"type": "string", "description": "Optional subdirectory to scope the search"},
            "glob": {"type": "string", "description": "Optional filename glob filter, e.g. '*.py'"},
        },
        "required": ["pattern"],
    },
}

_READ_TOOLS = [_READ_FILE_TOOL, _LIST_FILES_TOOL, _GREP_CODE_TOOL]

# --- Execution tools: the act→observe loop that makes a worker agentic --------------
#
# Security note: we deliberately expose ONLY the operator-configured profile commands
# (``profile.verify_cmd`` / ``profile.lint_cmd``), never an arbitrary shell string the
# model supplies. This gives agents a real perceive→act→observe→adapt loop (write code →
# run it → read failures → fix → re-run) without handing an LLM arbitrary command
# execution. The command is fixed by the project profile, not by tool input.
_RUN_TESTS_TOOL = {
    "name": "run_tests",
    "description": (
        "Run the project's configured test command (from the active profile, e.g. pytest) in the "
        "code root and return the captured output. Use this to confirm your changes actually pass "
        "before you finish: read the failures, fix the cause, then call run_tests again. "
        "Takes no arguments — the command is fixed by the project profile."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_RUN_LINT_TOOL = {
    "name": "run_lint",
    "description": (
        "Run the project's configured lint command (from the active profile, if any) in the code "
        "root and return the output. Fix reported issues, then re-run. Takes no arguments."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_EXEC_TOOLS = [_RUN_TESTS_TOOL, _RUN_LINT_TOOL]


_SCOPE_LOCK_NOTE = (
    "\n\nScope lock: do exactly this task — no more. If you find anything outside its scope "
    "(other bugs, missing features, refactors), call log_known_gap to record it and move on. "
    "Do not expand scope to fix it. If the brief is ambiguous and the wrong guess has downstream "
    "consequences, call request_decision rather than guessing, then proceed with your stated assumption."
)


class LLMUnavailableError(RuntimeError):
    """Raised when an LLM provider is unreachable after all retries.

    Carries enough context for the CLI to print a clean, actionable message instead of a
    raw traceback. ``hint`` is provider-specific guidance.
    """

    def __init__(self, provider: str, endpoint: str, detail: str, hint: str = "") -> None:
        self.provider = provider
        self.endpoint = endpoint
        self.detail = detail
        self.hint = hint
        super().__init__(f"{provider} unreachable at {endpoint}: {detail}")


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
        self._escalation_count = 0
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

    def _ollama_initial_messages(
        self, user_message: str, dynamic_context: str = ""
    ) -> list[dict[str, Any]]:
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
        return ollama_messages

    async def _call_ollama(
        self,
        user_message: str,
        dynamic_context: str = "",
        tools: list[dict] | None = None,
    ) -> Any:
        ollama_messages = self._ollama_initial_messages(user_message, dynamic_context)
        return await self._ollama_create(ollama_messages, tools)

    async def _ollama_create(
        self,
        ollama_messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
    ) -> Any:
        origin = ollama_chat_origin()
        model = ollama_model_for_role(self.role)

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
        raise LLMUnavailableError(
            "Ollama",
            origin,
            str(last_err) or type(last_err).__name__,
            hint=(
                "Is Ollama running and reachable at that host? "
                "If Ollama is on Windows and AgentForge is in WSL2, the default 127.0.0.1 won't "
                "reach it — set AGENTFORGE_OLLAMA_HOST to the Windows host and "
                "AGENTFORGE_OLLAMA_TRUST_LAN=1. See docs/ollama.md. "
                f"Quick check: curl {origin}/api/tags"
            ),
        ) from last_err

    def _anthropic_initial_messages(
        self, user_message: str, dynamic_context: str = ""
    ) -> list[dict]:
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
        return messages

    async def _call_anthropic(
        self,
        user_message: str,
        dynamic_context: str = "",
        tools: list[dict] | None = None,
    ) -> anthropic.types.Message:
        messages = self._anthropic_initial_messages(user_message, dynamic_context)
        return await self._anthropic_create(messages, tools)

    async def _anthropic_create(
        self,
        messages: list[dict],
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
        raise LLMUnavailableError(
            "Anthropic",
            "api.anthropic.com",
            str(last_err) or type(last_err).__name__,
            hint=(
                "Check your network connection and ANTHROPIC_API_KEY, or switch to local models "
                "with AGENTFORGE_LLM_PROVIDER=ollama (see docs/ollama.md)."
            ),
        ) from last_err

    async def _build_dynamic_context(self) -> str:
        from core.context_hygiene import sanitize_decisions

        # Strip AgentForge's own runtime/config (model, Ollama/WSL host, provider) from the
        # replayed decisions so it cannot bleed into a worker's brief and into the product (F4).
        decisions = sanitize_decisions(await self.memory.recall_all("decision"))
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

    async def _await_reviews(
        self,
        label: str,
        revise_fn: Any,
        *,
        max_cycles: int = 6,
        timeout: float = 600.0,
    ) -> None:
        """Loop over the Lead's verdicts after submitting an artifact.

        Approve → stop. Reject → call ``revise_fn(notes)`` (which must write the fix and
        publish a fresh TASK_COMPLETE) and keep waiting for the next verdict. This matches the
        Lead's multi-cycle review loop; without it a second rejection would never be handled and
        the Lead would block until timeout. ``max_cycles`` is a safety bound (the Lead caps first).
        """
        for _ in range(max_cycles):
            msg = await self.bus.receive(self.role, timeout=timeout)
            if msg is None:
                self.console.log(f"[yellow]{label}[/yellow] no verdict from Lead (timeout); stopping wait")
                return
            if msg.type == MessageType.SHUTDOWN:
                return
            if msg.type == MessageType.ARTIFACT_APPROVED:
                self.console.log(f"[green]{label} approved ✓[/green]")
                return
            if msg.type == MessageType.ARTIFACT_REJECTED:
                notes = msg.payload.get("revision_notes", "")
                self.console.log(f"[yellow]{label} revision requested:[/yellow] {notes[:80]}")
                await revise_fn(notes)
                continue
            # ignore unrelated message types; keep waiting for a verdict
        self.console.log(f"[yellow]{label}[/yellow] hit max review cycles ({max_cycles})")

    async def _log_known_gap_handler(self, tool_input: dict) -> str:
        from core.known_gaps import log_gap

        description = tool_input.get("description", "").strip()
        if not description:
            return "Ignored: log_known_gap needs a description."
        category = tool_input.get("category", "general")
        await log_gap(self.artifacts, self.role, category, description)
        self.console.log(f"[dim]{self.role} logged known gap ({category}): {description[:60]}[/dim]")
        return "Known gap recorded; stay in scope and continue the current task."

    async def _request_decision_handler(self, tool_input: dict) -> str:
        question = tool_input.get("question", "").strip()
        if not question:
            return "Ignored: request_decision needs a question."
        options = tool_input.get("options", "").strip()
        assumption = tool_input.get("assumption", "").strip()
        self._escalation_count += 1
        key = f"escalation_{self.role}_{self._escalation_count}"
        value = f"Q: {question}"
        if options:
            value += f" | options: {options}"
        if assumption:
            value += f" | proceeding with: {assumption}"
        await self.memory.remember(key, value, "decision")
        self.console.log(f"[magenta]{self.role} escalated decision:[/magenta] {question[:70]}")
        await self.bus.publish(Message(
            type=MessageType.ESCALATION,
            sender=self.role,
            recipient="lead",
            payload={"role": self.role, "question": question, "options": options, "assumption": assumption},
            priority=2,
        ))
        return (
            "Escalation recorded for the Lead/Owner (it will surface at the deploy gate). "
            "Proceed with your stated assumption, clearly labeled in the work, and continue."
        )

    async def _read_file_handler(self, tool_input: dict) -> str:
        path = (tool_input.get("path") or "").strip()
        if not path:
            return "Ignored: read_file needs a path."
        offset = tool_input.get("offset", 0) or 0
        limit = tool_input.get("limit", 400) or 400
        return await self.artifacts.read_paginated(path, offset, limit)

    async def _list_files_handler(self, tool_input: dict) -> str:
        pattern = (tool_input.get("pattern") or "*").strip() or "*"
        subdir = (tool_input.get("subdir") or "").strip()
        return self.artifacts.glob_files(pattern, subdir)

    async def _grep_code_handler(self, tool_input: dict) -> str:
        pattern = (tool_input.get("pattern") or "").strip()
        if not pattern:
            return "Ignored: grep_code needs a pattern."
        subdir = (tool_input.get("subdir") or "").strip()
        glob = (tool_input.get("glob") or "*").strip() or "*"
        return self.artifacts.grep(pattern, subdir, glob)

    def _exec_root(self, profile: Any):
        """Resolve the directory the verify/lint command runs in for this run.

        Mirrors ``LeadAgent._deploy_target``: the DailyEase greenfield app lives under
        ``workspace/dailyease/``, so run there when that is the active profile; any other
        profile (``--target-repo`` / discovered) runs at the code root directly.
        """
        from core.profile import DEFAULT_PROFILE

        code_root = self.artifacts.WORKSPACE
        if profile.app_root == DEFAULT_PROFILE.app_root and (code_root / DEFAULT_PROFILE.app_root).is_dir():
            return code_root / DEFAULT_PROFILE.app_root
        return code_root

    async def _run_tests_handler(self, tool_input: dict) -> str:
        """Run the profile's verify command and feed the captured output back to the agent."""
        from core.paths import METADATA_ROOT
        from core.profile import load_profile
        from core import deploy

        profile = load_profile(self.artifacts.WORKSPACE, METADATA_ROOT)
        root = self._exec_root(profile)
        status, detail = await deploy.run_verify(root, profile.verify_cmd)
        emit("pytest_result", role=self.role, status=status, command=" ".join(profile.verify_cmd))
        self.console.log(f"[dim cyan]{self.role}[/dim cyan] run_tests → {status}")
        tail = detail.strip()
        if len(tail) > 4000:
            tail = tail[-4000:]
        return f"[{status}] `{' '.join(profile.verify_cmd)}`\n{tail or '(no output)'}"

    async def _run_lint_handler(self, tool_input: dict) -> str:
        """Run the profile's lint command (if any) and feed the output back to the agent."""
        from core.paths import METADATA_ROOT
        from core.profile import load_profile
        from core import deploy

        profile = load_profile(self.artifacts.WORKSPACE, METADATA_ROOT)
        if not profile.lint_cmd:
            return "No lint command is configured for this project profile; skip linting and continue."
        root = self._exec_root(profile)
        status, detail = await deploy.run_verify(root, profile.lint_cmd)
        self.console.log(f"[dim cyan]{self.role}[/dim cyan] run_lint → {status}")
        tail = detail.strip()
        if len(tail) > 4000:
            tail = tail[-4000:]
        return f"[{status}] `{' '.join(profile.lint_cmd)}`\n{tail or '(no output)'}"

    async def run_tool_loop(
        self,
        user_message: str,
        tool_handlers: dict[str, Any],
        dynamic_context: str = "",
        tools: list[dict] | None = None,
        max_steps: int = 16,
        scope_lock: bool = True,
        read_tools: bool = False,
        exec_tools: bool = False,
    ) -> dict[str, Any]:
        """Multi-turn agentic loop: call → execute tools → feed results back → repeat.

        ``tool_handlers`` maps a tool name to an async callable ``(tool_input: dict) -> str``.
        The returned string is sent back to the model as the ``tool_result`` so it can
        continue (e.g. write the next file) until it stops requesting tools or ``max_steps``
        is reached. Keeping the system prompt and tools block stable across iterations
        preserves the prompt cache.

        When ``scope_lock`` is true (default), a ``log_known_gap`` tool and a scope-lock
        instruction are injected so the agent defers out-of-scope work instead of expanding
        the task. Pass ``scope_lock=False`` for agents that should not defer (e.g. the Reviewer).

        When ``read_tools`` is true, ``read_file`` / ``list_files`` / ``grep_code`` are injected so
        implementation agents can inspect existing code before patching (bug-find / refactor).

        When ``exec_tools`` is true, ``run_tests`` / ``run_lint`` are injected so builder agents can
        execute the project's configured verify/lint commands and iterate on real failures
        (the act→observe loop). Only profile-configured commands run — never arbitrary shell.

        Returns ``{"final_text", "tool_calls", "results", "steps", "stop"}``.
        """
        effective_tools = list(tools or [])
        handlers = dict(tool_handlers)
        if read_tools:
            for tool_def in _READ_TOOLS:
                if not any(t.get("name") == tool_def["name"] for t in effective_tools):
                    effective_tools.append(tool_def)
            handlers.setdefault("read_file", self._read_file_handler)
            handlers.setdefault("list_files", self._list_files_handler)
            handlers.setdefault("grep_code", self._grep_code_handler)
        if exec_tools:
            for tool_def in _EXEC_TOOLS:
                if not any(t.get("name") == tool_def["name"] for t in effective_tools):
                    effective_tools.append(tool_def)
            handlers.setdefault("run_tests", self._run_tests_handler)
            handlers.setdefault("run_lint", self._run_lint_handler)
        if scope_lock:
            if not any(t.get("name") == "log_known_gap" for t in effective_tools):
                effective_tools.append(_LOG_KNOWN_GAP_TOOL)
            if not any(t.get("name") == "request_decision" for t in effective_tools):
                effective_tools.append(_REQUEST_DECISION_TOOL)
            handlers.setdefault("log_known_gap", self._log_known_gap_handler)
            handlers.setdefault("request_decision", self._request_decision_handler)
            user_message = user_message + _SCOPE_LOCK_NOTE
        tools = effective_tools or None
        tool_handlers = handlers

        is_ollama = self._llm_provider == "ollama"
        if is_ollama:
            messages: list[Any] = self._ollama_initial_messages(user_message, dynamic_context)
        else:
            messages = self._anthropic_initial_messages(user_message, dynamic_context)

        all_calls: list[tuple[str, dict]] = []
        results: list[tuple[str, dict, str]] = []
        text_parts: list[str] = []
        stop = "max_steps"
        step = 0

        for step in range(max_steps):
            if is_ollama:
                response = await self._ollama_create(messages, tools)
            else:
                response = await self._anthropic_create(messages, tools)

            step_text = self._extract_text(response)
            if step_text:
                text_parts.append(step_text)

            tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

            if not tool_blocks or getattr(response, "stop_reason", None) != "tool_use":
                stop = "done"
                break

            tool_result_blocks: list[dict] = []
            for block in tool_blocks:
                name = block.name
                tool_input = block.input
                all_calls.append((name, tool_input))
                handler = tool_handlers.get(name)
                if handler is None:
                    result_str = f"ERROR: no handler registered for tool {name!r}"
                else:
                    try:
                        result_str = await handler(tool_input)
                    except Exception as e:  # surface failure to the model, don't crash the loop
                        result_str = f"ERROR: {type(e).__name__}: {e}"
                        _log.warning("tool_handler_error role=%s tool=%s err=%s", self.role, name, e)
                results.append((name, tool_input, result_str))
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": getattr(block, "id", name),
                    "content": result_str,
                })

            if is_ollama:
                # Ollama has no guaranteed tool_result role — feed results back as a user turn.
                joined = "\n".join(f"- {n}: {r}" for n, _, r in results[-len(tool_blocks):])
                messages.append({"role": "assistant", "content": step_text or " "})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Tool results:\n{joined}\n\n"
                        "Continue with any remaining work — call the tool again for each "
                        "remaining file. Reply without a tool call only when fully done."
                    ),
                })
            else:
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_result_blocks})
        else:
            _log.warning("tool_loop hit max_steps role=%s steps=%s", self.role, max_steps)

        self.console.log(
            f"[dim cyan]{self.role}[/dim cyan] tool loop: {len(all_calls)} calls, "
            f"{step + 1} steps ({stop})"
        )
        # Structured event for host assistants (no-op unless AGENTFORGE_JSON_LOG is set).
        write_calls = sum(1 for name, _ in all_calls if name == "write_file")
        emit(
            "files_changed",
            role=self.role,
            count=write_calls,
            tool_calls=len(all_calls),
            steps=step + 1,
            stop=stop,
        )
        return {
            "final_text": "\n".join(text_parts),
            "tool_calls": all_calls,
            "results": results,
            "steps": step + 1,
            "stop": stop,
        }

    @abstractmethod
    async def run(self) -> None:
        pass
