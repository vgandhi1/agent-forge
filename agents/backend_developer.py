from core.message_bus import MessageBus
from core.message_types import Message, MessageType
from core.artifact_store import ArtifactStore
from core.context import condense_markdown, doc_reference
from core.paths import WORKSPACE, METADATA_ROOT
from core.profile import Profile, load_profile
from .base_agent import BaseAgent

_PREFER = ["task", "habit", "finance", "wellness", "schema", "api", "endpoint", "database", "model", "router"]

_TOOLS = [
    {
        "name": "write_file",
        "description": "Write a source file to the project",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the code root, e.g. src/main.py or src/routers/tasks.py",
                },
                "content": {"type": "string", "description": "Complete file content — no truncation"},
            },
            "required": ["path", "content"],
        },
    },
]

_REQUIRED_FILES = [
    "dailyease/main.py",
    "dailyease/database.py",
    "dailyease/requirements.txt",
    "dailyease/models/__init__.py",
    "dailyease/schemas/__init__.py",
    "dailyease/routers/__init__.py",
    "dailyease/services/__init__.py",
    "dailyease/models/task.py",
    "dailyease/models/habit.py",
    "dailyease/models/finance.py",
    "dailyease/models/wellness.py",
    "dailyease/schemas/task.py",
    "dailyease/schemas/habit.py",
    "dailyease/schemas/finance.py",
    "dailyease/schemas/wellness.py",
    "dailyease/routers/tasks.py",
    "dailyease/routers/habits.py",
    "dailyease/routers/finance.py",
    "dailyease/routers/wellness.py",
    "dailyease/services/task_service.py",
    "dailyease/services/habit_service.py",
    "dailyease/services/finance_service.py",
    "dailyease/services/wellness_service.py",
]


def required_files(profile: Profile) -> list[str]:
    """Return the fixed greenfield checklist only for the DailyEase default profile.

    Any other profile (improve/debug/fix/harden on an existing repo) gets no fixed checklist —
    the agent is expected to read existing code and write under ``profile.app_root``.
    """
    return list(_REQUIRED_FILES) if profile.app_root == "dailyease" else []


def build_prompt(profile: Profile, *, plan_notes: str, sprint_goal: str,
                 arch_content: str, req_content: str, task_description: str,
                 arch_path: str = "docs/architecture.md",
                 req_path: str = "docs/requirements.md") -> str:
    """Construct the backend build prompt, profile-driven.

    DailyEase default keeps the exact 23-file FastAPI checklist behavior; other profiles instruct
    the agent to inspect existing code first and write to ``profile.app_root`` using ``profile.stack``.

    Upstream docs are passed path-first (small digest + ``read_file`` pointer) rather than as a
    large inlined blob, so the agent can read the whole document on demand instead of losing the
    sections that condensing dropped.
    """
    arch_block = doc_reference(arch_path, arch_content, label="Architecture Document",
                               digest_chars=2200, prefer=_PREFER)
    req_block = doc_reference(req_path, req_content, label="Requirements Summary",
                              digest_chars=1500, prefer=_PREFER)

    if profile.app_root == "dailyease":
        files = required_files(profile)
        return (
            f"{plan_notes}"
            f"Implement the complete DailyEase FastAPI application.\n\n"
            f"Sprint goal (context): {sprint_goal}\n\n"
            f"{arch_block}"
            f"{req_block}"
            f"Task: {task_description}\n\n"
            f"Write ALL of these files using write_file — one call per file, "
            f"continuing across turns until every file is written:\n"
            + "\n".join(f"- {f}" for f in files)
            + "\n\nEvery file must be complete and functional. "
            f"Use SQLAlchemy 2.x async + aiosqlite + FastAPI + Pydantic v2. "
            f"Include proper error handling in all routers. "
            f"Reply without a tool call only when all files are written."
        )

    stack = ", ".join(profile.stack) if profile.stack else "the project's existing stack"
    return (
        f"{plan_notes}"
        f"Implement the change in the existing {profile.name} project.\n\n"
        f"Sprint goal (context): {sprint_goal}\n\n"
        f"{arch_block}"
        f"{req_block}"
        f"Task: {task_description}\n\n"
        f"First, read the existing code: use read_file/list_files/grep_code to understand the "
        f"current layout, conventions, and the code you need to change before writing anything. "
        f"Write your changes under {profile.app_root}/ using write_file (one call per file), "
        f"matching the existing style and using {stack} for tech choices. "
        f"Keep changes scoped to the task. "
        f"Reply without a tool call only when all changes are written."
    )


