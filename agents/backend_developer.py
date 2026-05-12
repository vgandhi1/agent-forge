from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from .base_agent import BaseAgent

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a Python source file to the DailyEase workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to workspace/, e.g. dailyease/main.py or dailyease/routers/tasks.py",
                },
                "content": {"type": "string", "description": "Complete file content — no truncation"},
            },
            "required": ["path", "content"],
        },
    },
]

_REQUIRED_FILES = [
    "dailyease/main.py",
    "dailyease/database.py",
    "dailyease/requirements.txt",
    "dailyease/models/__init__.py",
    "dailyease/schemas/__init__.py",
    "dailyease/routers/__init__.py",
    "dailyease/services/__init__.py",
    "dailyease/models/task.py",
    "dailyease/models/habit.py",
    "dailyease/models/finance.py",
    "dailyease/models/wellness.py",
    "dailyease/schemas/task.py",
    "dailyease/schemas/habit.py",
    "dailyease/schemas/finance.py",
    "dailyease/schemas/wellness.py",
    "dailyease/routers/tasks.py",
    "dailyease/routers/habits.py",
    "dailyease/routers/finance.py",
    "dailyease/routers/wellness.py",
    "dailyease/services/task_service.py",
    "dailyease/services/habit_service.py",
    "dailyease/services/finance_service.py",
    "dailyease/services/wellness_service.py",
]


class BackendDeveloperAgent(BaseAgent):
    async def run(self) -> None:
        while True:
            msg = await self.bus.receive(self.role)
            if msg is None:
                continue
            if msg.type == MessageType.SHUTDOWN:
                break
            if msg.type == MessageType.TASK_ASSIGN:
                await self._handle_task(msg)

    async def _handle_task(self, msg: Message) -> None:
        task = msg.payload
        self.console.log(f"[green]Backend[/green] starting: {task.get('deliverable', '')}")

        approved_artifacts = task.get("approved_artifacts", {})
        arch_path = approved_artifacts.get("architect_artifact", "docs/architecture.md")
        req_path = approved_artifacts.get("pm_artifact", "docs/requirements.md")

        arch_content = await self.artifacts.read(arch_path)
        req_content = await self.artifacts.read(req_path)

        context = await self._build_dynamic_context()

        sprint_goal = task.get("sprint_goal", "")

        response = await self._call_llm(
            user_message=(
                f"Implement the complete DailyEase FastAPI application.\n\n"
                f"Sprint goal (context): {sprint_goal}\n\n"
                f"Architecture Document:\n```markdown\n{arch_content[:4000]}\n```\n\n"
                f"Requirements Summary:\n```markdown\n{req_content[:2000]}\n```\n\n"
                f"Task: {task['task_description']}\n\n"
                f"Write ALL of these files using write_file (one call per file):\n"
                + "\n".join(f"- {f}" for f in _REQUIRED_FILES)
                + "\n\nEvery file must be complete and functional. "
                f"Use SQLAlchemy 2.x async + aiosqlite + FastAPI + Pydantic v2. "
                f"Include proper error handling in all routers."
            ),
            dynamic_context=context,
            tools=_TOOLS,
        )

        written_files: list[str] = []
        for tool_name, tool_input in self._extract_tool_calls(response):
            if tool_name == "write_file":
                full_path = await self.artifacts.write(tool_input["path"], tool_input["content"])
                written_files.append(str(full_path))
                await self.memory.remember(f"wrote_{tool_input['path']}", str(full_path), "artifact_ref")
                self.console.log(f"[green]Backend[/green] wrote: {full_path}")

        primary_path = "dailyease/main.py"

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"DailyEase FastAPI app implemented ({len(written_files)} files)",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        approval_msg = await self.bus.receive(self.role, timeout=120.0)
        if approval_msg and approval_msg.type == MessageType.ARTIFACT_REJECTED:
            notes = approval_msg.payload.get("revision_notes", "")
            self.console.log(f"[yellow]Backend[/yellow] revisions: {notes}")
            await self._revise(notes, msg, written_files)
        else:
            self.console.log("[green]Backend[/green] implementation approved ✓")

    async def _revise(self, notes: str, original_msg: Message, prior_files: list[str]) -> None:
        context = await self._build_dynamic_context()
        files_summary = "\n".join(prior_files[:10])

        response = await self._call_llm(
            user_message=(
                f"Revise the implementation based on this feedback:\n{notes}\n\n"
                f"Files already written:\n{files_summary}\n\n"
                f"Write corrected files using write_file."
            ),
            dynamic_context=context,
            tools=_TOOLS,
        )

        written_files = []
        for tool_name, tool_input in self._extract_tool_calls(response):
            if tool_name == "write_file":
                full_path = await self.artifacts.write(tool_input["path"], tool_input["content"])
                written_files.append(str(full_path))

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": "dailyease/main.py",
                "path": "dailyease/main.py",
                "summary": f"Revised implementation ({len(written_files)} files updated)",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
