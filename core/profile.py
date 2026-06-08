"""Project profile: how AgentForge adapts to the target repo's stack.

A profile decouples worker prompts and the deploy/verify step from the hardcoded DailyEase
FastAPI shape. Resolution order (first hit wins):

1. ``<metadata_root>/profile.yaml`` — explicit profile committed by the user (``.agentforge/profile.yaml``
   inside a ``--target-repo``).
2. Stack discovery from the code root (``pyproject.toml`` → python/pytest, ``package.json`` → node/npm,
   ``go.mod`` → go test).
3. ``DEFAULT_PROFILE`` — the DailyEase greenfield behavior (backward compatible).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Profile:
    name: str = "dailyease"
    stack: list[str] = field(default_factory=lambda: ["fastapi", "sqlalchemy", "pytest"])
    app_root: str = "dailyease"          # code dir relative to the code root
    test_cmd: list[str] = field(default_factory=lambda: ["pytest", "-q"])
    lint_cmd: list[str] | None = None
    _verify_cmd: list[str] | None = None

    @property
    def verify_cmd(self) -> list[str]:
        """Command used by the deploy gate to verify the project (defaults to ``test_cmd``)."""
        return self._verify_cmd or self.test_cmd

    def describe(self) -> str:
        return f"{self.name} [{', '.join(self.stack)}] app_root={self.app_root}/ verify={' '.join(self.verify_cmd)}"


# DailyEase greenfield default — keeps existing behavior when no profile/discovery applies.
DEFAULT_PROFILE = Profile()


def _from_mapping(data: dict) -> Profile:
    verify = data.get("verify_cmd")
    return Profile(
        name=str(data.get("name", "project")),
        stack=list(data.get("stack", []) or []),
        app_root=str(data.get("app_root", ".")),
        test_cmd=list(data.get("test_cmd", ["pytest", "-q"]) or ["pytest", "-q"]),
        lint_cmd=list(data["lint_cmd"]) if data.get("lint_cmd") else None,
        _verify_cmd=list(verify) if verify else None,
    )


def _discover(code_root: Path) -> Profile | None:
    """Infer a profile from common project manifests. Returns None if nothing recognizable."""
    if (code_root / "pyproject.toml").is_file() or (code_root / "setup.py").is_file():
        return Profile(name=code_root.name, stack=["python"], app_root="src",
                       test_cmd=["pytest", "-q"], lint_cmd=["ruff", "check", "."])
    pkg = code_root / "package.json"
    if pkg.is_file():
        stack = ["node"]
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "next" in deps:
                stack.append("next")
            elif "react" in deps:
                stack.append("react")
        except (json.JSONDecodeError, OSError):
            pass
        return Profile(name=code_root.name, stack=stack, app_root="src",
                       test_cmd=["npm", "test"], lint_cmd=["npm", "run", "lint"])
    if (code_root / "go.mod").is_file():
        return Profile(name=code_root.name, stack=["go"], app_root=".",
                       test_cmd=["go", "test", "./..."])
    return None


def load_profile(code_root: Path, metadata_root: Path | None = None) -> Profile:
    """Resolve the active profile for the given code/metadata roots.

    Explicit ``profile.yaml`` wins; otherwise discover from manifests; otherwise DailyEase default.
    """
    metadata_root = metadata_root or code_root
    for candidate in (metadata_root / "profile.yaml", code_root / ".agentforge" / "profile.yaml"):
        if candidate.is_file():
            try:
                data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    return _from_mapping(data)
            except (yaml.YAMLError, OSError):
                break
    return _discover(code_root) or DEFAULT_PROFILE
