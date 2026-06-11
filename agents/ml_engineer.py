"""AI/ML Engineer agent — builds the machine-learning layer on top of validated factory data.

Consumes the Data Engineer's contracts (see ``data_engineer``) and delivers feature engineering,
model training/evaluation, and an input-validating inference path for industrial AI use cases
(predictive maintenance, anomaly detection, quality/defect prediction).

Profile-aware like the Backend developer's non-DailyEase path.
"""

from core.message_types import Message, MessageType
from core.context import doc_reference
from core.paths import WORKSPACE, METADATA_ROOT
from core.profile import Profile, load_profile
from .base_agent import BaseAgent

_PREFER = [
    "feature", "model", "train", "evaluation", "metric", "predict", "inference", "serving",
    "anomaly", "maintenance", "quality", "baseline", "leakage", "drift", "contract", "sensor",
]

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a feature, training, evaluation, serving, or design file to the project",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the code root, e.g. ml/features.py, ml/train.py, "
                    "ml/serve.py, or docs/ml_design.md",
                },
                "content": {"type": "string", "description": "Complete file content — no truncation"},
            },
            "required": ["path", "content"],
        },
    },
]

_DESIGN_DOC = "docs/ml_design.md"


def build_prompt(profile: Profile, *, sprint_goal: str, data_content: str, req_content: str,
                 task_description: str, data_path: str = "docs/data_engineering.md",
                 req_path: str = "docs/requirements.md") -> str:
    """Construct the ML build prompt: path-first on the data-engineering contract and requirements."""
    data_block = doc_reference(data_path, data_content, label="Data Engineering Contract",
                              digest_chars=2200, prefer=_PREFER)
    req_block = doc_reference(req_path, req_content, label="Requirements Summary",
                             digest_chars=1500, prefer=_PREFER)
    stack = ", ".join(profile.stack) if profile.stack else "the project's existing stack"
    return (
        f"Build the AI/ML layer for this factory / industrial system on top of the curated, "
        f"contracted data the Data Engineer produced.\n\n"
        f"Sprint goal (context): {sprint_goal}\n\n"
        f"{data_block}"
        f"{req_block}"
        f"Task: {task_description}\n\n"
        f"First, inspect the repo and the data contracts: use read_file/list_files/grep_code to learn "
        f"the available validated features before modeling. Do NOT invent raw ingestion — consume the "
        f"Data Engineer's contracts.\n\n"
        f"Then deliver, writing each file with write_file under {profile.app_root}/ using {stack}:\n"
        f"1. {_DESIGN_DOC} — problem framing (and the cost of a wrong prediction: false alarm vs missed "
        f"failure), feature definitions, a baseline + the chosen model, the evaluation plan (time-ordered "
        f"split, no leakage), the metrics that match the problem, and the key risks.\n"
        f"2. A feature-engineering module reused by BOTH training and serving (no train/serve skew).\n"
        f"3. Training + evaluation code that is reproducible (seeded, config-driven), reports metrics "
        f"against a baseline, and saves a model artifact.\n"
        f"4. An inference/serving module that validates inputs against the data contract and handles "
        f"missing / out-of-range values explicitly.\n"
        f"5. A test proving the evaluation is reproducible and serving rejects malformed input.\n\n"
        f"Fit transforms on train only, reuse the exact features at serving, and tune the decision "
        f"threshold to the failure mode. Reply without a tool call only when all files are written."
    )


class MLEngineerAgent(BaseAgent):
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
        self.console.log(f"[magenta]MLEng[/magenta] starting: {task.get('deliverable', '')}")

        profile = load_profile(WORKSPACE, METADATA_ROOT)

        approved = task.get("approved_artifacts", {})
        # Prefer the Data Engineer's contract; fall back to architecture if data phase was skipped.
        data_path = approved.get("data_engineer_artifact") or approved.get(
            "architect_artifact", "docs/data_engineering.md")
        req_path = approved.get("pm_artifact", "docs/requirements.md")
        data_content = await self.artifacts.read(data_path)
        req_content = await self.artifacts.read(req_path)

        context = await self._build_dynamic_context()
        sprint_goal = task.get("sprint_goal", "")

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
            self.console.log(f"[magenta]MLEng[/magenta] wrote: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=build_prompt(
                profile,
                sprint_goal=sprint_goal,
                data_content=data_content,
                req_content=req_content,
                task_description=task["task_description"],
                data_path=data_path,
                req_path=req_path,
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=30,
            read_tools=True,
        )

        if not written_files:
            fallback = "# ML Design\n\n[Generated — no files emitted]\n"
            full_path = await self.artifacts.write(_DESIGN_DOC, fallback)
            written_files.append(str(full_path))

        primary_path = next((w for w in written_files if _DESIGN_DOC in w), written_files[0])
        await self.memory.remember("ml_design_path", primary_path, "artifact_ref")

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"ML layer written ({len(written_files)} files)",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        async def _revise_cb(notes: str) -> None:
            await self._revise(notes, msg, written_files, primary_path)

        await self._await_reviews("MLEng", _revise_cb)

    async def _revise(self, notes: str, original_msg: Message, prior_files: list[str],
                      primary_path: str) -> None:
        context = await self._build_dynamic_context()
        files_summary = "\n".join(prior_files[:10])
        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            self.console.log(f"[magenta]MLEng[/magenta] revised: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=(
                f"Revise the ML layer based on this feedback:\n{notes}\n\n"
                f"Files already written:\n{files_summary}\n\n"
                f"Write corrected files using write_file (one call per file). "
                f"Reply without a tool call only when all fixes are written."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=30,
            read_tools=True,
        )

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"Revised ML layer ({len(written_files)} files updated)",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
