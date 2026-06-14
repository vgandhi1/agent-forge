#!/usr/bin/env python3
"""AgentForge CLI: run multi-agent cycles, list artifacts, dry-run, or launch TUI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import core.paths as paths
import core.artifact_store as artifact_store
from core.paths import ROOT
from core.phases import PHASE_PRESETS, VALID_ROLES
from core.ollama_url import validate_ollama_base_url
from agents.base_agent import (
    LLMUnavailableError,
    anthropic_model_for_role,
    llm_provider,
    ollama_model_for_role,
)

load_dotenv()


def _configure_runtime_logging(verbose: bool, log_file: Path | None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    level = logging.DEBUG if verbose else logging.INFO
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_file is not None:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def _load_goal_file(path: Path, console: Console) -> str:
    if not path.exists():
        console.print(f"[red]Error: --goal-file path does not exist: {path}[/red]")
        raise SystemExit(2)
    if not path.is_file():
        console.print(f"[red]Error: --goal-file must be a regular file: {path}[/red]")
        raise SystemExit(2)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        err = e.strerror or type(e).__name__
        console.print(f"[red]Error: cannot read --goal-file ({err}). Check permissions.[/red]")
        raise SystemExit(2) from e


def _apply_target_repo(target_repo: Path | None, console: Console) -> None:
    """Re-root the code/metadata trees onto an existing repo (``--target-repo``).

    Security: the target must be an explicit, existing directory the caller named. Metadata is
    isolated under ``<target>/.agentforge`` so AgentForge never writes its bookkeeping into the
    user's source tree, and the SQLite DB stays under AGENTFORGE_ROOT.
    """
    if target_repo is None:
        return
    target = target_repo.expanduser().resolve()
    if not target.exists():
        console.print(f"[red]Error: --target-repo path does not exist: {target}[/red]")
        raise SystemExit(2)
    if not target.is_dir():
        console.print(f"[red]Error: --target-repo must be a directory: {target}[/red]")
        raise SystemExit(2)
    code_root, metadata_root = paths.resolve_roots(str(target))
    artifact_store.configure_roots(code_root, metadata_root)
    metadata_root.mkdir(parents=True, exist_ok=True)
    console.print(
        f"[cyan]Target repo:[/cyan] {code_root}\n"
        f"[dim]Metadata under {metadata_root} · DB stays at {paths.DB_PATH}[/dim]"
    )


DEFAULT_GOAL = """
Build the MVP of DailyEase — a daily life management platform impacting millions of users.

Required modules:
1. Task Management: create/update/delete tasks, set priorities and due dates, mark complete
2. Habit Tracking: define habits with frequency goals, log daily completions, track streaks
3. Personal Finance: log income/expenses with categories, set monthly budgets, view summaries
4. Wellness Reminders: schedule reminders for sleep, hydration, exercise, medication

