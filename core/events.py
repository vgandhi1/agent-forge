"""Structured machine-readable event log for host assistants.

When AgentForge is driven as a subprocess by an AI coding assistant (Cursor, Codex,
Claude Code, ...), the human-facing Rich console output is hard to parse reliably.
This module emits **one JSON object per line on stderr** so the host assistant can
tail and consume typed events instead of scraping console text.

It is **opt-in and side-effect-free by default**: nothing is written unless the
environment variable ``AGENTFORGE_JSON_LOG`` is truthy. The variable is read from
``os.environ`` at call time (not at import), so tests can toggle it with
``monkeypatch.setenv`` / ``delenv`` without reimporting the module.

Usage::

    from core.events import emit
    emit("phase_complete", phase="backend", role="backend")
    emit("files_changed", role="backend", count=23)
    emit("review_verdict", role="qa", decision="approve")
    emit("pytest_result", passed=44, failed=0, exit_code=0)
    emit("exit_summary", status="ok", phases=5)

Each emitted line is a JSON object of the shape::

    {"event": "<event_type>", "ts": "<iso8601-utc>", ...fields}

``emit`` never raises: if serialization or stderr writes fail, the error is swallowed
so structured logging can never break a real run.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from typing import Any

# Documented, supported event types. ``emit`` does not reject other strings (so callers
# stay forward-compatible), but these are the ones host assistants can rely on.
EVENT_TYPES: tuple[str, ...] = (
    "phase_complete",
    "files_changed",
    "review_verdict",
    "pytest_result",
    "exit_summary",
)

_TRUTHY = {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Return True when JSON event logging is switched on via the environment.

    Read at call time so tests (and the CLI) can toggle ``AGENTFORGE_JSON_LOG``
    dynamically. Any of ``1/true/yes/on`` (case-insensitive) enables it.
    """
    return os.environ.get("AGENTFORGE_JSON_LOG", "").strip().lower() in _TRUTHY


def _timestamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def emit(event_type: str, **fields: Any) -> None:
    """Write one JSON event line to stderr — but only when JSON logging is enabled.

    No-op when ``AGENTFORGE_JSON_LOG`` is unset/falsey, so default human output is
    unchanged. Never raises: any failure (non-serializable field, closed stderr) is
    swallowed. Reserved keys ``event`` and ``ts`` in ``fields`` are ignored in favor
    of the event type and a fresh timestamp.
    """
    if not enabled():
        return
    try:
        record: dict[str, Any] = {"event": event_type, "ts": _timestamp()}
        for key, value in fields.items():
            if key in ("event", "ts"):
                continue
            record[key] = value
        line = json.dumps(record, default=str, ensure_ascii=False)
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        # Structured logging must never break a real run.
        pass
