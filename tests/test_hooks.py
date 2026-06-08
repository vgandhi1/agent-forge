"""Tests for optional per-phase guardrail hooks (core/hooks.py)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from core import hooks


def _write_hook(hooks_dir: Path, stage: str, body: str) -> Path:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    path = hooks_dir / stage
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.mark.asyncio
async def test_no_hook_is_skipped(tmp_path: Path):
    status, detail = await hooks.run_phase_hook(
        "pre-phase", "backend", metadata_root=tmp_path / "meta", code_root=tmp_path
    )
    assert status == "skipped"


@pytest.mark.asyncio
async def test_unknown_stage_is_skipped(tmp_path: Path):
    status, _ = await hooks.run_phase_hook(
        "mid-phase", "backend", metadata_root=tmp_path, code_root=tmp_path
    )
    assert status == "skipped"


@pytest.mark.asyncio
async def test_pre_phase_hook_runs_and_sees_env(tmp_path: Path):
    meta = tmp_path / "meta"
    out = tmp_path / "marker.txt"
    _write_hook(
        meta / "hooks",
        "pre-phase",
        f'#!/bin/sh\necho "$AGENTFORGE_HOOK_STAGE $AGENTFORGE_PHASE_ROLE" > "{out}"\nexit 0\n',
    )
    status, _ = await hooks.run_phase_hook(
        "pre-phase", "qa", metadata_root=meta, code_root=tmp_path
    )
    assert status == "ok"
    assert out.read_text().strip() == "pre-phase qa"


@pytest.mark.asyncio
async def test_failing_hook_reports_fail(tmp_path: Path):
    meta = tmp_path / "meta"
    _write_hook(meta / "hooks", "post-phase", "#!/bin/sh\necho boom\nexit 3\n")
    status, detail = await hooks.run_phase_hook(
        "post-phase", "backend", metadata_root=meta, code_root=tmp_path
    )
    assert status == "fail"
    assert "boom" in detail


@pytest.mark.asyncio
async def test_non_executable_hook_is_skipped(tmp_path: Path):
    meta = tmp_path / "meta"
    (meta / "hooks").mkdir(parents=True)
    path = meta / "hooks" / "pre-phase"
    path.write_text("#!/bin/sh\nexit 0\n")  # not chmod +x
    # Sanity: ensure it is genuinely non-executable before asserting skip.
    assert not os.access(path, os.X_OK)
    status, _ = await hooks.run_phase_hook(
        "pre-phase", "qa", metadata_root=meta, code_root=tmp_path
    )
    assert status == "skipped"


@pytest.mark.asyncio
async def test_code_root_agentforge_hook_is_found(tmp_path: Path):
    code_root = tmp_path / "repo"
    out = tmp_path / "ran.txt"
    _write_hook(
        code_root / ".agentforge" / "hooks",
        "pre-phase",
        f'#!/bin/sh\necho ran > "{out}"\nexit 0\n',
    )
    status, _ = await hooks.run_phase_hook(
        "pre-phase", "backend", metadata_root=tmp_path / "missing", code_root=code_root
    )
    assert status == "ok"
    assert out.read_text().strip() == "ran"
