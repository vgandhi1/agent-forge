from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from .base_agent import BaseAgent

_WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": "Write a document or file to the workspace",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to workspace/, e.g. docs/requirements.md",
            },
            "content": {"type": "string", "description": "Full file content"},
        },
        "required": ["path", "content"],
    },
}


class ProductManagerAgent(BaseAgent):
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
        self.console.log(f"[blue]PM[/blue] starting: {task.get('deliverable', '')}")

        context = await self._build_dynamic_context()
        sprint_goal = task.get("sprint_goal") or (await self.memory.recall("sprint_goal") or "")

        written_files: list[str] = []
        primary_path = "docs/requirements.md"

        async def write_file_handler(tool_input: dict) -> str:
            nonlocal primary_path
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            if "requirements" in path:
                primary_path = path
            await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
            self.console.log(f"[blue]PM[/blue] wrote: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        result = await self.run_tool_loop(
            user_message=(
                f"Write the complete DailyEase requirements document.\n\n"
                f"Sprint Goal: {sprint_goal}\n\n"
                f"Task: {task['task_description']}\n\n"
                f"Save it to docs/requirements.md using the write_file tool.\n"
                f"Include all required sections: executive summary, personas, problem statement, "
                f"feature specs for all 4 modules, user stories, API overview, NFRs, out of scope."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=[_WRITE_FILE_TOOL],
            max_steps=8,
        )

        # Ensure file exists even if the model didn't use the tool
        if not written_files:
            fallback = result["final_text"]
            full_path = await self.artifacts.write(primary_path, fallback or "# Requirements\n\n[Generated]")
            written_files.append(str(full_path))

        await self.memory.remember("requirements_path", primary_path, "artifact_ref")

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"Requirements document written ({len(written_files)} files)",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        # Wait for the Lead's verdict(s); handle every revision cycle, not just the first.
        async def _revise(notes: str) -> None:
            await self._revise_artifact(primary_path, notes, msg)

        await self._await_reviews("PM", _revise)

    async def _revise_artifact(self, original_path: str, revision_notes: str, original_msg: Message) -> None:
        original_content = await self.artifacts.read(original_path)
        context = await self._build_dynamic_context()

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            full_path = await self.artifacts.write(tool_input["path"], tool_input["content"])
            written_files.append(str(full_path))
            return f"Wrote {tool_input['path']} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=(
                f"Revise the requirements document based on these notes:\n{revision_notes}\n\n"
                f"Original content:\n```\n{original_content}\n```\n\n"
                f"Write the revised document using write_file."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=[_WRITE_FILE_TOOL],
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
                "summary": "Revised requirements document",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
