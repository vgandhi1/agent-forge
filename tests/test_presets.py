from core.phases import PHASE_PRESETS, VALID_ROLES

_DAILYEASE_MARKERS = ("dailyease", "fastapi", "sqlalchemy", "aiosqlite", "pydantic")


def _roles(preset: str) -> list[str]:
    return [role for role, _desc in PHASE_PRESETS[preset]]


def test_debug_fix_harden_exist() -> None:
    for name in ("debug", "fix", "harden"):
        assert name in PHASE_PRESETS, f"missing preset {name}"
        assert isinstance(PHASE_PRESETS[name], list)


def test_debug_role_sequence() -> None:
    # reproduce (qa) -> fix (backend) -> re-verify (qa)
    assert _roles("debug") == ["qa", "backend", "qa"]


def test_fix_role_sequence() -> None:
    assert _roles("fix") == ["backend", "qa"]


def test_harden_role_sequence() -> None:
    assert _roles("harden") == ["qa", "backend", "devops"]


def test_preset_roles_are_valid() -> None:
    for name in ("debug", "fix", "harden"):
        for role, _desc in PHASE_PRESETS[name]:
            assert role in VALID_ROLES, f"{name} uses invalid role {role}"


def test_descriptions_non_empty() -> None:
    for name in ("debug", "fix", "harden"):
        for role, desc in PHASE_PRESETS[name]:
            assert isinstance(desc, str) and desc.strip(), f"{name}/{role} has empty description"


def test_descriptions_not_dailyease_specific() -> None:
    for name in ("debug", "fix", "harden"):
        for role, desc in PHASE_PRESETS[name]:
            low = desc.lower()
            for marker in _DAILYEASE_MARKERS:
                assert marker not in low, f"{name}/{role} description mentions '{marker}': {desc!r}"
