"""Integration test for the debug preset against a fixture repo with a known failing test.

Closes the A4 gap from feedback.md Part 3 (#1): the debug/fix presets existed but had no
integration test on a real repo with a failing test. This exercises the deploy *verify*
step — the same one the debug preset's final QA phase relies on — end to end:

1. the committed broken repo (`add` subtracts) makes `pytest` fail (reproduce),
2. patching the root cause makes the same verify pass (re-verify).

No LLM is involved: the patch stands in for the Backend phase so the loop is deterministic.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import deploy
from core.phases import PHASE_PRESETS
from core.profile import load_profile

FIXTURE = Path(__file__).parent / "fixtures" / "broken_calc"


def test_debug_preset_phase_order():
    """The debug preset is the reproduce -> patch -> re-verify loop (qa, backend, qa)."""
    roles = [role for role, _ in PHASE_PRESETS["debug"]]
    assert roles == ["qa", "backend", "qa"]


def test_profile_loads_verify_cmd_from_target_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    profile = load_profile(repo, repo / ".agentforge")
    assert profile.verify_cmd == ["pytest", "-q"]


@pytest.mark.asyncio
async def test_debug_loop_reproduces_then_fixes(tmp_path: Path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    profile = load_profile(repo, repo / ".agentforge")

    # Reproduce: the known bug makes the verify command fail.
    status, detail = await deploy.run_verify(repo, profile.verify_cmd)
    assert status == "fail"
    assert "test_add" in detail

    # Patch the root cause (stands in for the Backend phase).
    calc = repo / "calc.py"
    calc.write_text(calc.read_text().replace("return a - b  # BUG: should be a + b", "return a + b"))

    # Re-verify: the same command now passes.
    status, detail = await deploy.run_verify(repo, profile.verify_cmd)
    assert status == "pass", detail
