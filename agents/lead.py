import asyncio
import logging
import os
import sys
from datetime import UTC, datetime

from rich.panel import Panel
from rich.text import Text

from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from core.phases import DEFAULT_PHASES, VALID_ROLES
from core.paths import METADATA_ROOT
from core.profile import load_profile, DEFAULT_PROFILE
from core import deploy, handoff, hooks
from core.events import emit
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
                    "enum": ["pm", "architect", "backend", "qa", "devops", "data_engineer", "ml_engineer"],
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

_PLANNING_TOOLS = [
    {
        "name": "propose_plan",
        "description": (
            "Propose the ordered sequence of phases to deliver the sprint goal. Each phase assigns "
            "one role a concrete objective. Order by dependency (requirements before design before "
            "implementation before testing before ship). Reuse the seed plan as a baseline; only "
            "deviate when the goal clearly calls for it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phases": {
                    "type": "array",
                    "description": "Ordered phases to execute",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "enum": list(VALID_ROLES),
                                "description": "The agent that owns this phase",
                            },
                            "objective": {
                                "type": "string",
                                "description": "What this phase must produce, specific to the goal",
                            },
                        },
                        "required": ["role", "objective"],
                    },
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this sequence fits the goal (one or two sentences)",
                },
            },
            "required": ["phases"],
        },
    },
]

