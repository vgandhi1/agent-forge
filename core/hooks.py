"""Optional per-phase guardrail hooks.

Step 7 of ``docs/evaluation.md`` ("auto test / lint on change") today runs only at the
deploy gate. These hooks let a project run a guardrail *around every phase* — e.g. a lint
or a pytest smoke — without changing AgentForge itself.

A hook is an executable file the project commits at one of:

* ``<metadata_root>/hooks/<stage>``            (e.g. ``.agentforge/hooks/pre-phase``)
* ``<code_root>/.agentforge/hooks/<stage>``

where ``<stage>`` is ``pre-phase`` or ``post-phase``. The mechanism is **opt-in by
presence**: with no hook file, :func:`run_phase_hook` is a no-op (``skipped``). When a hook
exists it runs with the phase role in the environment:

* ``AGENTFORGE_HOOK_STAGE`` — ``pre-phase`` | ``post-phase``
* ``AGENTFORGE_PHASE_ROLE`` — ``pm`` | ``architect`` | ``backend`` | ``qa`` | ``devops``

Hooks are advisory: a non-zero exit is reported (``fail``) and surfaced to the operator but
does **not** abort the sprint. The function never raises — a broken hook cannot break a run.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

STAGES = ("pre-phase", "post-phase")


def _find_hook(stage: str, metadata_root: Path, code_root: Path) -> Path | None:
    """Return the first existing, executable hook for ``stage`` (or None)."""
    candidates = [
        metadata_root / "hooks" / stage,
        code_root / ".agentforge" / "hooks" / stage,
    ]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


async def run_phase_hook(
    stage: str,
    role: str,
    *,
    metadata_root: Path,
    code_root: Path,
    timeout: float = 120.0,
) -> tuple[str, str]:
    """Run the project's ``<stage>`` hook for ``role`` if one is present.

    Returns ``(status, detail)`` where status is ``skipped`` (no hook), ``ok`` (exit 0), or
    ``fail`` (non-zero exit, timeout, or launch error). Never raises. Output is capped to the
    last 4000 chars.
    """
    if stage not in STAGES:
        return "skipped", f"unknown hook stage: {stage}"

    hook = _find_hook(stage, metadata_root, code_root)
    if hook is None:
        return "skipped", f"no {stage} hook"

    env = os.environ.copy()
    env["AGENTFORGE_HOOK_STAGE"] = stage
    env["AGENTFORGE_PHASE_ROLE"] = role

    try:
        proc = await asyncio.create_subprocess_exec(
            str(hook),
            cwd=str(code_root if code_root.is_dir() else hook.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except OSError as e:
        return "fail", f"could not launch {stage} hook {hook}: {e}"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "fail", f"{stage} hook timed out after {timeout:.0f}s"

    text = out.decode(errors="replace")
    if len(text) > 4000:
        text = text[-4000:]
    code = proc.returncode if proc.returncode is not None else 1
    return ("ok" if code == 0 else "fail"), text
