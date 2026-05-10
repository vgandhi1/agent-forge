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
}

VALID_ROLES = ("pm", "architect", "backend", "qa", "devops")
