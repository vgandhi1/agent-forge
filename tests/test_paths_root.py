from pathlib import Path

from core import paths


def _make_source_checkout(base: Path) -> Path:
    """Create a fake AgentForge source tree (main.py + core/ + agents/) under ``base``."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "main.py").write_text("# fake entrypoint\n")
    (base / "core").mkdir()
    (base / "agents").mkdir()
    return base


def test_agentforge_root_env_wins(tmp_path):
    # AGENTFORGE_ROOT takes precedence even when cwd looks like a source checkout.
    checkout = _make_source_checkout(tmp_path / "checkout")
    explicit = tmp_path / "explicit-root"
    explicit.mkdir()
    root = paths.resolve_root(cwd=checkout, env={"AGENTFORGE_ROOT": str(explicit)})
    assert root == explicit.resolve()


def test_source_checkout_resolves_to_cwd(tmp_path):
    # A cwd with main.py + core/ + agents/ → ROOT is that cwd (preserves repo behavior).
    checkout = _make_source_checkout(tmp_path / "src")
    root = paths.resolve_root(cwd=checkout, env={})
    assert root == checkout.resolve()


def test_non_source_dir_uses_agentforge_home(tmp_path):
    # Not a source checkout, AGENTFORGE_HOME set → resolves to that home.
    plain = tmp_path / "some-project"
    plain.mkdir()
    home = tmp_path / "custom-home"
    root = paths.resolve_root(cwd=plain, env={"AGENTFORGE_HOME": str(home)})
    assert root == home.resolve()


def test_default_falls_back_to_user_home(tmp_path, monkeypatch):
    # Nothing set and not a source checkout → ~/.agentforge.
    plain = tmp_path / "elsewhere"
    plain.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    root = paths.resolve_root(cwd=plain, env={})
    assert root == (fake_home / ".agentforge").resolve()
