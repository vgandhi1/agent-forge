"""Persisted Known-Gaps log for scope lock.

When an agent finds something outside the current task (another bug, a missing feature,
a refactor), it records it here instead of expanding scope. The Reviewer routes drift
here too. The Lead surfaces the log in the deploy summary.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

GAPS_PATH = "reports/known_gaps.md"

_HEADER = "# Known Gaps\n\nOut-of-scope items deferred during sprints (scope lock). Each entry: when, who, category, what.\n"


async def log_gap(store: Any, source: str, category: str, description: str) -> None:
    """Append one entry to the Known-Gaps log, creating it if needed.

    ``store`` is duck-typed: it must expose async ``read(path)`` and ``write(path, content)``
    (ArtifactStore, or a fake in tests).
    """
    existing = await store.read(GAPS_PATH)
    # ArtifactStore.read returns a "[File not found: …]"/"[Access denied…]" marker when missing.
    if not existing.strip() or existing.lstrip().startswith("["):
        existing = _HEADER
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    entry = f"- [{ts}] **{source}** ({category or 'general'}): {description.strip()}"
    await store.write(GAPS_PATH, existing.rstrip() + "\n" + entry + "\n")
