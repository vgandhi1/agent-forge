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


def ollama_options() -> dict[str, Any]:
    """Per-request Ollama ``options`` assembled from env.

    ``AGENTFORGE_OLLAMA_NUM_GPU`` — number of layers to offload to GPU. Set to ``0`` to force
    CPU inference, the reliable escape hatch when the GPU's ROCm/CUDA libraries are broken for the
    card's arch (e.g. AMD gfx1103 missing ``rocblas`` TensileLibrary → HTTP 500 on /api/chat).
    """
    opts: dict[str, Any] = {}
    num_gpu = os.getenv("AGENTFORGE_OLLAMA_NUM_GPU", "").strip()
    if num_gpu:
        try:
            opts["num_gpu"] = int(num_gpu)
        except ValueError:
            pass
    return opts


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

# --- Data mocking: generate standardized dummy datasets for local pipeline/model testing --------
#
# Data/ML engineers need fixtures to exercise pipelines and feature/serving code without production
# data. This tool turns a simple column schema into a deterministic dataset file (seeded), written
# through the sandboxed artifact store. It is for TEST fixtures only — not for fabricating data that
# would be delivered as real.
_GENERATE_MOCK_DATA_TOOL = {
    "name": "generate_mock_data",
    "description": (
        "Generate a STANDARDIZED synthetic dataset file to test pipelines or models locally "
        "without production data. Provide 'columns' (each {name, type}) where type is one of "
        "int, float, bool, timestamp, category, id, string — with optional min/max (numeric), "
        "values (category list), precision (float), unit. Also give 'rows' and an optional 'seed' "
        "(data is deterministic per seed). Writes a csv/json/jsonl fixture into the project. Use "
        "this only for test fixtures, never to fabricate data delivered as real."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the code root for the fixture file"},
            "format": {"type": "string", "enum": ["csv", "json", "jsonl"], "description": "Output format (default csv)"},
            "rows": {"type": "integer", "description": "Number of rows (default 20; capped at 1000)"},
            "seed": {"type": "integer", "description": "Seed for deterministic output (default 0)"},
            "columns": {
                "type": "array",
                "description": "Column schema; each item {name, type, [min,max,values,precision,unit]}",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                        "values": {"type": "array", "items": {"type": "string"}},
                        "precision": {"type": "integer"},
                        "unit": {"type": "string"},
                    },
                    "required": ["name", "type"],
                },
            },
        },
        "required": ["path", "columns"],
    },
}

