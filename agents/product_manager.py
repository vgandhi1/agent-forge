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

        response = await self._call_llm(
            user_message=(
                f"Write the complete DailyEase requirements document.\n\n"
                f"Sprint Goal: {sprint_goal}\n\n"
                f"Task: {task['task_description']}\n\n"
                f"Save it to docs/requirements.md using the write_file tool.\n"
                f"Include all required sections: executive summary, personas, problem statement, "
                f"feature specs for all 4 modules, user stories, API overview, NFRs, out of scope."
            ),
            dynamic_context=context,
            tools=[_WRITE_FILE_TOOL],
        )

        written_files: list[str] = []
        primary_path = "docs/requirements.md"

        for tool_name, tool_input in self._extract_tool_calls(response):
            if tool_name == "write_file":
                path = tool_input["path"]
                full_path = await self.artifacts.write(path, tool_input["content"])
                written_files.append(str(full_path))
                if "requirements" in path:
                    primary_path = path
                await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
                self.console.log(f"[blue]PM[/blue] wrote: {full_path}")

        # Ensure file exists even if Claude didn't use the tool
        if not written_files:
            fallback = self._extract_text(response)
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

        # Wait for approval/rejection
        approval_msg = await self.bus.receive(self.role, timeout=120.0)
        if approval_msg and approval_msg.type == MessageType.ARTIFACT_APPROVED:
            self.console.log("[blue]PM[/blue] requirements approved ✓")
        elif approval_msg and approval_msg.type == MessageType.ARTIFACT_REJECTED:
            notes = approval_msg.payload.get("revision_notes", "")
            self.console.log(f"[yellow]PM[/yellow] revisions requested: {notes}")
            await self._revise_artifact(primary_path, notes, msg)

    async def _revise_artifact(self, original_path: str, revision_notes: str, original_msg: Message) -> None:
        original_content = await self.artifacts.read(original_path)
        context = await self._build_dynamic_context()

        response = await self._call_llm(
            user_message=(
                f"Revise the requirements document based on these notes:\n{revision_notes}\n\n"
                f"Original content:\n```\n{original_content}\n```\n\n"
                f"Write the revised document using write_file."
            ),
            dynamic_context=context,
            tools=[_WRITE_FILE_TOOL],
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
                "primary_path": original_path,
                "path": original_path,
                "summary": "Revised requirements document",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
