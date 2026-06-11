"""Tests for the factory data & AI engineering team: data_engineer + ml_engineer roles,
their presets, and cross-wiring consistency (every preset role is a known, promptable role)."""

from core.phases import PHASE_PRESETS, VALID_ROLES
from core.profile import Profile
from agents.base_agent import SYSTEM_PROMPTS
from agents.data_engineer import build_prompt as data_prompt, _DESIGN_DOC as DATA_DOC
from agents.ml_engineer import build_prompt as ml_prompt, _DESIGN_DOC as ML_DOC


def _roles(preset: str) -> list[str]:
    return [role for role, _desc in PHASE_PRESETS[preset]]


def _profile() -> Profile:
    return Profile(
        name="line-analytics",
        stack=["python", "polars", "scikit-learn"],
        app_root="src",
        test_cmd=["pytest", "-q"],
    )


# ---- roles registered ----

def test_new_roles_in_valid_roles() -> None:
    assert "data_engineer" in VALID_ROLES
    assert "ml_engineer" in VALID_ROLES


def test_new_roles_have_system_prompts() -> None:
    for role in ("data_engineer", "ml_engineer"):
        assert role in SYSTEM_PROMPTS
        assert SYSTEM_PROMPTS[role].strip()


def test_every_valid_role_is_promptable() -> None:
    # Consistency guard: a role usable in a phase must have a persona to run it.
    for role in VALID_ROLES:
        assert role in SYSTEM_PROMPTS, f"role {role} has no SYSTEM_PROMPT"


# ---- presets ----

def test_factory_presets_exist() -> None:
    for name in ("data", "ml", "factory"):
        assert name in PHASE_PRESETS
        assert isinstance(PHASE_PRESETS[name], list)


def test_data_preset_sequence() -> None:
    assert _roles("data") == ["pm", "data_engineer", "qa"]


def test_ml_preset_sequence() -> None:
    assert _roles("ml") == ["pm", "data_engineer", "ml_engineer", "qa"]


def test_factory_preset_sequence() -> None:
    assert _roles("factory") == [
        "pm", "architect", "data_engineer", "ml_engineer", "backend", "qa", "devops",
    ]


def test_all_preset_roles_valid() -> None:
    for name, phases in PHASE_PRESETS.items():
        if phases is None:  # "full" sentinel
            continue
        for role, desc in phases:
            assert role in VALID_ROLES, f"{name} uses invalid role {role}"
            assert isinstance(desc, str) and desc.strip()


# ---- prompts are profile-aware and domain-scoped ----

def test_data_prompt_uses_profile_and_contracts() -> None:
    prompt = data_prompt(
        _profile(),
        sprint_goal="ingest CNC telemetry",
        arch_content="arch",
        req_content="req",
        task_description="build ingestion",
    )
    assert "src/" in prompt
    assert "polars" in prompt
    assert DATA_DOC in prompt
    assert "data contract" in prompt.lower()
    assert "idempotent" in prompt.lower()


def test_ml_prompt_consumes_data_contract_no_leakage() -> None:
    prompt = ml_prompt(
        _profile(),
        sprint_goal="predict tool wear",
        data_content="contract",
        req_content="req",
        task_description="train model",
    )
    assert "src/" in prompt
    assert ML_DOC in prompt
    assert "baseline" in prompt.lower()
    assert "leakage" in prompt.lower()
    # Must not invent its own raw ingestion — consumes the data engineer's contract.
    assert "contract" in prompt.lower()
