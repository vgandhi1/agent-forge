"""Independent code reviewer.

Distinct from the QA engineer (which writes and runs tests): the Reviewer reads the
actual files an agent produced and judges them against the task brief for spec
compliance, drift, security, logic, and standards. The Lead consults it during the
approval gate instead of reviewing artifacts itself.
"""
from __future__ import annotations

from typing import Any

from core.message_bus import MessageBus
from core.message_types import MessageType
from core.artifact_store import ArtifactStore
from .base_agent import BaseAgent

_REVIEWER_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file the agent produced so you can review its actual contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (workspace-relative or absolute) to read.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "submit_review",
        "description": "Submit your verdict. Call exactly once after reviewing the files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["approve", "reject", "escalate"],
                    "description": "approve (meets brief), reject (blocking issues), or escalate (needs a product/business decision)",
                },
                "summary": {
                    "type": "string",
                    "description": "One or two sentences: what was reviewed and the verdict rationale.",
                },
                "must_fix": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Blocking issues. Each: file — what is wrong — how to fix. Empty if approving.",
                },
                "should_fix": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Non-blocking recommendations. May be empty.",
                },
                "drift": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Things the agent added beyond the brief (scope drift). Flag even if harmless; these are logged as known gaps, not necessarily blocking.",
                },
                "escalation_question": {
                    "type": "string",
                    "description": "If decision is escalate: the product/business question that must be resolved.",
                },
            },
            "required": ["decision", "summary"],
        },
    },
]

_MAX_FILE_CHARS = 8000


class ReviewerAgent(BaseAgent):
    async def run(self) -> None:
        # The Reviewer is consulted synchronously by the Lead via review(); it is not a
        # bus worker. Stay alive until shutdown so registration stays consistent.
        while True:
            msg = await self.bus.receive(self.role)
            if msg is None:
                continue
            if msg.type == MessageType.SHUTDOWN:
                break

    async def review(
        self,
        *,
        phase_role: str,
        summary: str,
        files: list[str],
        brief: str = "",
        dynamic_context: str = "",
    ) -> dict[str, Any]:
        """Read the produced files and return a structured verdict.

        Returns ``{"decision", "summary", "must_fix", "should_fix", "escalation_question"}``.
        Defaults to ``reject`` if the model fails to submit a verdict — silence is not approval.
        """
        file_list = "\n".join(f"- {f}" for f in files) if files else "(no files reported)"
        verdict: dict[str, Any] = {}

        async def read_file_handler(tool_input: dict) -> str:
            content = await self.artifacts.read(tool_input["path"])
            if len(content) > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + "\n…[truncated for review]"
            return content

        async def submit_review_handler(tool_input: dict) -> str:
            verdict.clear()
            verdict.update(tool_input)
            return "Review recorded."

        user_message = (
            f"Review the {phase_role} agent's artifact before it is accepted.\n\n"
            f"Task brief / phase objective:\n{brief or '(not provided)'}\n\n"
            f"Agent's own summary: {summary}\n\n"
            f"Files produced — read the ones you need with read_file:\n{file_list}\n\n"
            f"Judge spec compliance, drift, security, logic correctness, and standards. "
            f"Then call submit_review exactly once. Do not approve unless it genuinely meets the brief."
        )

        await self.run_tool_loop(
            user_message=user_message,
            tool_handlers={
                "read_file": read_file_handler,
                "submit_review": submit_review_handler,
            },
            dynamic_context=dynamic_context,
            tools=_REVIEWER_TOOLS,
            max_steps=24,
            scope_lock=False,  # reviewer reports drift via its verdict, doesn't defer work
        )

        if not verdict:
            return {
                "decision": "reject",
                "summary": "Reviewer returned no verdict; rejecting by default (silence is not approval).",
                "must_fix": ["Reviewer did not submit a verdict — resubmit the artifact for review."],
                "should_fix": [],
                "drift": [],
                "escalation_question": "",
            }

        verdict.setdefault("must_fix", [])
        verdict.setdefault("should_fix", [])
        verdict.setdefault("drift", [])
        verdict.setdefault("summary", "")
        verdict.setdefault("escalation_question", "")
        verdict["decision"] = str(verdict.get("decision", "reject")).lower()

        # Route any flagged drift to the persisted Known-Gaps log.
        if verdict["drift"]:
            from core.known_gaps import log_gap

            for item in verdict["drift"]:
                await log_gap(self.artifacts, f"reviewer:{phase_role}", "drift", str(item))

        return verdict
