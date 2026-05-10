import pytest

import cli


def test_resolve_phases_custom_order() -> None:
    phases = cli._resolve_phases(None, "pm,qa")
    assert [p[0] for p in phases] == ["pm", "qa"]


def test_resolve_phases_unknown_role_exits() -> None:
    with pytest.raises(SystemExit):
        cli._resolve_phases(None, "pm,notarole")


def test_resolve_phases_full_is_none() -> None:
    assert cli._resolve_phases("full", None) is None


def test_resolve_phases_unknown_preset_exits() -> None:
    with pytest.raises(SystemExit):
        cli._resolve_phases("not-a-preset", None)
