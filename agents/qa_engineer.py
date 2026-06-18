from __future__ import annotations

import asyncio
import importlib.util
import sys

from core import artifact_quality
from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from core.context import condense_markdown
from core.paths import WORKSPACE, METADATA_ROOT
from core.profile import Profile, load_profile
from .base_agent import BaseAgent

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a test file or QA report to the project",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the code root"},
                "content": {"type": "string", "description": "Complete file content"},
            },
            "required": ["path", "content"],
        },
    },
]

_QA_FILES = [
    "dailyease/tests/__init__.py",
    "dailyease/tests/conftest.py",
    "dailyease/tests/test_tasks.py",
    "dailyease/tests/test_habits.py",
    "dailyease/tests/test_finance.py",
    "dailyease/tests/test_wellness.py",
    "reports/qa_report.md",
]


def qa_files(profile: Profile) -> list[str]:
    """Return the fixed DailyEase test checklist only for the greenfield default profile."""
    return list(_QA_FILES) if profile.app_root == "dailyease" else []


def build_qa_prompt(profile: Profile, *, sprint_goal: str, impl_summary: str,
                    code_excerpts: str, task_description: str) -> str:
    """Construct the QA prompt, profile-driven.

    DailyEase default keeps the fixed test-file checklist; other profiles instruct the agent to
    read existing code/tests first and write tests under ``profile.app_root``.
    """
    if profile.app_root == "dailyease":
        files = qa_files(profile)
        return (
            f"Write a complete pytest test suite for DailyEase and a QA report.\n\n"
            f"Sprint goal (context): {sprint_goal}\n\n"
            f"Implementation files available:\n{impl_summary}\n\n"
            f"{code_excerpts}"
            f"Task: {task_description}\n\n"
            f"Write ALL of these files using write_file:\n"
            + "\n".join(f"- {f}" for f in files)
            + "\n\nTests must use pytest + httpx.AsyncClient + pytest-asyncio. "
            f"conftest.py must set up an async test database (SQLite in-memory). "
            f"Write at least 5 tests per module (CRUD + edge cases). "
            f"QA report must include: executive summary, test coverage matrix, bugs found, recommendations."
        )

    stack = ", ".join(profile.stack) if profile.stack else "the project's existing stack"
    verify = " ".join(profile.verify_cmd)
    return (
        f"Verify the change in the existing {profile.name} project and report on it.\n\n"
        f"Sprint goal (context): {sprint_goal}\n\n"
        f"Implementation files available:\n{impl_summary}\n\n"
        f"{code_excerpts}"
        f"Task: {task_description}\n\n"
        f"First, read the existing code and tests: use read_file/list_files/grep_code to find the "
        f"relevant modules and the existing test layout/conventions before writing anything. "
        f"Reproduce the reported behavior where applicable, then add or update tests under "
        f"{profile.app_root}/ using write_file, matching the existing style and {stack}. "
        f"The suite is verified with `{verify}`. "
        f"Write a QA report to reports/qa_report.md covering: summary, what was reproduced/verified, "
        f"bugs found, and recommendations."
    )


