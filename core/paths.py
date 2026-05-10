"""Resolved project paths (workspace, DB). Override with AGENTFORGE_ROOT / AGENTFORGE_WORKSPACE."""

from __future__ import annotations

import os
from pathlib import Path

# Directory containing agentforge.db and default workspace/ (usually the repo root / agents folder)
ROOT = Path(os.environ.get("AGENTFORGE_ROOT", os.getcwd())).resolve()

# Generated artifacts
WORKSPACE = (ROOT / os.environ.get("AGENTFORGE_WORKSPACE", "workspace")).resolve()

# SQLite persistence
DB_PATH = (ROOT / os.environ.get("AGENTFORGE_DB", "agentforge.db")).resolve()