class BackendDeveloperAgent(BaseAgent):
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
        self.console.log(f"[green]Backend[/green] starting: {task.get('deliverable', '')}")

        profile = load_profile(WORKSPACE, METADATA_ROOT)
        checklist = required_files(profile)

        approved_artifacts = task.get("approved_artifacts", {})
        arch_path = approved_artifacts.get("architect_artifact", "docs/architecture.md")
        req_path = approved_artifacts.get("pm_artifact", "docs/requirements.md")

        arch_content = await self.artifacts.read(arch_path)
        req_content = await self.artifacts.read(req_path)

        context = await self._build_dynamic_context()

        sprint_goal = task.get("sprint_goal", "")

        plan_notes = ""
        if task.get("plan_gate"):
            plan_notes = await self._propose_plan(arch_content, req_content, task, context)

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            await self.memory.remember(f"wrote_{path}", str(full_path), "artifact_ref")
            self.console.log(f"[green]Backend[/green] wrote: {full_path}")
            size = len(tool_input.get("content", ""))
            if not checklist:
                return f"Wrote {path} ({size} bytes)."
            remaining = [f for f in checklist if not any(f in w for w in written_files)]
            hint = (
                f" {len(remaining)} required files still missing: {', '.join(remaining[:5])}"
                + ("…" if len(remaining) > 5 else "")
                if remaining
                else " All required files written."
            )
            return f"Wrote {path} ({size} bytes).{hint}"

        await self.run_tool_loop(
            user_message=build_prompt(
                profile,
                plan_notes=plan_notes,
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
            max_steps=40,
            read_tools=True,
        )

        primary_path = written_files[0] if written_files and not checklist else "dailyease/main.py"

        await self.bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.role,
            recipient="lead",
            payload={
                "files": written_files,
                "primary_path": primary_path,
                "path": primary_path,
                "summary": (
                    f"DailyEase FastAPI app implemented ({len(written_files)} files)"
                    if checklist
                    else f"Implementation written ({len(written_files)} files)"
                ),
            },
            correlation_id=msg.message_id,
            priority=2,
        ))

        async def _revise_cb(notes: str) -> None:
            await self._revise(notes, msg, written_files, primary_path)

        await self._await_reviews("Backend", _revise_cb)

    async def _propose_plan(self, arch_content: str, req_content: str, task: dict, context: str) -> str:
        """Show a build plan to the Lead and wait for confirmation before writing code.

        Returns redirect notes to fold into the build (empty string if approved or no response).
        """
        response = await self._call_llm(
            user_message=(
                "Before writing any code, produce a concise build plan: the file groups you will "
                "create, key technical decisions, and anything you are uncertain about. No code yet.\n\n"
                f"Task: {task['task_description']}\n\n"
                f"Architecture:\n```markdown\n{condense_markdown(arch_content, 4000, _PREFER)}\n```\n\n"
                f"Requirements:\n```markdown\n{condense_markdown(req_content, 2000, _PREFER)}\n```"
            ),
            dynamic_context=context,
        )
        plan = self._extract_text(response)
        self.console.log("[green]Backend[/green] submitted build plan for confirmation")
        await self.bus.publish(Message(
            type=MessageType.CONSULT_REQUEST,
            sender=self.role,
            recipient="lead",
            payload={"kind": "build_plan", "plan": plan},
            priority=2,
        ))
        resp = await self.bus.receive(self.role, timeout=300.0)
        if resp and resp.type == MessageType.CONSULT_RESPONSE:
            if resp.payload.get("approved"):
                self.console.log("[green]Backend[/green] plan approved — building")
                return ""
            notes = resp.payload.get("notes", "")
            self.console.log(f"[yellow]Backend[/yellow] plan redirected: {notes[:80]}")
            return f"Architect redirected your plan — incorporate this before building:\n{notes}\n\n"
        return ""

    async def _revise(self, notes: str, original_msg: Message, prior_files: list[str],
                      primary_path: str = "dailyease/main.py") -> None:
        context = await self._build_dynamic_context()
        files_summary = "\n".join(prior_files[:10])

        written_files: list[str] = []

        async def write_file_handler(tool_input: dict) -> str:
            path = tool_input["path"]
            full_path = await self.artifacts.write(path, tool_input["content"])
            written_files.append(str(full_path))
            self.console.log(f"[green]Backend[/green] revised: {full_path}")
            return f"Wrote {path} ({len(tool_input.get('content', ''))} bytes)."

        await self.run_tool_loop(
            user_message=(
                f"Revise the implementation based on this feedback:\n{notes}\n\n"
                f"Files already written:\n{files_summary}\n\n"
                f"Write corrected files using write_file (one call per file). "
                f"Reply without a tool call only when all fixes are written."
            ),
            tool_handlers={"write_file": write_file_handler},
            dynamic_context=context,
            tools=_TOOLS,
            max_steps=40,
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
                "summary": f"Revised implementation ({len(written_files)} files updated)",
            },
            correlation_id=original_msg.message_id,
            priority=2,
        ))
