"""Deploy-gate helpers: verification smoke test and a guarded git commit.

These back the Lead's finalize step (see agents/lead.py). Kept side-effecting work
(subprocess, git) here so the orchestration logic stays testable.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def _is_pytest_cmd(verify_cmd: list[str]) -> bool:
    """True for pytest-style verify commands (so we can skip when there are no tests)."""
    return bool(verify_cmd) and verify_cmd[0] == "pytest"


def build_commit_message(goal: str, *, scope: str = "agentforge") -> str:
    """Conventional-commit message for a deploy commit against the target repo.

    Uses the first non-empty line of the goal as the summary, e.g.
    ``chore(agentforge): Add health check endpoint``. Pure (no I/O) so it is unit-testable.
    """
    summary = ""
    for line in goal.splitlines():
        if line.strip():
            summary = line.strip()
            break
    summary = summary or "sprint"
    if len(summary) > 72:
        summary = summary[:69].rstrip() + "..."
    return f"chore({scope}): {summary}"


async def run_verify(
    code_root: Path,
    verify_cmd: list[str] | None = None,
    timeout: float = 180.0,
) -> tuple[str, str]:
    """Run the profile's verify command in ``code_root`` as a deploy smoke check.

    ``verify_cmd`` defaults to ``["pytest", "-q"]``. Returns ``(status, detail)`` where status is
    ``pass`` | ``fail`` | ``skipped``. For pytest-style commands a missing ``tests/`` directory is
    ``skipped`` (not a deploy failure); an unavailable executable is also ``skipped``; a non-zero
    exit or timeout is ``fail``. Output is capped to the last 4000 chars.
    """
    verify_cmd = list(verify_cmd) if verify_cmd else ["pytest", "-q"]
    if not code_root.is_dir():
        return "skipped", f"no code root to verify: {code_root}"

    pytest_style = _is_pytest_cmd(verify_cmd)
    if pytest_style and not (code_root / "tests").is_dir():
        return "skipped", "no tests/ directory to verify"

    # Run pytest via the current interpreter (-m pytest) so it works without a console script.
    if pytest_style:
        argv = [sys.executable, "-m", "pytest", *verify_cmd[1:]]
    else:
        argv = verify_cmd

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(code_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as e:
        return "skipped", f"could not launch verify command {verify_cmd!r}: {e}"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "fail", f"verify command timed out after {timeout:.0f}s"

    text = out.decode(errors="replace")
    if len(text) > 4000:
        text = text[-4000:]
    code = proc.returncode if proc.returncode is not None else 1
    return ("pass" if code == 0 else "fail"), text


async def run_pytest_smoke(dailyease_root: Path, timeout: float = 180.0) -> tuple[str, str]:
    """Run the generated app's pytest suite as a deploy smoke check (DailyEase default path).

    Thin wrapper over :func:`run_verify` with the pytest verify command, preserved for the Lead's
    default path and existing tests. Returns ``(status, detail)`` with status
    ``pass`` | ``fail`` | ``skipped``.
    """
    if not dailyease_root.is_dir():
        return "skipped", "no dailyease/ workspace to verify"
    return await run_verify(dailyease_root, ["pytest", "-q", "--tb=line"], timeout=timeout)


async def git_commit_dir(target: Path, message: str, branch: str | None = None) -> tuple[bool, str]:
    """Commit everything under ``target`` to a git repo scoped to that directory.

    Initializes a repo there if one does not exist. When ``branch`` is given, create/checkout that
    branch before committing (for a PR workflow). Returns ``(ok, info)`` where info is the short SHA
    on success or an error/"nothing to commit" message.
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

    if branch:
        # Checkout the branch if it exists, else create it.
        code, _ = await run("rev-parse", "--verify", branch)
        code, msg = await run("checkout", branch) if code == 0 else await run("checkout", "-b", branch)
        if code != 0:
            return False, f"git checkout {branch} failed: {msg}"

    await run("add", "-A")
    code, msg = await run("commit", "-m", message)
    if code != 0:
        return False, msg or "nothing to commit"
    code, sha = await run("rev-parse", "--short", "HEAD")
    return True, (sha if code == 0 else "committed")
