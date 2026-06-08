"""Tests for profile-driven deploy verification and the conventional-commit helper (roadmap A5)."""
import asyncio
import sys

import pytest

from core import deploy


# --------------------------------------------------------------------------- run_verify


@pytest.mark.asyncio
async def test_run_verify_pass_on_trivial_command(tmp_path) -> None:
    status, detail = await deploy.run_verify(tmp_path, [sys.executable, "-c", "pass"])
    assert status == "pass", detail


@pytest.mark.asyncio
async def test_run_verify_fail_on_failing_command(tmp_path) -> None:
    status, detail = await deploy.run_verify(tmp_path, [sys.executable, "-c", "import sys; sys.exit(1)"])
    assert status == "fail"


@pytest.mark.asyncio
async def test_run_verify_skips_pytest_without_tests_dir(tmp_path) -> None:
    # pytest-style command but no tests/ directory → skipped (not a deploy failure)
    status, detail = await deploy.run_verify(tmp_path, ["pytest", "-q"])
    assert status == "skipped"
    assert "tests/" in detail


@pytest.mark.asyncio
async def test_run_verify_skips_missing_code_root(tmp_path) -> None:
    status, detail = await deploy.run_verify(tmp_path / "does-not-exist", ["pytest", "-q"])
    assert status == "skipped"


@pytest.mark.asyncio
async def test_run_verify_pass_on_pytest_dir(tmp_path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    status, detail = await deploy.run_verify(tmp_path, ["pytest", "-q"])
    assert status == "pass", detail


@pytest.mark.asyncio
async def test_run_verify_fail_on_pytest_dir(tmp_path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    status, detail = await deploy.run_verify(tmp_path, ["pytest", "-q"])
    assert status == "fail"


@pytest.mark.asyncio
async def test_run_verify_defaults_to_pytest(tmp_path) -> None:
    # No verify_cmd → defaults to pytest-style, so missing tests/ → skipped
    status, _ = await deploy.run_verify(tmp_path)
    assert status == "skipped"


@pytest.mark.asyncio
async def test_run_verify_caps_output(tmp_path) -> None:
    big = "print('x' * 100)\n" * 200
    script = tmp_path / "noise.py"
    script.write_text(big, encoding="utf-8")
    status, detail = await deploy.run_verify(tmp_path, [sys.executable, str(script)])
    assert status == "pass"
    assert len(detail) <= 4000


# --------------------------------------------------------------- run_pytest_smoke delegation


@pytest.mark.asyncio
async def test_pytest_smoke_still_skips_without_workspace(tmp_path) -> None:
    status, detail = await deploy.run_pytest_smoke(tmp_path / "missing")
    assert status == "skipped"
    assert "dailyease" in detail


@pytest.mark.asyncio
async def test_pytest_smoke_passes_with_tests(tmp_path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    status, _ = await deploy.run_pytest_smoke(tmp_path)
    assert status == "pass"


# --------------------------------------------------------------- build_commit_message


def test_commit_message_uses_first_goal_line() -> None:
    msg = deploy.build_commit_message("Add health check endpoint\n\nmore detail")
    assert msg == "chore(agentforge): Add health check endpoint"


def test_commit_message_skips_leading_blank_lines() -> None:
    msg = deploy.build_commit_message("\n\n  Fix N+1 query  \nrest")
    assert msg == "chore(agentforge): Fix N+1 query"


def test_commit_message_empty_goal_fallback() -> None:
    assert deploy.build_commit_message("   \n  ") == "chore(agentforge): sprint"


def test_commit_message_truncates_long_summary() -> None:
    long_goal = "x" * 200
    msg = deploy.build_commit_message(long_goal)
    assert msg.startswith("chore(agentforge): ")
    assert msg.endswith("...")
    # subject (after the prefix) is bounded
    assert len(msg) <= len("chore(agentforge): ") + 72


def test_commit_message_custom_scope() -> None:
    assert deploy.build_commit_message("Refactor", scope="api") == "chore(api): Refactor"


# --------------------------------------------------------------- git_commit_dir branch


def _git_available() -> bool:
    async def _check() -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "--version",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            return False
        await proc.communicate()
        return proc.returncode == 0

    return asyncio.run(_check())


@pytest.mark.skipif(not _git_available(), reason="git not available")
@pytest.mark.asyncio
async def test_git_commit_dir_creates_branch(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    # minimal git identity so commit succeeds in CI sandboxes
    async def git(*args):
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(repo),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        return proc.returncode

    await git("init")
    await git("config", "user.email", "t@example.com")
    await git("config", "user.name", "Test")
    (repo / "file.txt").write_text("hi", encoding="utf-8")

    ok, info = await deploy.git_commit_dir(repo, "chore(agentforge): test", branch="agentforge/work")
    assert ok, info

    # verify the branch was created/checked out
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--abbrev-ref", "HEAD", cwd=str(repo),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    assert out.decode().strip() == "agentforge/work"
