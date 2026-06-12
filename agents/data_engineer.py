"""Data Engineer agent — builds ingestion, data contracts, and ETL/ELT pipelines.

Targets factory / industrial data (sensor & telemetry streams, MES/SCADA/historian batch
exports) so the downstream AI layer (see ``ml_engineer``) consumes validated, contracted data.

Profile-aware like the Backend developer's non-DailyEase path: it reads the approved
requirements/architecture, inspects any existing code via read tools, then writes pipeline and
contract files under ``profile.app_root`` using the project's stack.
"""

from core.message_types import Message, MessageType
from core.context import doc_reference
from core.paths import WORKSPACE, METADATA_ROOT
from core.profile import Profile, load_profile
from .base_agent import BaseAgent

_PREFER = [
    "sensor", "telemetry", "ingest", "pipeline", "schema", "contract", "etl", "elt",
    "stream", "batch", "quality", "validation", "warehouse", "lake", "partition", "asset",
]

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a pipeline, data-contract, or design file to the project",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the code root, e.g. pipelines/ingest_sensors.py "
                    "or data_contracts/telemetry.py or docs/data_engineering.md",
                },
                "content": {"type": "string", "description": "Complete file content — no truncation"},
            },
            "required": ["path", "content"],
        },
    },
]

_DESIGN_DOC = "docs/data_engineering.md"


def build_prompt(profile: Profile, *, sprint_goal: str, arch_content: str, req_content: str,
                 task_description: str, arch_path: str = "docs/architecture.md",
                 req_path: str = "docs/requirements.md") -> str:
    """Construct the data-engineering build prompt, profile-driven and path-first on upstream docs."""
    arch_block = doc_reference(arch_path, arch_content, label="Architecture Document",
                              digest_chars=2200, prefer=_PREFER)
    req_block = doc_reference(req_path, req_content, label="Requirements Summary",
                             digest_chars=1500, prefer=_PREFER)
    stack = ", ".join(profile.stack) if profile.stack else "the project's existing stack"
    return (
        f"Build the data engineering layer for this factory / industrial system.\n\n"
        f"Sprint goal (context): {sprint_goal}\n\n"
        f"{arch_block}"
        f"{req_block}"
        f"Task: {task_description}\n\n"
        f"First, inspect the repo: use read_file/list_files/grep_code to learn the existing layout, "
        f"data sources, and conventions before writing anything.\n\n"
        f"Then deliver, writing each file with write_file under {profile.app_root}/ using {stack}:\n"
        f"1. {_DESIGN_DOC} — sources (streaming + batch), explicit data contracts/schemas "
        f"(name, type, unit, range, nullability, keys), the pipeline DAG (extract → validate → "
        f"transform → load), the storage model (tables, partitioning by asset/line/time, retention), "
        f"and the data-quality rules.\n"
        f"2. Data-contract / schema definitions plus validation code that rejects (quarantines) bad rows.\n"
        f"3. Idempotent, restartable pipeline modules with clear extract/validate/transform/load stages.\n"
        f"4. A test or sample fixture proving the validation rejects out-of-range / malformed rows.\n\n"
        f"Make units explicit, keep pipelines replay-safe (a re-run must not double-load), and record "
        f"row/reject counts per run. Reply without a tool call only when all files are written."
    )


class DataEngineerAgent(BaseAgent):
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
        self.console.log(f"[cyan]DataEng[/cyan] starting: {task.get('deliverable', '')}")

        profile = load_profile(WORKSPACE, METADATA_ROOT)

        approved = task.get("approved_artifacts", {})
        arch_path = approved.get("architect_artifact", "docs/architecture.md")
        req_path = approved.get("pm_artifact", "docs/requirements.md")
        arch_content = await self.artifacts.read(arch_path)
        req_content = await self.artifacts.read(req_path)

        context = await self._build_dynamic_context()
        sprint_goal = task.get("sprint_goal", "")

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
            self.console.log(f"[cyan]DataEng[/cyan] wrote: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=build_prompt(
                profile,
                sprint_goal=sprint_goal,
                arch_content=arch_content,
                req_content=req_content,
                task_description=task["task_description"],
                arch_path=arch_path,
                req_path=req_path,
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=30,
            read_tools=True,
        )

        if not written_files:
            fallback = "# Data Engineering Design\n\n[Generated — no files emitted]\n"
            full_path = await self.artifacts.write(_DESIGN_DOC, fallback)
            written_files.append(str(full_path))

        primary_path = next((w for w in written_files if _DESIGN_DOC in w), written_files[0])
        await self.memory.remember("data_engineering_path", primary_path, "artifact_ref")

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": f"Data engineering layer written ({len(written_files)} files)",
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        async def _revise_cb(notes: str) -> None:
            await self._revise(notes, msg, written_files, primary_path)

        await self._await_reviews("DataEng", _revise_cb)

    async def _revise(self, notes: str, original_msg: Message, prior_files: list[str],
                      primary_path: str) -> None:
        context = await self._build_dynamic_context()
        files_summary = "\n".join(prior_files[:10])
        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            self.console.log(f"[cyan]DataEng[/cyan] revised: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=(
                f"Revise the data engineering layer based on this feedback:\n{notes}\n\n"
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
                "summary": f"Revised data engineering layer ({len(written_files)} files updated)",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
