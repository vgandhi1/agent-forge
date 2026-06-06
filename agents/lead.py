import logging
from rich.panel import Panel
from rich.text import Text

from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from core.phases import DEFAULT_PHASES
from .base_agent import BaseAgent
from .reviewer import ReviewerAgent

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

_lead_log = logging.getLogger("agentforge.lead")


class LeadAgent(BaseAgent):
    def __init__(self, role: str, bus: MessageBus, artifact_store: ArtifactStore, console) -> None:
        super().__init__(role, bus, artifact_store, console)
        self._approved_artifacts: dict[str, str] = {}
        # Independent reviewer consulted at the approval gate (see _review_artifact).
        self.reviewer = ReviewerAgent("reviewer", bus, artifact_store, console)
        self._current_brief: str = ""

    async def run(self) -> None:
        pass  # Lead is driven by run_development_cycle, not the message loop

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
        _lead_log.info("phase_start role=%s", agent_role)

        context = await self._build_dynamic_context()
        context += f"\n\n## Sprint Goal\n{goal}"

        response = await self._call_llm(
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
        self._current_brief = task_payload.get("task_description", phase_description)

        self.console.log(f"[cyan]Lead → {agent_role}:[/cyan] {task_payload.get('deliverable', '')}")

        await self.bus.publish(Message(
            type=MessageType.TASK_ASSIGN,
            sender="lead",
            recipient=agent_role,
            payload=task_payload,
            priority=1,
        ))

        max_revisions = 3
        revision = 0
        while revision < max_revisions:
            result_msg = await self.bus.receive("lead", timeout=600.0)
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
                # Flagged escalation, not a silent pass: accept to avoid deadlock, but record
                # that review findings are unresolved so the debt is visible downstream.
                debt_note = (
                    f"{agent_role} artifact accepted after {max_revisions} revision cycles with "
                    f"UNRESOLVED review findings — flagged for follow-up."
                )
                await self.memory.remember(f"quality_debt_{agent_role}", debt_note, "decision")
                _lead_log.warning("quality_debt role=%s path=%s", agent_role, artifact_path)
                await self.bus.publish(Message(
                    type=MessageType.ARTIFACT_APPROVED,
                    sender="lead",
                    recipient=agent_role,
                    payload={
                        "agent": agent_role,
                        "artifact_name": artifact_path,
                        "approval_notes": (
                            "ACCEPTED WITH UNRESOLVED REVIEW FINDINGS after max revision cycles "
                            "(flagged for follow-up)"
                        ),
                    },
                    priority=1,
                ))
                self.console.log(
                    f"[bold red][FLAGGED][/bold red] accepted {agent_role} artifact after max "
                    f"revisions with unresolved review findings"
                )
                break

            self.console.log(f"[yellow]Revision {revision} requested for {agent_role}[/yellow]")

    async def _review_artifact(self, agent_role: str, artifact: dict, attempt: int) -> bool:
        """Consult the independent Reviewer and act on its verdict.

        The Reviewer reads the actual files (not a truncated preview) and returns a
        structured decision. A missing verdict defaults to reject — silence is not approval.
        """
        artifact_path = artifact.get("primary_path", artifact.get("path", ""))
        files_written = artifact.get("files", []) or ([artifact_path] if artifact_path else [])
        summary = artifact.get("summary", "")

        self.console.log(
            f"[cyan]Reviewer auditing {agent_role} artifact (attempt {attempt + 1}): {summary}[/cyan]"
        )

        context = await self._build_dynamic_context()

        verdict = await self.reviewer.review(
            phase_role=agent_role,
            summary=summary,
            files=files_written,
            brief=self._current_brief,
            dynamic_context=context,
        )

        decision = verdict.get("decision", "reject")
        must_fix = verdict.get("must_fix") or []
        should_fix = verdict.get("should_fix") or []
        review_summary = verdict.get("summary", "")

        if decision == "approve":
            await self.bus.publish(Message(
                type=MessageType.ARTIFACT_APPROVED,
                sender="lead",
                recipient=agent_role,
                payload={
                    "agent": agent_role,
                    "artifact_name": artifact_path,
                    "approval_notes": review_summary or "Reviewer approved.",
                },
                priority=1,
            ))
            self.console.log(f"[green]Reviewer approved {agent_role} artifact[/green]")
            return True

        if decision == "escalate":
            question = verdict.get("escalation_question") or review_summary
            await self.memory.remember(f"escalation_{agent_role}", question, "decision")
            _lead_log.warning("review_escalation role=%s q=%s", agent_role, question)
            notes = f"ESCALATION (needs a product/business decision): {question}"
            if should_fix:
                notes += "\n\nShould fix:\n" + "\n".join(f"- {s}" for s in should_fix)
            await self.bus.publish(Message(
                type=MessageType.ARTIFACT_REJECTED,
                sender="lead",
                recipient=agent_role,
                payload={"agent": agent_role, "artifact_name": artifact_path, "revision_notes": notes},
                priority=1,
            ))
            self.console.log(f"[magenta]Reviewer escalated {agent_role} artifact[/magenta]")
            return False

        # decision == "reject" (or anything unrecognized → treat as reject)
        notes_parts: list[str] = []
        if must_fix:
            notes_parts.append("Must fix:\n" + "\n".join(f"- {m}" for m in must_fix))
        if should_fix:
            notes_parts.append("Should fix:\n" + "\n".join(f"- {s}" for s in should_fix))
        revision_notes = "\n\n".join(notes_parts) or review_summary or "Revisions required."
        await self.bus.publish(Message(
            type=MessageType.ARTIFACT_REJECTED,
            sender="lead",
            recipient=agent_role,
            payload={"agent": agent_role, "artifact_name": artifact_path, "revision_notes": revision_notes},
            priority=1,
        ))
        self.console.log(f"[yellow]Reviewer rejected {agent_role} artifact ({len(must_fix)} must-fix)[/yellow]")
        return False
