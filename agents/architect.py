from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from core.context import condense_markdown
from .base_agent import BaseAgent

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a document or code file to the workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace/"},
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["path", "content"],
        },
    },
]


class ArchitectAgent(BaseAgent):
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
        self.console.log(f"[magenta]Architect[/magenta] starting: {task.get('deliverable', '')}")

        # Load requirements doc to base architecture on
        approved_artifacts = task.get("approved_artifacts", {})
        req_path = approved_artifacts.get("pm_artifact", "docs/requirements.md")
        requirements_content = await self.artifacts.read(req_path)

        context = await self._build_dynamic_context()

        sprint_goal = task.get("sprint_goal", "")

        written_files: list[str] = []
        primary_path = "docs/architecture.md"

        async def write_file_handler(tool_input: dict) -> str:
            nonlocal primary_path
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            if "architecture" in path:
                primary_path = path
            await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
            self.console.log(f"[magenta]Architect[/magenta] wrote: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        result = await self.run_tool_loop(
            user_message=(
                f"Design the complete system architecture for DailyEase.\n\n"
                f"Sprint goal (context): {sprint_goal}\n\n"
                f"Requirements Document:\n```markdown\n{condense_markdown(requirements_content, 8000, ['task', 'habit', 'finance', 'wellness', 'api', 'requirement', 'user story', 'nfr'])}\n```\n\n"
                f"Task: {task['task_description']}\n\n"
                f"Save to docs/architecture.md using write_file. Include ALL required sections: "
                f"system overview, tech stack, database schema, app structure, API design, "
                f"data flow, security design, scalability considerations."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=8,
        )

        if not written_files:
            fallback = result["final_text"]
            full_path = await self.artifacts.write(primary_path, fallback or "# Architecture\n\n[Generated]")
            written_files.append(str(full_path))

        await self.memory.remember("architecture_path", primary_path, "artifact_ref")

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"Architecture document written ({len(written_files)} files)",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        async def _revise_cb(notes: str) -> None:
            await self._revise(primary_path, notes, msg)

        await self._await_reviews("Architect", _revise_cb)

    async def _revise(self, original_path: str, notes: str, original_msg: Message) -> None:
        original_content = await self.artifacts.read(original_path)
        context = await self._build_dynamic_context()

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            full_path = await self.artifacts.write(tool_input["path"], tool_input["content"])
            written_files.append(str(full_path))
            return f"Wrote {tool_input['path']} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=(
                f"Revise the architecture document:\n{notes}\n\n"
                f"Original:\n```\n{original_content}\n```\n\nUse write_file."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=8,
        )

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": original_path,
                "path": original_path,
                "summary": "Revised architecture document",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
