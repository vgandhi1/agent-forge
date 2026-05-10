from __future__ import annotations

import re
from pathlib import Path

from .paths import WORKSPACE

# Relative paths only; no traversal (workspace security policy)
_SAFE_REL = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_./-]*$")


def _validate_relative_path(relative_path: str) -> Path:
    if not relative_path or not isinstance(relative_path, str):
        raise ValueError("Invalid path")
    if not _SAFE_REL.match(relative_path):
        raise ValueError("Path must be a safe relative path under workspace")
    p = Path(relative_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Path traversal not allowed")
    full = (WORKSPACE / p).resolve()
    workspace_resolved = WORKSPACE.resolve()
    if full == workspace_resolved:
        return p
    try:
        full.relative_to(workspace_resolved)
    except ValueError as e:
        raise ValueError("Path escapes workspace") from e
    return p


class ArtifactStore:
    WORKSPACE = WORKSPACE

    @staticmethod
    async def write(relative_path: str, content: str) -> Path:
        rel = _validate_relative_path(relative_path)
        full_path = WORKSPACE / rel
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return full_path

    @staticmethod
    async def read(path: str | Path) -> str:
        p = Path(path) if not isinstance(path, Path) else path
        if not p.is_absolute():
            p = WORKSPACE / p
        p = p.resolve()
        workspace_resolved = WORKSPACE.resolve()
        try:
            p.relative_to(workspace_resolved)
        except ValueError:
            return "[Access denied: path outside workspace]"
        if not p.exists():
            return f"[File not found: {p}]"
        return p.read_text(encoding="utf-8")

    @staticmethod
    def list_files(subdir: str = "") -> list[Path]:
        if subdir:
            _validate_relative_path(subdir)  # ensures no traversal
        base = WORKSPACE / subdir if subdir else WORKSPACE
        if not base.exists():
            return []
        base = base.resolve()
        workspace_resolved = WORKSPACE.resolve()
        if base != workspace_resolved:
            try:
                base.relative_to(workspace_resolved)
            except ValueError:
                return []
        return [p for p in base.rglob("*") if p.is_file()]

    @staticmethod
    def dailyease_root() -> Path:
        return WORKSPACE / "dailyease"
