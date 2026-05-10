from __future__ import annotations

import asyncio
import sys

from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from .base_agent import BaseAgent

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a test file or QA report to the workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace/"},
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

        impl_files = self.artifacts.list_files("dailyease")
        ws = self.artifacts.WORKSPACE
        rel_paths: list[str] = []
        for p in impl_files[:30]:
            try:
                rel_paths.append(str(p.relative_to(ws)))
            except ValueError:
                rel_paths.append(str(p))
        impl_summary = "\n".join(rel_paths)

        main_content = await self.artifacts.read("dailyease/main.py")
        tasks_router = await self.artifacts.read("dailyease/routers/tasks.py")
        habits_router = await self.artifacts.read("dailyease/routers/habits.py")

        context = await self._build_dynamic_context()
        sprint_goal = task.get("sprint_goal", "")

        user_msg = (
            f"Write a complete pytest test suite for DailyEase and a QA report.\n\n"
            f"Sprint goal (context): {sprint_goal}\n\n"
            f"Implementation files available:\n{impl_summary}\n\n"
            f"main.py:\n```python\n{main_content[:2000]}\n```\n\n"
            f"routers/tasks.py:\n```python\n{tasks_router[:2000]}\n```\n\n"
            f"routers/habits.py:\n```python\n{habits_router[:1500]}\n```\n\n"
            f"Task: {task['task_description']}\n\n"
            f"Write ALL of these files using write_file:\n"
            + "\n".join(f"- {f}" for f in _QA_FILES)
            + "\n\nTests must use pytest + httpx.AsyncClient + pytest-asyncio. "
            f"conftest.py must set up an async test database (SQLite in-memory). "
            f"Write at least 5 tests per module (CRUD + edge cases). "
            f"QA report must include: executive summary, test coverage matrix, bugs found, recommendations."
        )

        written_files = await self._generate_tests(user_msg, context)

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
            recipient="ceo",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"Test suite + QA report ({len(written_files)} files); pytest logged in report",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        approval_msg = await self.bus.receive(self.role, timeout=120.0)
        if approval_msg and approval_msg.type == MessageType.ARTIFACT_REJECTED:
            notes = approval_msg.payload.get("revision_notes", "")
            self.console.log(f"[yellow]QA[/yellow] revisions: {notes}")
            await self._revise(notes, msg, primary_path)
        else:
            self.console.log("[yellow]QA[/yellow] test suite approved ✓")

    async def _generate_tests(self, user_message: str, context: str) -> list[str]:
        response = await self._call_claude(
            user_message=user_message,
            dynamic_context=context,
            tools=_TOOLS,
        )
        written_files: list[str] = []
        for tool_name, tool_input in self._extract_tool_calls(response):
            if tool_name == "write_file":
                full_path = await self.artifacts.write(tool_input["path"], tool_input["content"])
                written_files.append(str(full_path))
                await self.memory.remember(f"wrote_{tool_input['path']}", str(full_path), "artifact_ref")
                self.console.log(f"[yellow]QA[/yellow] wrote: {full_path}")
        return written_files

    async def _revise(self, notes: str, original_msg: Message, primary_path: str) -> None:
        report = await self.artifacts.read(primary_path)
        context = await self._build_dynamic_context()
        _, pytest_out = await self._run_pytest()

        user_message = (
            f"Revise tests and QA report per CEO feedback:\n{notes}\n\n"
            f"Current QA report:\n```markdown\n{report[:4000]}\n```\n\n"
            f"Latest pytest output:\n```\n{pytest_out[:6000]}\n```\n\n"
            f"Apply write_file to any files that need changes."
        )
        written_files = await self._generate_tests(user_message, context)

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="ceo",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": "Revised QA artifacts",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
