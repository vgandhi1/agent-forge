"""Deploy-gate helpers: verification smoke test and a guarded git commit.

These back the Lead's finalize step (see agents/lead.py). Kept side-effecting work
(subprocess, git) here so the orchestration logic stays testable.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def run_pytest_smoke(dailyease_root: Path, timeout: float = 180.0) -> tuple[str, str]:
    """Run the generated app's test suite as a deploy smoke check.

    Returns ``(status, detail)`` where status is ``pass`` | ``fail`` | ``skipped``.
    Missing tests or an unavailable pytest are ``skipped`` (not a deploy failure);
    a non-zero exit or timeout is ``fail``.
    """
    if not dailyease_root.is_dir():
        return "skipped", "no dailyease/ workspace to verify"
    if not (dailyease_root / "tests").is_dir():
        return "skipped", "no tests/ directory in workspace"

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pytest", "-q", "--tb=line",
            cwd=str(dailyease_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as e:
        return "skipped", f"could not launch pytest: {e}"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "fail", f"pytest timed out after {timeout:.0f}s"

    text = out.decode(errors="replace")
    if len(text) > 4000:
        text = text[-4000:]
    code = proc.returncode if proc.returncode is not None else 1
    return ("pass" if code == 0 else "fail"), text


async def git_commit_dir(target: Path, message: str) -> tuple[bool, str]:
    """Commit everything under ``target`` to a git repo scoped to that directory.

    Initializes a repo there if one does not exist (the generated workspace is build
    output, so this never touches the AgentForge repo). Returns ``(ok, info)`` where
    info is the short SHA on success or an error/"nothing to commit" message.
    """
    if not target.is_dir():
        return False, f"target not found: {target}"

    async def run(*args: str) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args, cwd=str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as e:
            return 127, f"git unavailable: {e}"
        out, _ = await proc.communicate()
        return (proc.returncode if proc.returncode is not None else 1), out.decode(errors="replace").strip()

    code, msg = await run("rev-parse", "--is-inside-work-tree")
    if code == 127:
        return False, msg
    if code != 0:
        code, msg = await run("init")
        if code != 0:
            return False, f"git init failed: {msg}"

    await run("add", "-A")
    code, msg = await run("commit", "-m", message)
    if code != 0:
        return False, msg or "nothing to commit"
    code, sha = await run("rev-parse", "--short", "HEAD")
    return True, (sha if code == 0 else "committed")
