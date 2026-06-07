"""Human-readable handoff files and a resumable session checkpoint.

Each completed phase writes ``handoff/<role>.md`` (brief, files, review summary) for an
auditable trail, and updates ``handoff/checkpoint.json`` so a later run can resume — skipping
phases already completed for the same sprint goal.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

CHECKPOINT_PATH = "handoff/checkpoint.json"


def goal_fingerprint(goal: str) -> str:
    return hashlib.sha256((goal or "").strip().encode("utf-8")).hexdigest()[:12]


async def load_checkpoint(store: Any) -> dict[str, Any]:
    raw = await store.read(CHECKPOINT_PATH)
    if not raw.strip() or raw.lstrip().startswith("["):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def save_checkpoint(store: Any, data: dict[str, Any]) -> None:
    await store.write(CHECKPOINT_PATH, json.dumps(data, indent=2))


async def record_phase(
    store: Any,
    *,
    goal: str,
    role: str,
    brief: str,
    files: list[str],
    review_summary: str,
) -> None:
    """Write the per-phase handoff file and update the checkpoint (resetting on goal change)."""
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    file_lines = [f"- {f}" for f in files] or ["(none)"]
    body = [
        f"# Handoff — {role}",
        f"Updated: {ts}",
        "",
        "## Brief",
        brief or "(none)",
        "",
        "## Files",
        *file_lines,
        "",
        "## Review",
        review_summary or "(none)",
        "",
    ]
    await store.write(f"handoff/{role}.md", "\n".join(body))

    fp = goal_fingerprint(goal)
    cp = await load_checkpoint(store)
    if cp.get("goal_fp") != fp:
        cp = {"goal_fp": fp, "goal": (goal or "").strip()[:200], "completed": [], "artifacts": {}}
    completed = cp.setdefault("completed", [])
    if role not in completed:
        completed.append(role)
    cp.setdefault("artifacts", {})[f"{role}_artifact"] = files[0] if files else ""
    cp["updated"] = ts
    await save_checkpoint(store, cp)
