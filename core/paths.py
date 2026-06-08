"""Resolved project paths (code tree, metadata, DB).

Two roots are distinguished so AgentForge can operate on a user's existing repo:

- ``WORKSPACE`` — the **code root** that workers read/write/grep. Defaults to ``ROOT/workspace``
  (greenfield sandbox); set to the target repo when ``--target-repo`` / ``AGENTFORGE_TARGET_REPO``
  is given.
- ``METADATA_ROOT`` — where AgentForge writes its own artifacts (``handoff/``, ``reports/``). Stays
  out of the user's source tree: ``WORKSPACE`` in default mode, ``<target>/.agentforge`` in target mode.
- ``DB_PATH`` — SQLite persistence, always under ``ROOT`` (never inside the target repo).

``ROOT`` is AgentForge's own bookkeeping directory (holds ``agentforge.db`` and the default
``workspace/``). It is resolved by :func:`resolve_root` in this order:

1. ``AGENTFORGE_ROOT`` env var, if set (highest priority; preserves all existing behavior).
2. Else, if the cwd looks like the AgentForge **source checkout** (contains ``main.py`` plus
   ``core/`` and ``agents/`` directories) → use the cwd, so running from the repo behaves as before.
3. Else (globally installed / run from an unrelated cwd) → a stable per-user home,
   ``AGENTFORGE_HOME`` if set else ``~/.agentforge``. This keeps ``workspace/`` and the DB out of
   the user's current directory; pass ``--target-repo`` to operate on that cwd's code.

Override with AGENTFORGE_ROOT / AGENTFORGE_HOME / AGENTFORGE_WORKSPACE / AGENTFORGE_TARGET_REPO / AGENTFORGE_DB.
"""

from __future__ import annotations

import os
from pathlib import Path


def _looks_like_source_checkout(cwd: Path) -> bool:
    """True if ``cwd`` is the AgentForge source tree (has main.py + core/ + agents/)."""
    return (
        (cwd / "main.py").is_file()
        and (cwd / "core").is_dir()
        and (cwd / "agents").is_dir()
    )


def resolve_root(cwd: Path | None = None, env: "os._Environ[str] | dict[str, str] | None" = None) -> Path:
    """Resolve AgentForge's bookkeeping ROOT (see module docstring for the order).

    ``cwd`` and ``env`` default to ``os.getcwd()`` / ``os.environ`` but may be passed for testing.
    """
    if env is None:
        env = os.environ
    cwd = Path(cwd) if cwd is not None else Path(os.getcwd())

    explicit = env.get("AGENTFORGE_ROOT")
    if explicit:
        return Path(explicit).resolve()
    if _looks_like_source_checkout(cwd):
        return cwd.resolve()
    home = env.get("AGENTFORGE_HOME")
    base = Path(home) if home else (Path.home() / ".agentforge")
    return base.resolve()


# Directory containing agentforge.db and default workspace/ (AgentForge's own install dir / cwd / ~/.agentforge)
ROOT = resolve_root()

# SQLite persistence — always under ROOT, never inside a target repo
DB_PATH = (ROOT / os.environ.get("AGENTFORGE_DB", "agentforge.db")).resolve()


def resolve_roots(target_repo: str | None = None) -> tuple[Path, Path]:
    """Return ``(code_root, metadata_root)`` for the given target repo (or default sandbox).

    ``target_repo`` may come from ``--target-repo`` or ``AGENTFORGE_TARGET_REPO``. When set, the
    code root is the repo itself and metadata is isolated under ``<repo>/.agentforge``.
    """
    target = target_repo or os.environ.get("AGENTFORGE_TARGET_REPO")
    if target:
        code_root = Path(target).expanduser().resolve()
        metadata_root = (code_root / ".agentforge").resolve()
        return code_root, metadata_root
    code_root = (ROOT / os.environ.get("AGENTFORGE_WORKSPACE", "workspace")).resolve()
    return code_root, code_root


# Code root (workers read/write here) and metadata root (handoff/, reports/)
WORKSPACE, METADATA_ROOT = resolve_roots()