class QAEngineerAgent(BaseAgent):
    async def run(self) -> None:
        while True:
            msg = await self.bus.receive(self.role)
            if msg is None:
                continue
            if msg.type == MessageType.SHUTDOWN:
                break
            if msg.type == MessageType.TASK_ASSIGN:
                await self._handle_task(msg)

    def _local_top_level(self, profile: Profile) -> set[str]:
        """Top-level module/package names that belong to the project itself.

        These are legitimately importable (the app package and its siblings), so they must not be
        flagged as phantom. Collected from the code root and the app root.
        """
        ws = self.artifacts.WORKSPACE
        names: set[str] = {profile.app_root.replace("\\", "/").split("/", 1)[0]}
        for base in {ws, ws / profile.app_root}:
            if not base.is_dir():
                continue
            for entry in base.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    names.add(entry.name)
                elif entry.suffix == ".py":
                    names.add(entry.stem)
        names.discard("")
        return names

    async def _scan_phantom_imports(self, profile: Profile) -> dict[str, list[str]]:
        """Statically flag imports that are neither stdlib, installed, nor local modules.

        Catches hallucinated imports / phantom dependencies before a pytest run that would just
        fail at import time. Conservative: a module is only reported if it is not local and
        ``importlib.util.find_spec`` cannot locate it (i.e. it is genuinely not installed).
        """
        local = self._local_top_level(profile)
        ws = self.artifacts.WORKSPACE
        known = set(local)
        findings: dict[str, list[str]] = {}

        for path in self.artifacts.list_files(profile.app_root):
            if path.suffix != ".py":
                continue
            try:
                src = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            phantoms: list[str] = []
            for mod in sorted(artifact_quality.phantom_imports(src, known)):
                # find_spec only resolves the top-level name, so it never imports/executes
                # package code — a cheap, side-effect-free availability check.
                try:
                    available = importlib.util.find_spec(mod) is not None
                except (ImportError, ValueError):
                    available = False
                if available:
                    known.add(mod)  # cache so we don't re-resolve across files
                else:
                    phantoms.append(mod)
            if phantoms:
                try:
                    rel = str(path.relative_to(ws))
                except ValueError:
                    rel = str(path)
                findings[rel] = phantoms
        return findings

    async def _run_pytest(self) -> tuple[int, str]:
        root = self.artifacts.dailyease_root()
        if not root.is_dir():
            return 1, "dailyease/ not found under workspace. Run implement or full pipeline first."

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            proc.kill()
            return 124, "pytest timed out after 300s"

        text = out.decode(errors="replace")
        if len(text) > 12000:
            text = text[-12000:]
        code = proc.returncode if proc.returncode is not None else 1
        return code, text

    async def _handle_task(self, msg: Message) -> None:
        task = msg.payload
        self.console.log(f"[yellow]QA[/yellow] starting: {task.get('deliverable', '')}")

        profile = load_profile(WORKSPACE, METADATA_ROOT)

        impl_files = self.artifacts.list_files(profile.app_root)
        ws = self.artifacts.WORKSPACE
        rel_paths: list[str] = []
        for p in impl_files[:30]:
            try:
                rel_paths.append(str(p.relative_to(ws)))
            except ValueError:
                rel_paths.append(str(p))
        impl_summary = "\n".join(rel_paths)

        code_excerpts = ""
        if profile.app_root == "dailyease":
            main_content = await self.artifacts.read("dailyease/main.py")
            tasks_router = await self.artifacts.read("dailyease/routers/tasks.py")
            habits_router = await self.artifacts.read("dailyease/routers/habits.py")
            code_excerpts = (
                f"main.py:\n```python\n{main_content[:2000]}\n```\n\n"
                f"routers/tasks.py:\n```python\n{tasks_router[:2000]}\n```\n\n"
                f"routers/habits.py:\n```python\n{habits_router[:1500]}\n```\n\n"
            )

        context = await self._build_dynamic_context()
        sprint_goal = task.get("sprint_goal", "")

        user_msg = build_qa_prompt(
            profile,
            sprint_goal=sprint_goal,
            impl_summary=impl_summary,
            code_excerpts=code_excerpts,
            task_description=task["task_description"],
        )

        written_files = await self._generate_tests(user_msg, context)

        # Pre-pytest static check: catch hallucinated imports / phantom dependencies and route a
        # targeted fix before spending a full pytest run that would only ImportError (critique #1
        # follow-on; see improvement.md "phantom-import detection").
        phantom = await self._scan_phantom_imports(profile)
        if phantom:
            total = sum(len(v) for v in phantom.values())
            self.console.log(f"[yellow]QA[/yellow] {total} phantom import(s) detected before pytest")
            listing = "\n".join(f"- {f}: {', '.join(mods)}" for f, mods in phantom.items())
            fix_msg = (
                "A static import check found references to modules that are neither in the "
                "standard library, installed in this environment, nor local project modules — "
                "they will fail at import time, so fix them before tests run:\n"
                f"{listing}\n\n"
                "For each: correct the import to the real module/package name, or remove it if "
                "unused. Do not invent packages. Use write_file or edit_file to apply the fixes."
            )
            written_files.extend(await self._generate_tests(fix_msg, context))

        exit_code, pytest_out = await self._run_pytest()
        self.console.log(f"[yellow]QA[/yellow] pytest exit={exit_code}")

        if exit_code != 0:
            fix_msg = (
                f"pytest failed (exit {exit_code}). Fix the tests or implementation stubs.\n\n"
                f"```\n{pytest_out}\n```\n\n"
                f"Update tests using write_file. Ensure imports match the actual app package layout."
            )
            written_files.extend(await self._generate_tests(fix_msg, context))
            exit_code2, pytest_out2 = await self._run_pytest()
            self.console.log(f"[yellow]QA[/yellow] pytest after fix exit={exit_code2}")
            if exit_code2 != 0:
                appendix = (
                    f"\n\n## Pytest output (last run)\n\n```\n{pytest_out2[:6000]}\n```\n"
                )
                report_path = "reports/qa_report.md"
                existing = await self.artifacts.read(report_path)
                if not existing.startswith("["):
                    await self.artifacts.write(report_path, existing + appendix)

        primary_path = "reports/qa_report.md"

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"Test suite + QA report ({len(written_files)} files); pytest logged in report",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        async def _revise_cb(notes: str) -> None:
            await self._revise(notes, msg, primary_path)

        await self._await_reviews("QA", _revise_cb)

    async def _generate_tests(self, user_message: str, context: str) -> list[str]:
        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
            self.console.log(f"[yellow]QA[/yellow] wrote: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=user_message,
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=24,
            read_tools=True,
            edit_tools=True,
        )
        for edited in self._edited_files:
            if edited not in written_files:
                written_files.append(edited)
        return written_files

    async def _revise(self, notes: str, original_msg: Message, primary_path: str) -> None:
        report = await self.artifacts.read(primary_path)
        context = await self._build_dynamic_context()
        _, pytest_out = await self._run_pytest()

        user_message = (
                f"Revise tests and QA report per Lead feedback:\n{notes}\n\n"
            f"Current QA report:\n```markdown\n{condense_markdown(report, 4500, ['bug', 'coverage', 'fail', 'test', 'recommendation'])}\n```\n\n"
            f"Latest pytest output:\n```\n{pytest_out[:6000]}\n```\n\n"
            f"Apply write_file to any files that need changes."
        )
        written_files = await self._generate_tests(user_message, context)

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": "Revised QA artifacts",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
