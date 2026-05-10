import asyncio
from rich.panel import Panel
from rich.text import Text

from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from core.phases import DEFAULT_PHASES
from .base_agent import BaseAgent

_DELEGATION_TOOLS = [
    {
        "name": "assign_task",
        "description": "Assign a specific task to one team member",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["pm", "architect", "backend", "qa", "devops"],
                    "description": "The agent to assign the task to",
                },
                "task_description": {
                    "type": "string",
                    "description": "Detailed description of what the agent must do and produce",
                },
                "deliverable": {
                    "type": "string",
                    "description": "The specific artifact or output expected",
                },
                "context_notes": {
                    "type": "string",
                    "description": "Any specific context, constraints, or prior decisions the agent should know",
                },
            },
            "required": ["agent", "task_description", "deliverable"],
        },
    },
    {
        "name": "approve_artifact",
        "description": "Approve a submitted artifact as meeting quality standards",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "artifact_name": {"type": "string"},
                "approval_notes": {
                    "type": "string",
                    "description": "What you approved and why it meets standards",
                },
            },
            "required": ["agent", "artifact_name", "approval_notes"],
        },
    },
    {
        "name": "reject_artifact",
        "description": "Reject an artifact and request specific revisions",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "artifact_name": {"type": "string"},
                "revision_notes": {
                    "type": "string",
                    "description": "Specific, actionable feedback on what must be changed",
                },
            },
            "required": ["agent", "artifact_name", "revision_notes"],
        },
    },
    {
        "name": "record_decision",
        "description": "Record an important strategic or technical decision",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision_key": {"type": "string", "description": "Short identifier for this decision"},
                "decision_value": {"type": "string", "description": "The decision and its rationale"},
            },
            "required": ["decision_key", "decision_value"],
        },
    },
]

