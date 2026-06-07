from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from core.context import condense_markdown
from .base_agent import BaseAgent

_PREFER = ["deploy", "docker", "ci", "scale", "security", "database", "api", "health", "performance"]

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

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
            self.console.log(f"[red]DevOps[/red] wrote: {full_path}")
            remaining = [f for f in _DEVOPS_FILES if not any(f in w for w in written_files)]
            hint = f" Remaining: {', '.join(remaining)}" if remaining else " All files written."
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes).{hint}"

        await self.run_tool_loop(
            user_message=(
                f"Write production deployment configuration for DailyEase.\n\n"
                f"Sprint goal (context): {sprint_goal}\n\n"
                f"Architecture Summary:\n```markdown\n{condense_markdown(arch_doc, 3500, _PREFER)}\n```\n\n"
                f"QA Report:\n```markdown\n{condense_markdown(qa_report, 2500, _PREFER)}\n```\n\n"
                f"Task: {task['task_description']}\n\n"
                f"Write ALL of these files using write_file — one call per file, "
                f"continuing across turns until all are written:\n"
                + "\n".join(f"- {f}" for f in _DEVOPS_FILES)
                + "\n\nRequirements:\n"
                f"- Dockerfile: multi-stage build, non-root user, HEALTHCHECK instruction\n"
                f"- docker-compose.yml: app + volume for SQLite persistence + health check\n"
                f"- CI workflow: lint (ruff) + type check (mypy) + pytest + docker build + push to ghcr.io\n"
                f"- deployment.md: complete runbook (local dev, staging, production)\n"
                f"Reply without a tool call only when all files are written."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=20,
        )

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

        async def _revise_cb(notes: str) -> None:
            await self._revise(notes, msg, task)

        await self._await_reviews("DevOps", _revise_cb)

    async def _revise(self, notes: str, original_msg: Message, task: dict) -> None:
        qa_report = await self.artifacts.read("reports/qa_report.md")
        arch_doc = await self.artifacts.read("docs/architecture.md")
        context = await self._build_dynamic_context()

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            self.console.log(f"[red]DevOps[/red] revised: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=(
                f"Revise deployment configs per feedback:\n{notes}\n\n"
                f"Task: {task.get('task_description', '')}\n\n"
                f"Architecture:\n```markdown\n{condense_markdown(arch_doc, 3000, _PREFER)}\n```\n\n"
                f"QA Report:\n```markdown\n{condense_markdown(qa_report, 2500, _PREFER)}\n```\n\n"
                f"Rewrite affected files using write_file. "
                f"Reply without a tool call only when all fixes are written."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=20,
        )

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