Tech stack: FastAPI + SQLite + aiosqlite + SQLAlchemy 2.x (async) + Pydantic v2
Target: 100k+ concurrent users, sub-200ms API response time
"""


def _resolve_phases(preset: str | None, phases_csv: str | None) -> list[tuple[str, str]] | None:
    """Return phase list for the Lead orchestrator, or None to use the default full pipeline."""
    if phases_csv:
        roles = [p.strip() for p in phases_csv.split(",") if p.strip()]
        for r in roles:
            if r not in VALID_ROLES:
                raise SystemExit(f"Unknown role in --phases: {r!r}. Valid: {', '.join(VALID_ROLES)}")
        desc = "Execute this role per the sprint goal and Lead task assignment."
        return [(r, desc) for r in roles]

    key = (preset or "full").lower()
    if key == "full":
        return None
    if key not in PHASE_PRESETS:
        choices = ", ".join(sorted(["full", *PHASE_PRESETS]))
        raise SystemExit(f"Unknown --preset {preset!r}. Choose: {choices}")

    resolved = PHASE_PRESETS[key]
    assert resolved is not None
    return resolved


def _list_artifacts(console: Console) -> None:
    workspace = artifact_store.WORKSPACE
    if not workspace.exists():
        console.print("[yellow]No artifacts yet. Run a cycle first.[/yellow]")
        return

    table = Table(title="Generated Artifacts", show_header=True, header_style="bold cyan")
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Category")

    categories = {
        "docs/": "Documentation",
        "dailyease/models/": "Models",
        "dailyease/schemas/": "Schemas",
        "dailyease/routers/": "API Routers",
        "dailyease/services/": "Services",
        "dailyease/tests/": "Tests",
        "dailyease/": "App Core",
        "reports/": "Reports",
    }

    for f in sorted(workspace.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(workspace))
        size = f"{f.stat().st_size:,} bytes"
        category = "Other"
        for prefix, cat in categories.items():
            if rel.startswith(prefix):
                category = cat
                break
        table.add_row(rel, size, category)

    console.print(table)


async def _run_cycle(
    goal: str,
    phases: list[tuple[str, str]] | None,
    skip_summary: bool,
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
    """Returns True if the deploy was recorded, False if fail-closed (blocked/declined)."""
    console = Console()

    from core.memory import init_db
    from core.message_bus import MessageBus
    from core.artifact_store import ArtifactStore
    from agents.lead import LeadAgent
    from agents.product_manager import ProductManagerAgent
    from agents.architect import ArchitectAgent
    from agents.backend_developer import BackendDeveloperAgent
    from agents.qa_engineer import QAEngineerAgent
    from agents.devops_engineer import DevOpsEngineerAgent
    from agents.data_engineer import DataEngineerAgent
    from agents.ml_engineer import MLEngineerAgent
    from core.message_types import Message, MessageType

    await init_db()

    bus = MessageBus()
    store = ArtifactStore()

    agents_map = {
        "lead": LeadAgent("lead", bus, store, console),
        "pm": ProductManagerAgent("pm", bus, store, console),
        "architect": ArchitectAgent("architect", bus, store, console),
        "backend": BackendDeveloperAgent("backend", bus, store, console),
        "qa": QAEngineerAgent("qa", bus, store, console),
        "devops": DevOpsEngineerAgent("devops", bus, store, console),
        "data_engineer": DataEngineerAgent("data_engineer", bus, store, console),
        "ml_engineer": MLEngineerAgent("ml_engineer", bus, store, console),
    }

    worker_tasks = [
        asyncio.create_task(agent.run(), name=role)
        for role, agent in agents_map.items()
        if role != "lead"
    ]

    deploy_ok = True
    try:
        deploy_ok = await agents_map["lead"].run_development_cycle(
            goal,
            phases=phases,
            deploy_gate=deploy_gate,
            auto_approve=auto_approve,
            deploy_commit=deploy_commit,
            deploy_branch=deploy_branch,
            plan_gate=plan_gate,
            resume=resume,
            strict_review=strict_review,
            allow_quality_debt=allow_quality_debt,
            adaptive=adaptive,
        )
    finally:
        for role in [r for r in agents_map if r != "lead"]:
            await bus.publish(Message(
                type=MessageType.SHUTDOWN,
                sender="lead",
                recipient=role,
                payload={},
                priority=1,
            ))
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    return deploy_ok

    if skip_summary:
        return

    console.print()
    _list_artifacts(console)
    console.print(Panel(
        Text(
            f"All artifacts written to: {artifact_store.WORKSPACE}\n"
            f"Project root: {ROOT}\n"
            f"Run with --list-artifacts to see the file tree.",
            style="bold green",
        ),
        title="[bold green]AgentForge Sprint Complete[/bold green]",
        border_style="green",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AgentForge — multi-agent intake, design, implementation, testing, and delivery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Presets map to workflows: intake (PM), design (PM+architect), implement, test, ship, improve, full.\n"
            "Examples:\n"
            "  python main.py --preset intake --goal 'Capture login requirements'\n"
            "  python main.py --phases qa,devops --goal 'Harden CI and tests'\n"
            "  python main.py --tui\n"
            "  python main.py --web\n"
        ),
    )
    parser.add_argument("--tui", action="store_true", help="Launch interactive terminal UI (Textual)")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch local browser UI (http://127.0.0.1:8755 by default)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8755,
        help="Port for --web (default: 8755)",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="Bind address for --web (default: 127.0.0.1 loopback only)",
    )
    parser.add_argument("--goal", default=DEFAULT_GOAL, help="Sprint goal / intake text")
    parser.add_argument(
        "--goal-file",
        type=Path,
        default=None,
        help="Read sprint goal from file (overrides --goal when set)",
    )
    parser.add_argument(
        "--preset",
        default="full",
        help=f"Workflow preset (default: full). Choices: full, {', '.join(sorted(k for k in PHASE_PRESETS if k != 'full'))}",
    )
    parser.add_argument(
        "--phases",
        default=None,
        help="Override preset: comma-separated roles (pm,architect,backend,qa,devops)",
    )
    parser.add_argument(
        "--target-repo",
        type=Path,
        default=None,
        help="Operate on an existing repo at PATH (read/write/grep its tree) instead of the "
        "workspace/ sandbox. AgentForge metadata is isolated under <PATH>/.agentforge "
        "(env: AGENTFORGE_TARGET_REPO)",
    )
    parser.add_argument("--list-artifacts", action="store_true", help="List workspace files and exit")
    parser.add_argument("--dry-run", action="store_true", help="Show configuration and exit")
    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="Skip artifact table at end (for scripted / TUI subprocess runs)",
    )
    parser.add_argument(
        "--deploy-gate",
        action="store_true",
        help="Require human sign-off before the deploy step (env: AGENTFORGE_DEPLOY_GATE=1)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="With --deploy-gate, approve automatically (unattended deploys)",
    )
    parser.add_argument(
        "--deploy-commit",
        action="store_true",
        help="On deploy, git-commit the target repo (or the generated workspace/dailyease app in "
        "default mode) with a conventional-commit message (env: AGENTFORGE_DEPLOY_COMMIT=1)",
    )
    parser.add_argument(
        "--deploy-branch",
        default=None,
        metavar="NAME",
        help="With --deploy-commit, create/checkout this branch before committing (PR workflow)",
    )
    parser.add_argument(
        "--plan-gate",
        action="store_true",
        help="Backend shows a build plan for Lead confirmation before writing code "
        "(env: AGENTFORGE_PLAN_GATE=1)",
    )
    parser.add_argument(
        "--strict-review",
        action="store_true",
        help="Deprecated/no-op: blocking on unresolved review findings is now the default "
        "(env: AGENTFORGE_STRICT_REVIEW=1)",
    )
    parser.add_argument(
        "--allow-quality-debt",
        action="store_true",
        help="Ship even when artifacts were force-accepted with unresolved review findings "
        "(quality debt), flagging the debt instead of failing closed "
        "(env: AGENTFORGE_ALLOW_QUALITY_DEBT=1)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip phases already completed for the same goal (reads handoff/checkpoint.json)",
    )
    parser.add_argument(
        "--adaptive",
        action="store_true",
        help="Agentic mode: the Lead plans the phase sequence from the goal, re-routes on phase "
        "outcomes (e.g. QA failure → backend fix), and self-checks the goal is met before "
        "finishing (env: AGENTFORGE_ADAPTIVE=1)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging to stderr (agentforge loggers)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Append logs to this file (UTF-8), in addition to stderr when used with --verbose",
    )

    args = parser.parse_args()
    console = Console()

    if args.verbose or args.log_file is not None:
        _configure_runtime_logging(bool(args.verbose), args.log_file)
        logging.getLogger("agentforge").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    _apply_target_repo(args.target_repo, console)

    if args.tui:
        from tui_main import launch_tui

        launch_tui()
        return

    if args.web:
        try:
            from web_ui import run_server
        except ImportError as e:
            console.print(
                "[red]Web UI requires fastapi and uvicorn. "
                "Run: pip install -r requirements.txt[/red]"
            )
            raise SystemExit(1) from e
        console.print(
            f"[green]AgentForge web UI[/green] → http://{args.web_host}:{args.web_port}\n"
            f"[dim]Press Ctrl+C to stop.[/dim]"
        )
        run_server(host=args.web_host, port=args.web_port)
        return

    if args.list_artifacts:
        _list_artifacts(console)
        sys.exit(0)

    goal_text = args.goal
    if args.goal_file is not None:
        goal_text = _load_goal_file(args.goal_file.resolve(), console)

    phases = _resolve_phases(args.preset, args.phases)

    if args.dry_run:
        provider = llm_provider()
        thinking = os.getenv("AGENTFORGE_THINKING", "false")
        phase_desc = "default (full pipeline)" if phases is None else str([p[0] for p in phases])
        roles = ("lead", "pm", "architect", "backend", "qa", "devops",
                 "data_engineer", "ml_engineer", "reviewer")
        if provider == "ollama":
            try:
                ohost = validate_ollama_base_url(os.getenv("AGENTFORGE_OLLAMA_HOST", "http://127.0.0.1:11434"))
            except ValueError as e:
                ohost = f"(invalid AGENTFORGE_OLLAMA_HOST: {e})"
            model_lines = "\n".join(
                f"  {r}: {ollama_model_for_role(r)}" for r in roles
            )
            model_block = f"[bold]Ollama host:[/bold] {ohost}\n[bold]Per-role models:[/bold]\n{model_lines}"
        else:
            model_lines = "\n".join(
                f"  {r}: {anthropic_model_for_role(r)}" for r in roles
            )
            model_block = f"[bold]Per-role Anthropic models:[/bold]\n{model_lines}"
        gate_on = args.deploy_gate or os.getenv("AGENTFORGE_DEPLOY_GATE", "").strip().lower() in ("1", "true", "yes")
        commit_on = args.deploy_commit or os.getenv("AGENTFORGE_DEPLOY_COMMIT", "").strip().lower() in ("1", "true", "yes")
        gate_desc = "on" if gate_on else "off (autonomous)"
        if gate_on and args.auto_approve:
            gate_desc += " + auto-approve"
        console.print(Panel(
            f"[bold]LLM provider:[/bold] {provider}\n"
            f"{model_block}\n"
            f"[bold]Thinking:[/bold] {thinking}\n"
            f"[bold]ROOT:[/bold] {ROOT}\n"
            f"[bold]Workspace:[/bold] {artifact_store.WORKSPACE}\n"
            f"[bold]Preset:[/bold] {args.preset}\n"
            f"[bold]Phases:[/bold] {phase_desc}\n"
            f"[bold]Deploy gate:[/bold] {gate_desc}\n"
            f"[bold]Deploy commit:[/bold] {'on' if commit_on else 'off'}"
            f"{f' → branch {args.deploy_branch}' if (commit_on and args.deploy_branch) else ''}\n"
            f"[bold]Plan gate:[/bold] {'on (backend)' if (args.plan_gate or os.getenv('AGENTFORGE_PLAN_GATE', '').strip().lower() in ('1', 'true', 'yes')) else 'off'}\n"
            f"[bold]Adaptive:[/bold] {'on (plan + re-route + goal-check)' if (args.adaptive or os.getenv('AGENTFORGE_ADAPTIVE', '').strip().lower() in ('1', 'true', 'yes')) else 'off'}\n"
            f"[bold]Resume:[/bold] {'on' if args.resume else 'off'}\n\n"
            f"[bold]Sprint Goal:[/bold]\n{goal_text.strip()}",
            title="[cyan]AgentForge Dry Run[/cyan]",
        ))
        sys.exit(0)

    if llm_provider() != "ollama" and not os.getenv("ANTHROPIC_API_KEY"):
        console.print(
            "[red]Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key, "
            "or set AGENTFORGE_LLM_PROVIDER=ollama for local Ollama.[/red]"
        )
        sys.exit(1)

    if llm_provider() == "ollama":
        from agents.base_agent import ollama_chat_origin

        try:
            ollama_chat_origin()  # validates AGENTFORGE_OLLAMA_HOST up front
        except ValueError as e:
            console.print(Panel(
                f"[bold]Invalid AGENTFORGE_OLLAMA_HOST.[/bold]\n{e}\n\n"
                "Use a loopback URL (e.g. http://127.0.0.1:11434), or set "
                "AGENTFORGE_OLLAMA_TRUST_LAN=1 for a LAN/Docker/Windows-host address. "
                "See docs/ollama.md.",
                title="[red]Ollama config error[/red]",
                border_style="red",
            ))
            sys.exit(1)

    def _env_flag(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in ("1", "true", "yes")

    deploy_gate = args.deploy_gate or _env_flag("AGENTFORGE_DEPLOY_GATE")
    deploy_commit = args.deploy_commit or _env_flag("AGENTFORGE_DEPLOY_COMMIT")
    plan_gate = args.plan_gate or _env_flag("AGENTFORGE_PLAN_GATE")
    strict_review = args.strict_review or _env_flag("AGENTFORGE_STRICT_REVIEW")
    allow_quality_debt = args.allow_quality_debt or _env_flag("AGENTFORGE_ALLOW_QUALITY_DEBT")
    adaptive = args.adaptive or _env_flag("AGENTFORGE_ADAPTIVE")

    try:
        deploy_ok = asyncio.run(_run_cycle(
            goal_text,
            phases,
            skip_summary=args.skip_summary,
            deploy_gate=deploy_gate,
            auto_approve=args.auto_approve,
            deploy_commit=deploy_commit,
            deploy_branch=args.deploy_branch,
            plan_gate=plan_gate,
            resume=args.resume,
            strict_review=strict_review,
            allow_quality_debt=allow_quality_debt,
            adaptive=adaptive,
        ))
        if not deploy_ok:
            # Fail closed: blocked or declined deploy must surface as a non-zero exit so
            # automation and host assistants never read a flagged run as success.
            sys.exit(2)
    except LLMUnavailableError as e:
        console.print(Panel(
            f"[bold]{e.provider} is unreachable.[/bold]\n"
            f"Endpoint: {e.endpoint}\n"
            f"Detail: {e.detail}\n\n"
            f"{e.hint}",
            title="[red]LLM connection failed[/red]",
            border_style="red",
        ))
        sys.exit(1)


if __name__ == "__main__":
    main()
