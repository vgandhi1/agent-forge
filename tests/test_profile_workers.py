from core.profile import DEFAULT_PROFILE, Profile

from agents.backend_developer import (
    _REQUIRED_FILES,
    build_prompt,
    required_files,
)
from agents.qa_engineer import _QA_FILES, build_qa_prompt, qa_files


def _existing_profile() -> Profile:
    return Profile(
        name="my-api",
        stack=["fastapi", "sqlalchemy", "pytest"],
        app_root="src",
        test_cmd=["pytest", "-q"],
    )


# ---- backend required_files gating ----

def test_required_files_default_is_full_checklist() -> None:
    assert required_files(DEFAULT_PROFILE) == list(_REQUIRED_FILES)
    assert len(required_files(DEFAULT_PROFILE)) == 23


def test_required_files_empty_for_existing_repo() -> None:
    assert required_files(_existing_profile()) == []


# ---- backend build_prompt ----

def test_backend_prompt_default_has_dailyease_checklist() -> None:
    prompt = build_prompt(
        DEFAULT_PROFILE,
        plan_notes="",
        sprint_goal="goal",
        arch_content="arch",
        req_content="req",
        task_description="do it",
    )
    assert "DailyEase" in prompt
    assert "dailyease/main.py" in prompt
    assert "FastAPI" in prompt


def test_backend_prompt_existing_repo_reads_first_no_checklist() -> None:
    profile = _existing_profile()
    prompt = build_prompt(
        profile,
        plan_notes="",
        sprint_goal="fix bug",
        arch_content="",
        req_content="",
        task_description="patch auth",
    )
    assert "DailyEase" not in prompt
    assert "dailyease/main.py" not in prompt
    # instructs to read existing code and write to app_root with stack
    assert "read_file" in prompt
    assert "src/" in prompt
    assert "fastapi" in prompt


def test_backend_prompt_includes_plan_notes() -> None:
    prompt = build_prompt(
        _existing_profile(),
        plan_notes="PLAN_NOTES_MARKER\n",
        sprint_goal="g",
        arch_content="",
        req_content="",
        task_description="t",
    )
    assert prompt.startswith("PLAN_NOTES_MARKER")


# ---- qa gating ----

def test_qa_files_default_is_full_checklist() -> None:
    assert qa_files(DEFAULT_PROFILE) == list(_QA_FILES)


def test_qa_files_empty_for_existing_repo() -> None:
    assert qa_files(_existing_profile()) == []


def test_qa_prompt_default_has_dailyease_checklist() -> None:
    prompt = build_qa_prompt(
        DEFAULT_PROFILE,
        sprint_goal="g",
        impl_summary="dailyease/main.py",
        code_excerpts="main.py:\n```\n...\n```\n",
        task_description="t",
    )
    assert "DailyEase" in prompt
    assert "dailyease/tests/conftest.py" in prompt


def test_qa_prompt_existing_repo_reads_first() -> None:
    profile = _existing_profile()
    prompt = build_qa_prompt(
        profile,
        sprint_goal="g",
        impl_summary="src/app.py",
        code_excerpts="",
        task_description="verify fix",
    )
    assert "DailyEase" not in prompt
    assert "dailyease/tests" not in prompt
    assert "read_file" in prompt
    assert "src/" in prompt
    # verify_cmd surfaced
    assert "pytest -q" in prompt