# --- Patch-based edit: surgical, anchored search/replace instead of full-file rewrite -------
#
# On a real --target-repo, rewriting a whole file with write_file is brittle (risks clobbering
# unrelated code) and token-heavy. edit_file replaces an exact, unique snippet so agents make
# minimal, reviewable changes. Path validation and the code-root sandbox are reused from the
# artifact store (the write goes through ArtifactStore.write), so this cannot escape the root.
_EDIT_FILE_TOOL = {
    "name": "edit_file",
    "description": (
        "Make a SURGICAL edit to an EXISTING file by replacing an exact snippet — prefer this over "
        "write_file for changes to files that already exist (it is safer and far cheaper than a full "
        "rewrite). Provide old_string: an exact snippet currently in the file, with enough "
        "surrounding context that it appears EXACTLY ONCE; and new_string: the replacement (use an "
        "empty string to delete the snippet). Fails if old_string is missing or not unique, unless "
        "replace_all is true. Read the file first (read_file) and copy the snippet verbatim, "
        "including indentation. To create a brand-new file, use write_file instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the code root of the file to edit"},
            "old_string": {
                "type": "string",
                "description": "Exact text to replace, copied verbatim incl. whitespace; must be unique unless replace_all",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text (empty string deletes the matched snippet)",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace every occurrence instead of requiring a unique match (default false)",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
}

# A file at/under this many lines is small enough that, when an anchored edit can't be located,
# rewriting it wholesale with write_file is the cheaper recovery than re-anchoring.
_EDIT_SMALL_FILE_LINES = 150


def _whitespace_tolerant_replace(content: str, old: str, new: str) -> tuple[str, str | None]:
    """Whitespace-tolerant, line-aligned fallback for ``edit_file`` when the exact anchor misses.

    LLMs frequently reproduce a snippet with the right *content* but slightly wrong leading
    indentation or trailing whitespace, so the exact substring match fails even though the target
    is unambiguous. This retries by comparing whole lines via their ``strip()``-ed form and, on a
    single contiguous match, splices ``new`` in at that span.

    Returns ``(status, new_content)`` where ``status`` is ``"ok"`` (with new content),
    ``"ambiguous"`` (matches more than one span — caller must disambiguate), or ``"none"``
    (no line-aligned match; caller falls through to the not-found path). Deliberately line-aligned
    so it can only recover from whitespace drift, never match unrelated mid-line text.
    """
    old_lines = old.splitlines()
    norm_old = [ln.strip() for ln in old_lines]
    # An all-blank or empty anchor would match anywhere; refuse to guess.
    if not norm_old or not any(norm_old):
        return ("none", None)

    content_lines = content.splitlines(keepends=True)
    n = len(norm_old)
    matches = [
        i
        for i in range(0, len(content_lines) - n + 1)
        if [w.strip() for w in content_lines[i:i + n]] == norm_old
    ]
    if not matches:
        return ("none", None)
    if len(matches) > 1:
        return ("ambiguous", None)

    i = matches[0]
    matched_block = "".join(content_lines[i:i + n])
    replacement = new
    # Keep line boundaries intact: if the matched span ended in a newline but the replacement
    # doesn't, re-add it so we don't fuse the following line onto the edit.
    if matched_block.endswith("\n") and not replacement.endswith("\n"):
        replacement += "\n"
    new_content = "".join(content_lines[:i]) + replacement + "".join(content_lines[i + n:])
    return ("ok", new_content)


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
        # Full paths edited via the edit_file tool during the most recent edit-enabled tool loop.
        # Reset at the start of each run_tool_loop(edit_tools=True); builders merge it into the
        # set of changed files they report to the Lead.
        self._edited_files: list[str] = []
        # Context-decay guards (overridable in tests):
        #  - _decisions_budget_chars bounds the replayed decisions log in _build_dynamic_context.
        #  - _context_char_budget is the circuit breaker for a single tool loop's running messages;
        #    when exceeded we drop the oldest complete tool exchanges (sliding window) BEFORE the
        #    next LLM call rather than letting the call fail on a blown context window.
        self._decisions_budget_chars = int(os.getenv("AGENTFORGE_DECISIONS_BUDGET_CHARS", "4000"))
        self._context_char_budget = int(os.getenv("AGENTFORGE_CONTEXT_CHAR_BUDGET", "120000"))
        bus.register(role)

    @staticmethod
    def _messages_size(messages: list[Any]) -> int:
        """Rough character size of a running message list (content may be str or block objects)."""
        return sum(len(str(m.get("content", ""))) for m in messages)

    def _compact_messages(
        self, messages: list[Any], initial_len: int
    ) -> tuple[list[Any], int]:
        """Sliding-window circuit breaker: drop the oldest complete tool exchanges when over budget.

        Each tool-loop iteration appends exactly one ``(assistant, user/tool_result)`` pair after the
        ``initial_len`` seed messages, so dropping whole pairs from the front of that tail preserves
        role alternation and tool_use/tool_result adjacency (Anthropic) while keeping the seed brief
        and the most recent turns. Returns ``(messages, dropped_pairs)``.
        """
        if self._messages_size(messages) <= self._context_char_budget:
            return messages, 0
        head = messages[:initial_len]
        tail = messages[initial_len:]
        dropped = 0
        # Keep at least the most recent pair so the model still sees the latest tool result.
        while len(tail) > 2 and self._messages_size(head + tail) > self._context_char_budget:
            tail = tail[2:]
            dropped += 1
        return head + tail, dropped

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
        opts = ollama_options()
        if opts:
            body["options"] = opts
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
        from core.context import rolling_state_block

        # Strip AgentForge's own runtime/config (model, Ollama/WSL host, provider) from the
        # replayed decisions so it cannot bleed into a worker's brief and into the product (F4).
        decisions = sanitize_decisions(await self.memory.recall_all("decision"))
        artifacts = await self.memory.recall_all("artifact_ref")
        parts: list[str] = []
        if decisions:
            # Bound the replayed decisions log: keep recent entries verbatim and condense older
            # ones so long adaptive runs don't exhaust the context window (context-decay guard).
            parts.append(
                "## Sprint Decisions\n"
                + rolling_state_block(decisions, max_chars=self._decisions_budget_chars)
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

    async def _edit_file_handler(self, tool_input: dict) -> str:
        """Apply an anchored search/replace to an existing file (patch-based edit).

        Safer/cheaper than a full rewrite: the model supplies an exact snippet (``old_string``)
        and its replacement (``new_string``). We require the snippet to exist and be unique
        (unless ``replace_all``), then write back through ``ArtifactStore.write`` so the existing
        path validation / code-root sandbox applies. Failures return an actionable message rather
        than raising, so the agent can correct and retry within the loop.
        """
        path = (tool_input.get("path") or "").strip()
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        replace_all = bool(tool_input.get("replace_all", False))

        if not path:
            return "[edit_file error: 'path' is required]"
        if not isinstance(old, str) or not isinstance(new, str):
            return "[edit_file error: 'old_string' and 'new_string' must be strings]"
        if old == "":
            return ("[edit_file error: 'old_string' must be non-empty. "
                    "To create a new file, use write_file instead.]")
        if old == new:
            return "[edit_file error: 'old_string' and 'new_string' are identical — nothing to change.]"

        content = await self.artifacts.read(path)
        if content.startswith("[File not found:") or content.startswith("[Access denied:"):
            return (f"[edit_file error: cannot edit {path}: {content.strip()} "
                    f"Use write_file to create a new file, or fix the path.]")

        count = content.count(old)
        mode = "exact"
        if count == 0:
            # Fallback ladder: the exact anchor missed — most often just indentation / trailing-
            # whitespace drift, not a real content change. Retry with a whitespace-tolerant,
            # line-aligned match before giving up.
            status, fb_content = _whitespace_tolerant_replace(content, old, new)
            if status == "ambiguous":
                return (f"[edit_file error: old_string matches multiple locations in {path} when "
                        f"ignoring whitespace; add surrounding lines to disambiguate, or set "
                        f"replace_all=true.]")
            if status != "ok" or fb_content is None:
                # Final rung: point the agent at the cheapest recovery for this file's size.
                n_lines = content.count("\n") + 1
                if n_lines <= _EDIT_SMALL_FILE_LINES:
                    hint = (f"this file is small ({n_lines} lines) — you may rewrite it wholesale "
                            f"with write_file instead")
                else:
                    hint = ("call read_file and copy a larger, exact snippet (including "
                            "whitespace/indentation), then try again")
                return f"[edit_file error: old_string not found in {path}; {hint}.]"
            new_content = fb_content
            mode = "whitespace-tolerant"
            replaced = 1
        else:
            if count > 1 and not replace_all:
                return (f"[edit_file error: old_string occurs {count} times in {path}; it must match "
                        f"exactly once. Add surrounding lines to make it unique, or set replace_all=true.]")
            new_content = content.replace(old, new) if replace_all else content.replace(old, new, 1)
            replaced = count if replace_all else 1

        try:
            full_path = await self.artifacts.write(path, new_content)
        except ValueError as e:
            # Path traversal / outside-root attempts are rejected by the artifact store.
            return f"[edit_file error: {e}]"

        await self.memory.remember(f"edited_{path}", str(full_path), "artifact_ref")
        self._edited_files.append(str(full_path))
        self.console.log(f"[cyan]{self.role}[/cyan] edited: {full_path} ({replaced} replacement(s), {mode})")
        note = "" if mode == "exact" else " (matched ignoring whitespace)"
        return f"Edited {path}: replaced {replaced} occurrence(s){note}; file is now {len(new_content)} bytes."

    async def _generate_mock_data_handler(self, tool_input: dict) -> str:
        """Generate a deterministic synthetic dataset fixture and write it through the sandbox."""
        from core import mockdata

        path = (tool_input.get("path") or "").strip()
        if not path:
            return "[generate_mock_data error: 'path' is required]"
        columns = tool_input.get("columns")
        if not isinstance(columns, list) or not columns:
            return "[generate_mock_data error: 'columns' must be a non-empty list of {name, type}]"
        named = [c for c in columns if isinstance(c, dict) and str(c.get("name", "")).strip()]
        if not named:
            return "[generate_mock_data error: no columns with a 'name']"

        fmt = str(tool_input.get("format", "csv")).lower()
        if fmt not in ("csv", "json", "jsonl"):
            fmt = "csv"
        try:
            rows = int(tool_input.get("rows", 20))
        except (TypeError, ValueError):
            rows = 20
        try:
            seed = int(tool_input.get("seed", 0))
        except (TypeError, ValueError):
            seed = 0

        data = mockdata.generate_rows(named, rows, seed=seed)
        content = mockdata.render(data, fmt, named)
        try:
            full_path = await self.artifacts.write(path, content)
        except ValueError as e:
            # Path traversal / outside-root attempts are rejected by the artifact store.
            return f"[generate_mock_data error: {e}]"

        await self.memory.remember(f"mockdata_{path}", str(full_path), "artifact_ref")
        self._edited_files.append(str(full_path))
        self.console.log(f"[cyan]{self.role}[/cyan] generated mock data: {full_path} ({len(data)} rows, {fmt})")
        return f"Generated {len(data)} rows of mock data → {path} ({fmt}, {len(content)} bytes)."

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
        edit_tools: bool = False,
        mock_tools: bool = False,
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

        When ``edit_tools`` is true, ``edit_file`` is injected so agents make surgical, anchored
        edits to existing files instead of rewriting them whole. ``self._edited_files`` is reset
        at the start of the loop and accumulates the paths edited, so callers can fold them into
        the set of changed files they report.

        When ``mock_tools`` is true, ``generate_mock_data`` is injected so Data/ML engineers can
        generate standardized dummy datasets to test pipelines locally without production data.
        Generated fixture paths also accumulate in ``self._edited_files``.

        Returns ``{"final_text", "tool_calls", "results", "steps", "stop", "compacted_pairs"}``.
        """
        effective_tools = list(tools or [])
        handlers = dict(tool_handlers)
        # Both edit_file and generate_mock_data record written paths in _edited_files; reset once
        # at the start of the loop so callers see only this loop's changes.
        if edit_tools or mock_tools:
            self._edited_files = []
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
        if edit_tools:
            if not any(t.get("name") == _EDIT_FILE_TOOL["name"] for t in effective_tools):
                effective_tools.append(_EDIT_FILE_TOOL)
            handlers.setdefault("edit_file", self._edit_file_handler)
        if mock_tools:
            if not any(t.get("name") == _GENERATE_MOCK_DATA_TOOL["name"] for t in effective_tools):
                effective_tools.append(_GENERATE_MOCK_DATA_TOOL)
            handlers.setdefault("generate_mock_data", self._generate_mock_data_handler)
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
        initial_len = len(messages)

        all_calls: list[tuple[str, dict]] = []
        results: list[tuple[str, dict, str]] = []
        text_parts: list[str] = []
        stop = "max_steps"
        step = 0
        compacted_pairs = 0

        for step in range(max_steps):
            # Context-decay circuit breaker: trim the oldest tool exchanges before the call so a
            # long loop degrades gracefully instead of failing on an overflowed context window.
            messages, dropped = self._compact_messages(messages, initial_len)
            if dropped:
                compacted_pairs += dropped
                _log.warning("context_compacted role=%s dropped_pairs=%s step=%s", self.role, dropped, step)
                emit("context_compacted", role=self.role, dropped_pairs=dropped, step=step)
                if compacted_pairs == dropped:  # first compaction in this loop — record once
                    await self.memory.remember(
                        f"context_compacted_{self.role}",
                        f"trimmed {dropped} oldest tool exchange(s) at step {step} to stay within the "
                        f"context budget; relying on recent turns + the decisions log",
                        "decision",
                    )

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
            "compacted_pairs": compacted_pairs,
        }

    @abstractmethod
    async def run(self) -> None:
        pass
