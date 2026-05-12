from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from .base_agent import BaseAgent

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a DevOps configuration file to the workspace",
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

_DEVOPS_FILES = [
    "dailyease/Dockerfile",
    "dailyease/docker-compose.yml",
    "dailyease/.dockerignore",
    "dailyease/.github/workflows/ci.yml",
    "docs/deployment.md",
]


class DevOpsEngineerAgent(BaseAgent):
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
        self.console.log(f"[red]DevOps[/red] starting: {task.get('deliverable', '')}")

        # Load QA report to confirm quality gate was passed
        qa_report = await self.artifacts.read("reports/qa_report.md")
        arch_doc = await self.artifacts.read("docs/architecture.md")

        context = await self._build_dynamic_context()
        sprint_goal = task.get("sprint_goal", "")

        response = await self._call_llm(
            user_message=(
                f"Write production deployment configuration for DailyEase.\n\n"
                f"Sprint goal (context): {sprint_goal}\n\n"
                f"Architecture Summary:\n```markdown\n{arch_doc[:2000]}\n```\n\n"
                f"QA Report:\n```markdown\n{qa_report[:1500]}\n```\n\n"
                f"Task: {task['task_description']}\n\n"
                f"Write ALL of these files using write_file:\n"
                + "\n".join(f"- {f}" for f in _DEVOPS_FILES)
                + "\n\nRequirements:\n"
                f"- Dockerfile: multi-stage build, non-root user, HEALTHCHECK instruction\n"
                f"- docker-compose.yml: app + volume for SQLite persistence + health check\n"
                f"- CI workflow: lint (ruff) + type check (mypy) + pytest + docker build + push to ghcr.io\n"
                f"- deployment.md: complete runbook (local dev, staging, production)"
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
                self.console.log(f"[red]DevOps[/red] wrote: {full_path}")

        primary_path = "docs/deployment.md"

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"Deployment configs written ({len(written_files)} files)",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        approval_msg = await self.bus.receive(self.role, timeout=120.0)
        if approval_msg and approval_msg.type == MessageType.ARTIFACT_REJECTED:
            notes = approval_msg.payload.get("revision_notes", "")
            self.console.log(f"[yellow]DevOps[/yellow] revisions: {notes}")
            await self._revise(notes, msg, task)
        else:
            self.console.log("[red]DevOps[/red] deployment configs approved ✓")

    async def _revise(self, notes: str, original_msg: Message, task: dict) -> None:
        qa_report = await self.artifacts.read("reports/qa_report.md")
        arch_doc = await self.artifacts.read("docs/architecture.md")
        context = await self._build_dynamic_context()

        response = await self._call_llm(
            user_message=(
                f"Revise deployment configs per feedback:\n{notes}\n\n"
                f"Task: {task.get('task_description', '')}\n\n"
                f"Architecture:\n```markdown\n{arch_doc[:2500]}\n```\n\n"
                f"QA Report:\n```markdown\n{qa_report[:2000]}\n```\n\n"
                f"Rewrite affected files using write_file."
            ),
            dynamic_context=context,
            tools=_TOOLS,
        )

        written_files: list[str] = []
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
                "primary_path": "docs/deployment.md",
                "path": "docs/deployment.md",
                "summary": "Revised deployment configs",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
