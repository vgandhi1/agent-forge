from pathlib import Path

from core.profile import DEFAULT_PROFILE, Profile, load_profile


def test_default_profile_is_dailyease(tmp_path):
    p = load_profile(tmp_path, tmp_path)
    assert p.app_root == "dailyease"
    assert p.verify_cmd == ["pytest", "-q"]


def test_verify_cmd_defaults_to_test_cmd():
    p = Profile(test_cmd=["go", "test", "./..."])
    assert p.verify_cmd == ["go", "test", "./..."]


def test_explicit_yaml_wins(tmp_path):
    meta = tmp_path / ".agentforge"
    meta.mkdir()
    (meta / "profile.yaml").write_text(
        "name: my-api\nstack: [fastapi, pytest]\napp_root: src\ntest_cmd: [pytest, -q, tests]\n",
        encoding="utf-8",
    )
    p = load_profile(tmp_path, meta)
    assert p.name == "my-api"
    assert p.app_root == "src"
    assert p.verify_cmd == ["pytest", "-q", "tests"]


def test_discover_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    p = load_profile(tmp_path, tmp_path / ".agentforge")
    assert "python" in p.stack
    assert p.lint_cmd == ["ruff", "check", "."]


def test_discover_node(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"18"}}', encoding="utf-8")
    p = load_profile(tmp_path, tmp_path / ".agentforge")
    assert "node" in p.stack and "react" in p.stack
    assert p.test_cmd == ["npm", "test"]


def test_discover_go(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    p = load_profile(tmp_path, tmp_path / ".agentforge")
    assert p.stack == ["go"]
    assert p.verify_cmd == ["go", "test", "./..."]