_REPLAN_TOOLS = [
    {
        "name": "adjust_plan",
        "description": (
            "Decide what to do after a phase finished. Either continue with the remaining plan, or "
            "insert ONE focused follow-up phase to run next (e.g. route a QA-found defect back to "
            "backend, or add a missing verification step). Only insert when the just-finished phase "
            "left a real, actionable gap — do not pad the plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["continue", "insert_phase"],
                    "description": "continue = proceed with the existing plan; insert_phase = run one follow-up next",
                },
                "role": {
                    "type": "string",
                    "enum": list(VALID_ROLES),
                    "description": "For insert_phase: the agent to run next",
                },
                "objective": {
                    "type": "string",
                    "description": "For insert_phase: the specific, scoped follow-up task",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this adjustment is warranted",
                },
            },
            "required": ["action"],
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
        self._goal: str = ""
        self._plan_gate: bool = False
        # Adaptive mode: the Lead plans the phase sequence from the goal, re-routes on outcomes
        # (e.g. QA failure → backend fix), and self-checks the goal is met before finishing.
        # Off by default — a fixed preset runs exactly as given (backward compatible).
        self._adaptive: bool = False
        self._replan_budget: int = 0
        self._last_review_summary: str = ""
        # PR-workflow branch for --deploy-commit (set by run_development_cycle); None = current branch.
        self._deploy_branch: str | None = None
        # Set when --deploy-gate is on; gates the mid-sprint escalation pause.
        self._deploy_gate: bool = False
        # Set True by _finalize_sprint when the deploy is fail-closed (e.g. unresolved
        # review findings). Read by the CLI to return a non-zero exit code.
        self._deploy_blocked: bool = False
        # Deploy gate hooks — overridable in tests. Defaults do real I/O.
        self._approval_fn = self._default_approval
        self._verify_fn = self._default_verify
        # Mid-sprint escalation pause — overridable in tests. Default prompts on a TTY.
        self._escalation_pause_fn = self._default_escalation_pause
        # Safe-pause timeout: if no operator responds to a mid-sprint escalation within this many
        # seconds, default to deferring to the deploy gate instead of blocking the run forever.
        self._escalation_timeout = float(os.getenv("AGENTFORGE_ESCALATION_TIMEOUT", "300"))
        # Blocking guidance reader (overridable in tests). Real impl reads one line from stdin.
        self._read_guidance = self._blocking_read_guidance
        # Last-reviewed content per file, for diff-only reviews on revision attempts (context-saver).
        self._reviewed_snapshots: dict[str, str] = {}

    async def run(self) -> None:
        pass  # Lead is driven by run_development_cycle, not the message loop

    async def run_development_cycle(
        self,
        goal: str,
        phases: list[tuple[str, str]] | None = None,
        *,
        deploy_gate: bool = False,
        auto_approve: bool = False,
        deploy_commit: bool = False,
        deploy_branch: str | None = None,
        plan_gate: bool = False,
        resume: bool = False,
        strict_review: bool = False,
        allow_quality_debt: bool = False,
        adaptive: bool = False,
    ) -> bool:
        """Run the full sprint. Returns True if the deploy was recorded, False if fail-closed
        (blocked by unresolved review findings or a declined gate).

        When ``adaptive`` is set, the Lead plans the phase sequence from the goal (seeded by the
        preset), re-routes on phase outcomes, and self-checks the goal is met before finishing.
        When unset (default), the given ``phases`` run in order, unchanged.
        """
        self._plan_gate = plan_gate
        self._deploy_branch = deploy_branch
        self._deploy_gate = deploy_gate
        self._goal = goal
        self._adaptive = adaptive
        self._replan_budget = 3 if adaptive else 0
        phase_list = phases if phases is not None else DEFAULT_PHASES
        self.console.print(Panel(
            f"[bold]Sprint Goal:[/bold]\n{goal.strip()}",
            title="[bold cyan]AgentForge — Development Cycle Start[/bold cyan]",
            border_style="cyan",
        ))

        await self.memory.remember("sprint_goal", goal)

        # Preflight: confirm the reviewer model can actually emit a structured verdict before
        # we run any phase. A reviewer that can't review sends every artifact into a
        # reject→revise death-spiral that burns dozens of model calls and never converges
        # (see agentforge-failure.md, F2). Abort early with a clear, actionable error instead.
        if not await self._reviewer_preflight():
            self._deploy_blocked = True
            return False

        completed: set[str] = set()
        if resume:
            cp = await handoff.load_checkpoint(self.artifacts)
            if cp.get("goal_fp") == handoff.goal_fingerprint(goal):
                completed = set(cp.get("completed", []))
                self._approved_artifacts.update(cp.get("artifacts", {}))
                if completed:
                    self.console.log(
                        f"[cyan]Resuming — skipping completed phases: {', '.join(sorted(completed))}[/cyan]"
                    )
            else:
                self.console.log("[yellow]Resume requested but checkpoint goal differs — starting fresh.[/yellow]")

        # Build the work queue. In adaptive mode the Lead proposes the plan from the goal
        # (seeded by the preset); otherwise the preset runs exactly as given.
        from collections import deque

        if self._adaptive:
            planned = await self._plan_phases(goal, list(phase_list))
            queue: deque[tuple[str, str]] = deque(planned)
        else:
            queue = deque(phase_list)

        # Hard cap so replanning / done-check remediation can never loop forever.
        hard_cap = len(queue) + 8
        executed = 0
        done_check_done = False

        while queue and executed < hard_cap:
            agent_role, phase_description = queue.popleft()
            if agent_role in completed:
                self.console.log(f"[dim]Skipping {agent_role} (already complete in checkpoint).[/dim]")
                continue

            outcome = await self._run_phase(agent_role, phase_description, goal)
            executed += 1

            if self._adaptive:
                for follow_role, follow_obj in await self._replan_after_phase(agent_role, outcome, goal):
                    self.console.log(f"[cyan]Replan:[/cyan] inserting {follow_role} — {follow_obj[:70]}")
                    queue.appendleft((follow_role, follow_obj))

            # When the plan drains in adaptive mode, verify the goal is actually met before
            # declaring success — and enqueue one bounded remediation round if it is not.
            if self._adaptive and not queue and not done_check_done:
                done_check_done = True
                met, gaps = await self._verify_goal_met(goal)
                if not met and gaps:
                    await self.memory.remember("goal_gap", gaps, "decision")
                    self.console.log(f"[yellow]Goal check: gaps remain[/yellow] — {gaps[:80]}")
                    queue.append(("backend", f"Close the remaining gaps so the goal is met: {gaps}"))
                    queue.append(("qa", "Re-verify the result meets the goal after remediation; run the tests"))
                else:
                    self.console.log("[green]Goal check: acceptance criteria met.[/green]")

        self.console.print(Panel(
            Text("All phases complete. Artifacts written to workspace/", style="bold green"),
            title="[bold green]Sprint Complete[/bold green]",
            border_style="green",
        ))

        await self._finalize_sprint(
            goal,
            deploy_gate=deploy_gate,
            auto_approve=auto_approve,
            deploy_commit=deploy_commit,
            strict_review=strict_review,
            allow_quality_debt=allow_quality_debt,
        )
        return not self._deploy_blocked

    async def _run_phase(self, agent_role: str, phase_description: str, goal: str) -> dict:
        """Run one phase to a verdict. Returns an outcome dict the adaptive loop can route on:
        ``{"role", "approved", "quality_debt", "escalated"}``.
        """
        outcome = {"role": agent_role, "approved": False, "quality_debt": False, "escalated": False}
        self.console.rule(f"[bold yellow]Phase: {agent_role.upper()}[/bold yellow]")
        _lead_log.info("phase_start role=%s", agent_role)

        await self._run_phase_hook("pre-phase", agent_role)

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
        plan_gate_active = self._plan_gate and agent_role == "backend"
        task_payload["plan_gate"] = plan_gate_active

        self.console.log(f"[cyan]Lead → {agent_role}:[/cyan] {task_payload.get('deliverable', '')}")

        await self.bus.publish(Message(
            type=MessageType.TASK_ASSIGN,
            sender="lead",
            recipient=agent_role,
            payload=task_payload,
            priority=1,
        ))

        if plan_gate_active:
            await self._handle_plan_gate(agent_role)

        max_revisions = 3
        revision = 0
        while revision < max_revisions:
            result_msg = await self.bus.receive("lead", timeout=600.0)
            if result_msg is None:
                self.console.log(f"[red]Timeout waiting for {agent_role}[/red]")
                break

            if result_msg.type == MessageType.SHUTDOWN:
                break

            if result_msg.type == MessageType.ESCALATION:
                outcome["escalated"] = True
                await self._handle_escalation(agent_role, result_msg)
                continue  # already recorded by the agent; will surface at the deploy gate

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
                outcome["approved"] = True
                break

            revision += 1
            if revision >= max_revisions:
                outcome["quality_debt"] = True
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

        # Write the per-phase handoff file and update the resumable checkpoint.
        path = self._approved_artifacts.get(f"{agent_role}_artifact", "")
        await handoff.record_phase(
            self.artifacts,
            goal=goal,
            role=agent_role,
            brief=self._current_brief,
            files=[path] if path else [],
            review_summary=self._last_review_summary,
        )

        # Typed progress for host assistants / Web UI (no-op unless AGENTFORGE_JSON_LOG is set).
        emit("phase_complete", phase=agent_role, role=agent_role, artifact=path)

        await self._run_phase_hook("post-phase", agent_role)

        return outcome

    async def _run_phase_hook(self, stage: str, agent_role: str) -> None:
        """Run an optional project guardrail hook around a phase (advisory, never fatal)."""
        code_root = self.artifacts.WORKSPACE
        status, detail = await hooks.run_phase_hook(
            stage, agent_role, metadata_root=METADATA_ROOT, code_root=code_root
        )
        if status == "skipped":
            return
        if status == "ok":
            self.console.log(f"[green]{stage} hook ok ({agent_role})[/green]")
            _lead_log.info("phase_hook stage=%s role=%s status=ok", stage, agent_role)
        else:
            self.console.log(
                f"[yellow]{stage} hook failed ({agent_role}) — advisory, continuing[/yellow]"
            )
            _lead_log.warning(
                "phase_hook stage=%s role=%s status=fail detail=%s",
                stage, agent_role, detail.strip()[-200:],
            )

    async def _handle_escalation(self, agent_role: str, msg: Message) -> None:
        """Surface a mid-sprint escalation; pause for the operator when the deploy gate is on.

        The escalation is already recorded by the agent and will also appear in the deploy
        summary. When ``--deploy-gate`` is active we additionally give the operator a chance
        to intervene mid-sprint (recorded as guidance) instead of only at the end.
        """
        question = msg.payload.get("question", "")
        self.console.log(f"[magenta]Escalation from {agent_role}:[/magenta] {question[:80]}")
        if self._deploy_gate:
            await self._escalation_pause_fn(agent_role, question)

    @staticmethod
    def _blocking_read_guidance() -> str:
        """Read one line of operator guidance from stdin (blocks until Enter). Overridable in tests."""
        return input("Guidance (or Enter): ").strip()

    async def _default_escalation_pause(self, agent_role: str, question: str) -> None:
        """Interactive mid-sprint pause with a safe-pause timeout.

        Without a TTY, record and continue (no deadlock). With a TTY, wait up to
        ``self._escalation_timeout`` seconds for operator guidance; if none arrives, default to a
        safe pause (defer to the deploy gate) instead of burning idle compute waiting forever.
        """
        if not sys.stdin.isatty():
            self.console.log(
                "[dim]Escalation noted (no interactive terminal) — will surface at the deploy gate.[/dim]"
            )
            return
        self.console.print(Panel(
            Text(
                f"{agent_role} escalated a decision:\n\n{question}\n\n"
                f"Enter guidance for the team, or press Enter to defer to the deploy gate "
                f"(auto-defers after {int(self._escalation_timeout)}s).",
                style="bold magenta",
            ),
            title="[bold magenta]Escalation — sprint paused[/bold magenta]",
            border_style="magenta",
        ))
        loop = asyncio.get_event_loop()
        try:
            answer = await asyncio.wait_for(
                loop.run_in_executor(None, self._read_guidance),
                timeout=self._escalation_timeout,
            )
        except asyncio.TimeoutError:
            # Safe pause: no human in the loop within the window — defer rather than deadlock.
            self.console.log(
                f"[yellow]No operator response within {int(self._escalation_timeout)}s — "
                f"safe-pausing; escalation deferred to the deploy gate.[/yellow]"
            )
            await self.memory.remember(
                f"escalation_timeout_{agent_role}",
                f"no operator response within {int(self._escalation_timeout)}s; safe-paused and "
                f"deferred to the deploy gate",
                "decision",
            )
            return
        if answer:
            await self.memory.remember(f"escalation_guidance_{agent_role}", answer, "decision")
            self.console.log(f"[cyan]Recorded guidance for {agent_role}.[/cyan]")

    # ------------------------------------------------------------------ adaptive planning

    def _normalize_plan(self, raw_phases: list) -> list[tuple[str, str]]:
        """Validate an LLM-proposed phase list into ``[(role, objective)]``; drop bad entries."""
        out: list[tuple[str, str]] = []
        for p in raw_phases or []:
            if not isinstance(p, dict):
                continue
            role = str(p.get("role", "")).strip()
            objective = str(p.get("objective", "")).strip()
            if role in VALID_ROLES and objective:
                out.append((role, objective))
        return out

    async def _plan_phases(
        self, goal: str, seed: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Ask the Lead to propose the phase sequence for the goal, seeded by the preset.

        Falls back to the seed plan if the model proposes nothing usable, so a planning hiccup
        never strands the sprint.
        """
        seed_desc = "\n".join(f"- {r}: {d}" for r, d in seed) or "(none)"
        self.console.log("[cyan]Planning the sprint from the goal…[/cyan]")
        context = await self._build_dynamic_context()
        context += f"\n\n## Sprint Goal\n{goal}"
        try:
            response = await self._call_llm(
                user_message=(
                    "Plan the phases to deliver this sprint goal. Use the seed plan below as a "
                    "baseline and adjust only where the goal clearly requires it (add, drop, or "
                    "reorder phases). Respect dependencies. Call propose_plan exactly once.\n\n"
                    f"Seed plan:\n{seed_desc}"
                ),
                dynamic_context=context,
                tools=_PLANNING_TOOLS,
            )
        except Exception as e:  # noqa: BLE001 — planning is best-effort; never strand the run
            _lead_log.warning("plan_phases error=%s — using seed plan", e)
            return seed

        for name, tool_input in self._extract_tool_calls(response):
            if name == "propose_plan":
                planned = self._normalize_plan(tool_input.get("phases", []))
                if planned:
                    await self.memory.remember(
                        "sprint_plan", "; ".join(f"{r}:{o[:60]}" for r, o in planned), "decision"
                    )
                    self.console.log(
                        f"[green]Plan:[/green] {' → '.join(r for r, _ in planned)}"
                    )
                    return planned
        self.console.log("[dim]No usable plan proposed — using the seed plan.[/dim]")
        return seed

    async def _replan_after_phase(
        self, agent_role: str, outcome: dict, goal: str
    ) -> list[tuple[str, str]]:
        """Optionally insert one follow-up phase based on the just-finished phase's outcome.

        Bounded by ``self._replan_budget`` and only consulted when there is a real signal
        (unresolved review findings or an escalation). Returns ``[]`` to continue unchanged.
        """
        if self._replan_budget <= 0:
            return []
        if not (outcome.get("quality_debt") or outcome.get("escalated")):
            return []

        signal = "unresolved review findings" if outcome.get("quality_debt") else "an escalation"
        context = await self._build_dynamic_context()
        context += f"\n\n## Sprint Goal\n{goal}"
        try:
            response = await self._call_llm(
                user_message=(
                    f"The {agent_role} phase just finished with {signal}. Decide whether to insert "
                    f"one focused follow-up phase to run next, or continue with the remaining plan. "
                    f"Call adjust_plan exactly once."
                ),
                dynamic_context=context,
                tools=_REPLAN_TOOLS,
            )
        except Exception as e:  # noqa: BLE001 — replanning is best-effort
            _lead_log.warning("replan error=%s — continuing", e)
            return []

        for name, tool_input in self._extract_tool_calls(response):
            if name == "adjust_plan" and tool_input.get("action") == "insert_phase":
                role = str(tool_input.get("role", "")).strip()
                objective = str(tool_input.get("objective", "")).strip()
                if role in VALID_ROLES and objective:
                    self._replan_budget -= 1
                    reason = str(tool_input.get("reason", "")).strip()
                    await self.memory.remember(
                        f"replan_{agent_role}", f"insert {role}: {objective[:80]} ({reason[:80]})", "decision"
                    )
                    _lead_log.info("replan insert role=%s after=%s", role, agent_role)
                    return [(role, objective)]
        return []

    async def _verify_goal_met(self, goal: str) -> tuple[bool, str]:
        """Self-check whether the accepted artifacts satisfy the goal. Advisory, best-effort.

        Returns ``(met, gaps)``; on any error returns ``(True, "")`` so a hiccup never blocks the
        run (the deploy quality gate remains the hard backstop).
        """
        artifacts_desc = "\n".join(f"- {k}: {v}" for k, v in self._approved_artifacts.items()) or "(none)"
        context = await self._build_dynamic_context()
        try:
            response = await self._call_llm(
                user_message=(
                    "Review whether the sprint goal is actually satisfied by the accepted artifacts.\n\n"
                    f"Sprint goal:\n{goal}\n\n"
                    f"Accepted artifacts:\n{artifacts_desc}\n\n"
                    "If the goal's core deliverables are present, reply exactly 'MET'. Otherwise reply "
                    "'UNMET: <the specific missing or incomplete deliverables>'. Be strict but fair — "
                    "minor polish is not 'unmet'."
                ),
                dynamic_context=context,
            )
        except Exception as e:  # noqa: BLE001
            _lead_log.warning("goal_check error=%s — treating as met", e)
            return True, ""
        verdict = self._extract_text(response).strip()
        if verdict.upper().startswith("MET"):
            return True, ""
        gaps = verdict.split(":", 1)[-1].strip() if ":" in verdict else verdict
        return False, gaps

    async def _reviewer_preflight(self) -> bool:
        """Smoke-test that the reviewer model returns a valid verdict on a trivial fixture.

        Returns True when the reviewer submitted a structured verdict (the tool contract works),
        False when it failed to — in which case the run should abort before any phase rather than
        loop the architect↔reviewer death-spiral (F2). Skippable via
        ``AGENTFORGE_SKIP_REVIEWER_PREFLIGHT=1`` for trusted setups.
        """
        if os.getenv("AGENTFORGE_SKIP_REVIEWER_PREFLIGHT", "").strip().lower() in ("1", "true", "yes"):
            return True

        self.console.log("[cyan]Reviewer preflight: checking the reviewer can emit a verdict…[/cyan]")
        fixture_path = "handoff/_preflight_fixture.md"
        await self.artifacts.write(
            fixture_path,
            "# Preflight Fixture\n\nThis file exists only to test the review tool contract.\n"
            "It trivially meets its one-line brief. Approve it.\n",
        )
        try:
            verdict = await self.reviewer.review(
                phase_role="preflight",
                summary="Trivial fixture that meets its brief.",
                files=[fixture_path],
                brief="Confirm this one-line fixture file exists and is non-empty, then submit a verdict.",
            )
        except Exception as e:  # noqa: BLE001 — preflight must surface any reviewer failure clearly
            self.console.print(Panel(
                Text(
                    f"Reviewer preflight failed to run: {e}\n\n"
                    "The reviewer model could not complete a trivial review. Aborting before the "
                    "run wastes model calls.",
                    style="bold red",
                ),
                title="[bold red]Reviewer Preflight Failed[/bold red]",
                border_style="red",
            ))
            _lead_log.warning("reviewer_preflight error=%s", e)
            return False

        if verdict.get("submitted"):
            self.console.log("[green]Reviewer preflight passed.[/green]")
            return True

        reviewer_model = ""
        try:
            from .base_agent import ollama_model_for_role, llm_provider

            reviewer_model = ollama_model_for_role("reviewer") if llm_provider() == "ollama" else ""
        except Exception:  # noqa: BLE001
            pass
        hint = (
            f"The reviewer model{f' ({reviewer_model})' if reviewer_model else ''} did not call "
            "submit_review on a trivial fixture — it cannot follow the structured-verdict tool "
            "contract. Every artifact would be force-rejected and the run would never converge.\n\n"
            "Use a stronger, tool-capable model for the reviewer role, e.g.\n"
            "  AGENTFORGE_OLLAMA_MODEL_REVIEWER=qwen2.5:14b-instruct\n"
            "(see agentforge-failure.md). Set AGENTFORGE_SKIP_REVIEWER_PREFLIGHT=1 to bypass."
        )
        self.console.print(Panel(
            Text(hint, style="bold red"),
            title="[bold red]Reviewer Preflight Failed[/bold red]",
            border_style="red",
        ))
        _lead_log.warning("reviewer_preflight failed model=%s", reviewer_model)
        return False

    async def _grounding_gap(self, agent_role: str, artifact: dict) -> list[str]:
        """Return salient goal terms missing from a PM/architect artifact (off-domain drift).

        Only PM and architect spec documents are graded — they author against the goal directly.
        Returns an empty list when grounded, the gate does not apply, or it is disabled via
        ``AGENTFORGE_SKIP_GROUNDING=1``.
        """
        if agent_role not in ("pm", "architect"):
            return []
        if os.getenv("AGENTFORGE_SKIP_GROUNDING", "").strip().lower() in ("1", "true", "yes"):
            return []
        if not self._goal.strip():
            return []

        from core.grounding import grounding_gap

        artifact_path = artifact.get("primary_path", artifact.get("path", ""))
        if not artifact_path:
            return []
        content = await self.artifacts.read(artifact_path)
        if content.startswith("[File not found:") or content.startswith("[Access denied:"):
            return []
        return grounding_gap(self._goal, content)

    async def _thin_artifacts(self) -> list[tuple[str, str]]:
        """Return (path, reason) for accepted spec docs that are thin/placeholder (F3 backstop).

        Re-reads the accepted artifacts at the deploy gate and flags any graded spec document
        (requirements/architecture/design) that is a stub, deferred-placeholder, or echoes the
        reviewer error. Skippable via ``AGENTFORGE_SKIP_DOC_QUALITY=1``.
        """
        if os.getenv("AGENTFORGE_SKIP_DOC_QUALITY", "").strip().lower() in ("1", "true", "yes"):
            return []

        from core.artifact_quality import is_graded_doc, thin_artifact_reason

        flagged: list[tuple[str, str]] = []
        for path in self._approved_artifacts.values():
            if not path or not is_graded_doc(path):
                continue
            content = await self.artifacts.read(path)
            if content.startswith("[File not found:") or content.startswith("[Access denied:"):
                flagged.append((path, "artifact missing or unreadable at deploy time"))
                continue
            reason = thin_artifact_reason(path, content)
            if reason:
                flagged.append((path, reason))
        return flagged

    async def _collect_diffs(self, files: list[str], *, max_chars: int = 6000) -> str:
        """Build a bounded unified diff of ``files`` against the last-reviewed snapshot.

        Updates the snapshot to the current content as a side effect. Returns "" when nothing
        changed or no prior snapshot exists (so the first review of a file is always a full read).
        """
        from core.diffs import unified_diff

        chunks: list[str] = []
        budget = max_chars
        for path in files:
            if not path:
                continue
            content = await self.artifacts.read(path)
            if content.startswith("[File not found:") or content.startswith("[Access denied:"):
                continue
            prior = self._reviewed_snapshots.get(path)
            self._reviewed_snapshots[path] = content
            if prior is None:
                continue  # first time we see this file — no diff to show
            d = unified_diff(prior, content, path, max_chars=min(4000, budget))
            if d:
                chunks.append(d)
                budget -= len(d)
                if budget <= 0:
                    break
        return "\n".join(chunks)

    async def _review_artifact(self, agent_role: str, artifact: dict, attempt: int) -> bool:
        """Consult the independent Reviewer and act on its verdict.

        The Reviewer reads the actual files (not a truncated preview) and returns a
        structured decision. A missing verdict defaults to reject — silence is not approval.

        On revision attempts (``attempt > 0``) in adaptive mode the Reviewer is additionally given a
        unified diff of what changed since the last review, so it can focus on the fix instead of
        re-reading whole files (it may still read_file for broader context).
        """
        artifact_path = artifact.get("primary_path", artifact.get("path", ""))
        files_written = artifact.get("files", []) or ([artifact_path] if artifact_path else [])
        summary = artifact.get("summary", "")

        # Goal-grounding gate: reject off-domain drift before spending a reviewer call (F1).
        missing = await self._grounding_gap(agent_role, artifact)
        if missing:
            shown = ", ".join(missing[:8]) + (" …" if len(missing) > 8 else "")
            notes = (
                f"Off-domain: the artifact does not reference the goal's named entities "
                f"({shown}). Rewrite it for the actual sprint goal — do not substitute a generic "
                f"or unrelated product. Reference the specific names, files, and identifiers in the goal."
            )
            self._last_review_summary = "Rejected by goal-grounding gate (off-domain)."
            emit("review_verdict", role=agent_role, decision="reject", attempt=attempt + 1)
            await self.bus.publish(Message(
                type=MessageType.ARTIFACT_REJECTED,
                sender="lead",
                recipient=agent_role,
                payload={"agent": agent_role, "artifact_name": artifact_path, "revision_notes": notes},
                priority=1,
            ))
            self.console.log(
                f"[yellow]Grounding gate rejected {agent_role} artifact "
                f"({len(missing)} goal terms missing)[/yellow]"
            )
            _lead_log.warning("grounding_gate_reject role=%s missing=%s", agent_role, missing[:8])
            return False

        self.console.log(
            f"[cyan]Reviewer auditing {agent_role} artifact (attempt {attempt + 1}): {summary}[/cyan]"
        )

        context = await self._build_dynamic_context()

        # Diff-only focus on revision attempts in adaptive mode: snapshot now, and on attempts after
        # the first hand the Reviewer the unified diff so it judges the change, not the whole tree.
        diffs = await self._collect_diffs(files_written)
        if not (self._adaptive and attempt > 0):
            diffs = ""

        verdict = await self.reviewer.review(
            phase_role=agent_role,
            summary=summary,
            files=files_written,
            diffs=diffs,
            brief=self._current_brief,
            dynamic_context=context,
        )

        decision = verdict.get("decision", "reject")
        must_fix = verdict.get("must_fix") or []
        should_fix = verdict.get("should_fix") or []
        review_summary = verdict.get("summary", "")
        self._last_review_summary = review_summary
        # Typed progress for host assistants / Web UI (no-op unless AGENTFORGE_JSON_LOG is set).
        emit("review_verdict", role=agent_role, decision=decision, attempt=attempt + 1)

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

    # ------------------------------------------------------------------ plan gate

    async def _handle_plan_gate(self, agent_role: str) -> None:
        """Wait for the agent's build plan, approve or redirect it before any code is written.

        Fail-open: if no plan arrives, the build proceeds (no deadlock).
        """
        msg = await self.bus.receive("lead", timeout=300.0)
        if msg is None or msg.type != MessageType.CONSULT_REQUEST:
            self.console.log(f"[yellow]No build plan from {agent_role}; proceeding without plan gate.[/yellow]")
            return

        plan = msg.payload.get("plan", "")
        self.console.log(f"[cyan]Reviewing {agent_role} build plan…[/cyan]")
        context = await self._build_dynamic_context()
        response = await self._call_llm(
            user_message=(
                f"The {agent_role} proposed this build plan for the brief:\n{self._current_brief}\n\n"
                f"Plan:\n{plan}\n\n"
                f"If it correctly and completely addresses the brief, reply exactly 'APPROVE'. "
                f"Otherwise reply 'REDIRECT: <specific changes>'."
            ),
            dynamic_context=context,
        )
        verdict = self._extract_text(response).strip()
        approved = verdict.upper().startswith("APPROVE")
        notes = "" if approved else verdict.split(":", 1)[-1].strip()
        await self.memory.remember(f"build_plan_{agent_role}", plan[:1000], "decision")
        self.console.log(
            f"[green]Plan approved[/green]" if approved else f"[yellow]Plan redirected:[/yellow] {notes[:80]}"
        )
        await self.bus.publish(Message(
            type=MessageType.CONSULT_RESPONSE,
            sender="lead",
            recipient=agent_role,
            payload={"approved": approved, "notes": notes},
            priority=1,
        ))

    # ------------------------------------------------------------------ deploy gate

    def _deploy_target(self):
        """Resolve ``(code_root, profile)`` for the deploy verify/commit step.

        Reads the *live* code root (``ArtifactStore.WORKSPACE``, re-rooted by ``--target-repo``) so
        verification and commits hit the real project. DailyEase default keeps targeting
        ``workspace/dailyease/``; any other profile targets the repo/code root directly.
        """
        code_root = self.artifacts.WORKSPACE
        profile = load_profile(code_root, METADATA_ROOT)
        if profile.app_root == DEFAULT_PROFILE.app_root and (code_root / DEFAULT_PROFILE.app_root).is_dir():
            # DailyEase greenfield: app lives under workspace/dailyease/.
            code_root = self.artifacts.dailyease_root()
        return code_root, profile

    async def _default_verify(self) -> tuple[str, str]:
        code_root, profile = self._deploy_target()
        return await deploy.run_verify(code_root, profile.verify_cmd)

    async def _default_approval(self, summary: str) -> bool:
        """Interactive go/no-go. Without a TTY, do not approve (fail safe)."""
        if not sys.stdin.isatty():
            self.console.log(
                "[yellow]Deploy gate enabled but no interactive terminal — not approving "
                "(use --auto-approve for unattended deploys).[/yellow]"
            )
            return False
        self.console.print(summary)
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, lambda: input("Approve deploy? [y/N] ").strip().lower()
        )
        return answer in ("y", "yes")

    async def _build_deploy_summary(self, goal: str) -> str:
        decisions = await self.memory.recall_all("decision")
        debts = {k: v for k, v in decisions.items() if k.startswith("quality_debt_")}
        escalations = {k: v for k, v in decisions.items() if k.startswith("escalation_")}

        lines = ["## Deploy summary", f"Sprint goal: {goal.strip().splitlines()[0] if goal.strip() else '(none)'}", ""]
        if self._approved_artifacts:
            lines.append("Accepted artifacts:")
            lines += [f"- {k}: {v}" for k, v in self._approved_artifacts.items()]
        else:
            lines.append("No artifacts were accepted.")
        if debts:
            lines += ["", "⚠ Unresolved review findings (quality debt):"]
            lines += [f"- {v}" for v in debts.values()]
        if escalations:
            lines += ["", "⚠ Open escalations:"]
            lines += [f"- {v}" for v in escalations.values()]

        from core.known_gaps import GAPS_PATH

        gaps = await self.artifacts.read(GAPS_PATH)
        if gaps.strip() and not gaps.lstrip().startswith("["):
            gap_entries = [ln for ln in gaps.splitlines() if ln.startswith("- [")]
            if gap_entries:
                lines += ["", f"⚠ Known gaps deferred ({len(gap_entries)}) — see {GAPS_PATH}:"]
                lines += gap_entries[:10]
                if len(gap_entries) > 10:
                    lines.append(f"- … and {len(gap_entries) - 10} more")
        return "\n".join(lines)

    async def _finalize_sprint(
        self,
        goal: str,
        *,
        deploy_gate: bool,
        auto_approve: bool,
        deploy_commit: bool,
        strict_review: bool = False,
        allow_quality_debt: bool = False,
    ) -> None:
        self.console.rule("[bold blue]Deploy gate[/bold blue]")

        summary = await self._build_deploy_summary(goal)
        verify_status, verify_detail = await self._verify_fn()
        self.console.log(f"[blue]Verify: {verify_status}[/blue]")
        _lead_log.info("deploy_verify status=%s", verify_status)
        summary += f"\n\nVerification: {verify_status}"

        # Fail closed by default: unresolved review findings (artifacts force-accepted after the
        # max revision cap) or thin/placeholder spec docs block the deploy — even on an autonomous
        # run. A green "Sprint Complete" must mean clean approvals. Pass --allow-quality-debt to
        # ship with the debt flagged instead.
        if not allow_quality_debt:
            decisions = await self.memory.recall_all("decision")
            debt_count = sum(1 for k in decisions if k.startswith("quality_debt_"))
            thin = await self._thin_artifacts()
            if debt_count or thin:
                self._deploy_blocked = True
                reasons: list[str] = []
                if debt_count:
                    reasons.append(f"{debt_count} unresolved review finding(s) (quality debt)")
                if thin:
                    reasons.append(f"{len(thin)} thin/placeholder spec doc(s)")
                body = "Deploy blocked: " + "; ".join(reasons) + "."
                if thin:
                    body += "\n\nThin artifacts:\n" + "\n".join(f"- {p}: {r}" for p, r in thin)
                body += "\n\nResolve and re-run, or pass --allow-quality-debt to ship flagged."
                # Preserve the existing record label when the block is debt-only (keeps the
                # quality-debt contract stable); name thin docs when that is the cause.
                if debt_count:
                    label = "blocked (unresolved review findings)"
                else:
                    label = "blocked (thin or placeholder artifacts)"
                self.console.print(Panel(
                    Text(body, style="bold red"),
                    title="[bold red]Deploy Blocked (quality gate)[/bold red]",
                    border_style="red",
                ))
                _lead_log.warning("deploy_blocked debt=%s thin=%s", debt_count, len(thin))
                await self._write_deploy_record(
                    goal, label, verify_status, verify_detail, commit_info=None
                )
                return

        if not deploy_gate:
            self.console.log(
                "[dim]Deploy gate disabled — autonomous run, no human sign-off requested. "
                "Set --deploy-gate to require approval.[/dim]"
            )
            decision = "autonomous"
        else:
            if verify_status == "fail":
                self.console.log("[red]Verification failed — review the smoke test before approving.[/red]")
            approved = True if auto_approve else await self._approval_fn(summary)
            if not approved:
                self._deploy_blocked = True
                self.console.print(Panel(
                    Text("Deploy declined. Nothing was shipped.", style="bold red"),
                    title="[bold red]Deploy Aborted[/bold red]",
                    border_style="red",
                ))
                await self._write_deploy_record(goal, "aborted", verify_status, verify_detail, commit_info=None)
                return
            decision = "approved (auto)" if auto_approve else "approved"

        commit_info: str | None = None
        if deploy_commit:
            commit_root, _ = self._deploy_target()
            message = deploy.build_commit_message(goal)
            if self._deploy_branch:
                ok, info = await deploy.git_commit_dir(commit_root, message, branch=self._deploy_branch)
            else:
                ok, info = await deploy.git_commit_dir(commit_root, message)
            commit_info = f"{'committed ' + info if ok else 'commit skipped: ' + info}"
            if ok and self._deploy_branch:
                commit_info += f" (branch {self._deploy_branch})"
            level = "green" if ok else "yellow"
            self.console.log(f"[{level}]Deploy commit: {commit_info}[/{level}]")

        record_path = await self._write_deploy_record(goal, decision, verify_status, verify_detail, commit_info)
        self.console.print(Panel(
            Text(f"Deploy recorded ({decision}). See {record_path}", style="bold green"),
            title="[bold green]Deploy Gate Complete[/bold green]",
            border_style="green",
        ))

    async def _write_deploy_record(
        self,
        goal: str,
        decision: str,
        verify_status: str,
        verify_detail: str,
        commit_info: str | None,
    ) -> str:
        ts = datetime.now(UTC).isoformat()
        summary = await self._build_deploy_summary(goal)
        body = [
            "# Deploy Record",
            f"Timestamp: {ts}",
            f"Decision: {decision}",
            f"Verification: {verify_status}",
        ]
        if commit_info is not None:
            body.append(f"Commit: {commit_info}")
        body += ["", summary, "", "## Verification detail", "```", verify_detail.strip() or "(none)", "```", ""]
        path = "reports/deploy_record.md"
        await self.artifacts.write(path, "\n".join(body))
        await self.memory.remember("deploy_decision", decision, "decision")
        return path