class CEOAgent(BaseAgent):
    def __init__(self, role: str, bus: MessageBus, artifact_store: ArtifactStore, console) -> None:
        super().__init__(role, bus, artifact_store, console)
        self._approved_artifacts: dict[str, str] = {}

    async def run(self) -> None:
        pass  # CEO is driven by run_development_cycle, not the message loop

    async def run_development_cycle(
        self,
        goal: str,
        phases: list[tuple[str, str]] | None = None,
    ) -> None:
        phase_list = phases if phases is not None else DEFAULT_PHASES
        self.console.print(Panel(
            f"[bold]Sprint Goal:[/bold]\n{goal.strip()}",
            title="[bold cyan]AgentForge — Development Cycle Start[/bold cyan]",
            border_style="cyan",
        ))

        await self.memory.remember("sprint_goal", goal)

        for agent_role, phase_description in phase_list:
            await self._run_phase(agent_role, phase_description, goal)

        self.console.print(Panel(
            Text("All phases complete. Artifacts written to workspace/", style="bold green"),
            title="[bold green]Sprint Complete[/bold green]",
            border_style="green",
        ))

    async def _run_phase(self, agent_role: str, phase_description: str, goal: str) -> None:
        self.console.rule(f"[bold yellow]Phase: {agent_role.upper()}[/bold yellow]")

        context = await self._build_dynamic_context()
        context += f"\n\n## Sprint Goal\n{goal}"

        response = await self._call_claude(
            user_message=(
                f"Formulate a specific, detailed task for the {agent_role} agent.\n\n"
                f"Phase objective: {phase_description}\n\n"
                f"Use the assign_task tool to delegate. Include all context the agent needs to succeed.\n"
                f"Use record_decision to log any key choices you make."
            ),
            dynamic_context=context,
            tools=_DELEGATION_TOOLS,
        )

        task_payload: dict | None = None
        for tool_name, tool_input in self._extract_tool_calls(response):
            if tool_name == "assign_task":
                task_payload = tool_input
            elif tool_name == "record_decision":
                await self.memory.remember(
                    tool_input["decision_key"], tool_input["decision_value"], "decision"
                )

        if task_payload is None:
            task_payload = {
                "agent": agent_role,
                "task_description": phase_description,
                "deliverable": f"{agent_role} artifact",
            }

        task_payload["approved_artifacts"] = dict(self._approved_artifacts)
        task_payload["sprint_goal"] = goal

        self.console.log(f"[cyan]CEO → {agent_role}:[/cyan] {task_payload.get('deliverable', '')}")

        await self.bus.publish(Message(
            type=MessageType.TASK_ASSIGN,
            sender="ceo",
            recipient=agent_role,
            payload=task_payload,
            priority=1,
        ))

        max_revisions = 3
        revision = 0
        while revision < max_revisions:
            result_msg = await self.bus.receive("ceo", timeout=600.0)
            if result_msg is None:
                self.console.log(f"[red]Timeout waiting for {agent_role}[/red]")
                break

            if result_msg.type == MessageType.SHUTDOWN:
                break

            if result_msg.type != MessageType.TASK_COMPLETE:
                self.console.log(f"[yellow]Unexpected message type: {result_msg.type}[/yellow]")
                continue

            artifact = result_msg.payload
            approved = await self._review_artifact(agent_role, artifact, revision)

            if approved:
                artifact_key = f"{agent_role}_artifact"
                artifact_path = artifact.get("primary_path", artifact.get("path", ""))
                self._approved_artifacts[artifact_key] = artifact_path
                await self.memory.remember(artifact_key, artifact_path, "artifact_ref")
                self.console.log(f"[green]✓ {agent_role} artifact approved[/green]")
                break

            revision += 1
            if revision >= max_revisions:
                artifact_path = artifact.get("primary_path", artifact.get("path", ""))
                self._approved_artifacts[f"{agent_role}_artifact"] = artifact_path
                await self.memory.remember(f"{agent_role}_artifact", artifact_path, "artifact_ref")
                await self.bus.publish(Message(
                    type=MessageType.ARTIFACT_APPROVED,
                    sender="ceo",
                    recipient=agent_role,
                    payload={
                        "agent": agent_role,
                        "artifact_name": artifact_path,
                        "approval_notes": "Accepted after maximum revision cycles",
                    },
                    priority=1,
                ))
                self.console.log(f"[yellow]Accepted {agent_role} artifact after max revisions[/yellow]")
                break

            self.console.log(f"[yellow]Revision {revision} requested for {agent_role}[/yellow]")
            # Agent handles ARTIFACT_REJECTED and sends another TASK_COMPLETE; loop receives it

    async def _review_artifact(self, agent_role: str, artifact: dict, attempt: int) -> bool:
        artifact_path = artifact.get("primary_path", artifact.get("path", ""))
        files_written = artifact.get("files", [])
        summary = artifact.get("summary", "")

        self.console.log(f"[cyan]CEO reviewing {agent_role} artifact: {summary}[/cyan]")

        content_preview = ""
        if artifact_path:
            content_preview = await self.artifacts.read(artifact_path)
            content_preview = content_preview[:3000]

        context = await self._build_dynamic_context()

        review_prompt = (
            f"Review the {agent_role}'s submitted artifact (attempt {attempt + 1}).\n\n"
            f"Summary: {summary}\n"
            f"Files written: {files_written}\n\n"
            f"Artifact content preview:\n```\n{content_preview}\n```\n\n"
            f"Use approve_artifact if it meets the acceptance criteria, "
            f"or reject_artifact with specific revision notes if it needs improvement."
        )

        response = await self._call_claude(
            user_message=review_prompt,
            dynamic_context=context,
            tools=_DELEGATION_TOOLS,
        )

        approved = False
        tool_used = False
        calls = self._extract_tool_calls(response)
        reject_calls = [inp for name, inp in calls if name == "reject_artifact"]
        approve_calls = [inp for name, inp in calls if name == "approve_artifact"]

        for tool_name, tool_input in calls:
            if tool_name == "record_decision":
                await self.memory.remember(
                    tool_input["decision_key"], tool_input["decision_value"], "decision"
                )

        if reject_calls:
            approved = False
            tool_used = True
            await self.bus.publish(Message(
                type=MessageType.ARTIFACT_REJECTED,
                sender="ceo",
                recipient=agent_role,
                payload=reject_calls[-1],
                priority=1,
            ))
        elif approve_calls:
            approved = True
            tool_used = True
            await self.bus.publish(Message(
                type=MessageType.ARTIFACT_APPROVED,
                sender="ceo",
                recipient=agent_role,
                payload=approve_calls[-1],
                priority=1,
            ))

        if not tool_used:
            approved = True
            await self.bus.publish(Message(
                type=MessageType.ARTIFACT_APPROVED,
                sender="ceo",
                recipient=agent_role,
                payload={"agent": agent_role, "artifact_name": artifact_path, "approval_notes": "Accepted"},
                priority=1,
            ))

        return approved
