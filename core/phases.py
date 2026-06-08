"""Pipeline phase definitions for CLI presets and the Lead orchestrator."""

from __future__ import annotations

# Full lifecycle: intake → design → implementation → feature testing → ship
DEFAULT_PHASES: list[tuple[str, str]] = [
    (
        "pm",
        "Intake & requirements: capture the sprint goal as docs/requirements.md "
        "(personas, user stories, API overview, NFRs, MoSCoW, acceptance criteria)",
    ),
    (
        "architect",
        "Development project design: docs/architecture.md (schema, API contracts, security, scale)",
    ),
    (
        "backend",
        "Implementation: full FastAPI app under workspace/dailyease per approved architecture",
    ),
    (
        "qa",
        "Feature testing: pytest suite + reports/qa_report.md; run tests and fix failures",
    ),
    (
        "devops",
        "Production readiness: Dockerfile, compose, CI workflow, docs/deployment.md",
    ),
]

PHASE_PRESETS: dict[str, list[tuple[str, str]] | None] = {
    "full": None,
    "intake": [
        (
            "pm",
            "Intake only: produce docs/requirements.md from the sprint goal (structured PRD + stories + API sketch)",
        ),
    ],
    "design": [
        (
            "pm",
            "Requirements intake: docs/requirements.md",
        ),
        (
            "architect",
            "Architecture: docs/architecture.md based on requirements",
        ),
    ],
    "implement": [
        (
            "backend",
            "Implementation only: FastAPI app in workspace/dailyease (use existing docs if present)",
        ),
    ],
    "test": [
        (
            "qa",
            "Feature testing only: pytest under dailyease/tests + reports/qa_report.md; run pytest and fix failures",
        ),
    ],
    "ship": [
        (
            "devops",
            "Ship: Dockerfile, docker-compose, CI workflow, deployment runbook",
        ),
    ],
    "improve": [
        (
            "backend",
            "Improvements sprint: refactor, performance, reliability, and API polish per the sprint goal",
        ),
        (
            "qa",
            "Re-verify: update tests if needed, run pytest, refresh QA report",
        ),
    ],
    "debug": [
        (
            "qa",
            "Reproduce: read the relevant code and tests, then reproduce the reported failure "
            "(run the failing test/command) and pinpoint where it breaks",
        ),
        (
            "backend",
            "Localize & patch: fix the root cause in the existing code identified by reproduction; "
            "keep the change minimal and scoped to the bug",
        ),
        (
            "qa",
            "Re-verify: re-run the previously failing test/command and confirm the fix; "
            "add a regression test that guards the bug",
        ),
    ],
    "fix": [
        (
            "backend",
            "Apply fix: read the affected code and implement the known fix per the sprint goal, "
            "scoped to the change",
        ),
        (
            "qa",
            "Verify: run the test suite and confirm the fix; add or update tests as needed",
        ),
    ],
    "harden": [
        (
            "qa",
            "Audit & test: read the existing code, run the test suite, and identify reliability, "
            "edge-case, and error-handling gaps",
        ),
        (
            "backend",
            "Harden: patch the gaps surfaced by QA — input validation, error handling, and "
            "robustness — without changing intended behavior",
        ),
        (
            "devops",
            "Production readiness: review build/CI/deploy config and close operational gaps "
            "(packaging, health checks, runbook)",
        ),
    ],
}

VALID_ROLES = ("pm", "architect", "backend", "qa", "devops")
