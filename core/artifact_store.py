from __future__ import annotations

import re
from pathlib import Path

from .paths import METADATA_ROOT, WORKSPACE

# Relative paths only; no traversal (workspace security policy)
_SAFE_REL = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_./-]*$")

# First path segment routed to the metadata root instead of the code root, so AgentForge's own
# artifacts never land in the user's source tree under --target-repo.
_METADATA_PREFIXES = ("handoff", "reports")


def configure_roots(code_root: Path, metadata_root: Path | None = None) -> None:
    """Rebind the code/metadata roots at runtime (e.g. after parsing ``--target-repo``).

    Updates module globals and the ``ArtifactStore.WORKSPACE`` class attribute so all read/write/
    grep operations resolve against the new tree. Idempotent.
    """
    global WORKSPACE, METADATA_ROOT
    WORKSPACE = Path(code_root).resolve()
    METADATA_ROOT = Path(metadata_root).resolve() if metadata_root else WORKSPACE
    ArtifactStore.WORKSPACE = WORKSPACE


def _root_for(relative_path: str) -> Path:
    """Code root by default; metadata root for AgentForge's own ``handoff/`` and ``reports/``."""
    first = relative_path.replace("\\", "/").split("/", 1)[0]
    return METADATA_ROOT if first in _METADATA_PREFIXES else WORKSPACE


def _validate_under(relative_path: str, base: Path) -> Path:
    if not relative_path or not isinstance(relative_path, str):
        raise ValueError("Invalid path")
    if not _SAFE_REL.match(relative_path):
        raise ValueError("Path must be a safe relative path under the project root")
    p = Path(relative_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Path traversal not allowed")
    base_resolved = base.resolve()
    full = (base / p).resolve()
    if full == base_resolved:
        return p
    try:
        full.relative_to(base_resolved)
    except ValueError as e:
        raise ValueError("Path escapes the project root") from e
    return p


def _validate_relative_path(relative_path: str) -> Path:
    """Validate a code-root-relative path (no traversal). Kept for code-only callers."""
    return _validate_under(relative_path, WORKSPACE)


class ArtifactStore:
    WORKSPACE = WORKSPACE

    @staticmethod
    async def write(relative_path: str, content: str) -> Path:
        base = _root_for(relative_path)
        rel = _validate_under(relative_path, base)
        full_path = base / rel
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return full_path

    @staticmethod
    async def read(path: str | Path) -> str:
        p = Path(path) if not isinstance(path, Path) else path
        if not p.is_absolute():
            base = _root_for(str(p))
            p = base / p
        p = p.resolve()
        # Allow reads from either the code root or the metadata root
        for root in {WORKSPACE.resolve(), METADATA_ROOT.resolve()}:
            try:
                p.relative_to(root)
                break
            except ValueError:
                continue
        else:
            return "[Access denied: path outside project root]"
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

    # --- Read tools for workers (bug-find / refactor): bounded output, no traversal ---

    @staticmethod
    async def read_paginated(path: str, offset: int = 0, limit: int = 400) -> str:
        """Read a workspace file by line window. Returns numbered lines, capped at ``limit``."""
        content = await ArtifactStore.read(path)
        if content.startswith("[File not found:") or content.startswith("[Access denied:"):
            return content
        lines = content.splitlines()
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 2000))
        window = lines[offset:offset + limit]
        numbered = "\n".join(f"{offset + i + 1}\t{ln}" for i, ln in enumerate(window))
        more = len(lines) - (offset + len(window))
        footer = f"\n… {more} more lines (use offset={offset + limit})" if more > 0 else ""
        return numbered + footer if numbered else "[empty file]"

    @staticmethod
    def glob_files(pattern: str = "*", subdir: str = "", cap: int = 200) -> str:
        """List workspace files matching a glob (recursive). Capped listing as text."""
        if subdir:
            _validate_relative_path(subdir)
        base = (WORKSPACE / subdir if subdir else WORKSPACE).resolve()
        workspace_resolved = WORKSPACE.resolve()
        if base != workspace_resolved:
            try:
                base.relative_to(workspace_resolved)
            except ValueError:
                return "[Access denied: path outside workspace]"
        if not base.exists():
            return "[No such directory]"
        pattern = pattern or "*"
        matches = sorted(p for p in base.rglob(pattern) if p.is_file())
        rels = [str(p.relative_to(workspace_resolved)) for p in matches[:cap]]
        out = "\n".join(rels) if rels else "[no matches]"
        if len(matches) > cap:
            out += f"\n… {len(matches) - cap} more (narrow the pattern)"
        return out

    @staticmethod
    def grep(pattern: str, subdir: str = "", glob: str = "*", max_matches: int = 100) -> str:
        """Search workspace files for a regex. Returns ``path:line: text`` entries, bounded."""
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"[Invalid regex: {e}]"
        if subdir:
            _validate_relative_path(subdir)
        base = (WORKSPACE / subdir if subdir else WORKSPACE).resolve()
        workspace_resolved = WORKSPACE.resolve()
        if base != workspace_resolved:
            try:
                base.relative_to(workspace_resolved)
            except ValueError:
                return "[Access denied: path outside workspace]"
        if not base.exists():
            return "[No such directory]"
        max_matches = max(1, min(int(max_matches), 500))
        hits: list[str] = []
        for fp in sorted(base.rglob(glob or "*")):
            if not fp.is_file():
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel = fp.relative_to(workspace_resolved)
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                    if len(hits) >= max_matches:
                        return "\n".join(hits) + f"\n… capped at {max_matches} matches"
        return "\n".join(hits) if hits else "[no matches]"
