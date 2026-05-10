#!/usr/bin/env python3
"""AgentForge CLI: run multi-agent cycles, list artifacts, dry-run, or launch TUI."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.paths import ROOT, WORKSPACE
from core.phases import DEFAULT_PHASES, PHASE_PRESETS, VALID_ROLES

load_dotenv()

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
    """Return phase list for CEO, or None to use DEFAULT_PHASES."""
    if phases_csv:
        roles = [p.strip() for p in phases_csv.split(",") if p.strip()]
        for r in roles:
            if r not in VALID_ROLES:
                raise SystemExit(f"Unknown role in --phases: {r!r}. Valid: {', '.join(VALID_ROLES)}")
        desc = "Execute this role per the sprint goal and CEO task assignment."
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
    if not WORKSPACE.exists():
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

    for f in sorted(WORKSPACE.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(WORKSPACE))
        size = f"{f.stat().st_size:,} bytes"
        category = "Other"
        for prefix, cat in categories.items():
            if rel.startswith(prefix):
                category = cat
                break
        table.add_row(rel, size, category)

    console.print(table)


async def _run_cycle(goal: str, phases: list[tuple[str, str]] | None, skip_summary: bool) -> None:
    console = Console()

    from core.memory import init_db
    from core.message_bus import MessageBus
    from core.artifact_store import ArtifactStore
    from agents.ceo import CEOAgent
    from agents.product_manager import ProductManagerAgent
    from agents.architect import ArchitectAgent
    from agents.backend_developer import BackendDeveloperAgent
    from agents.qa_engineer import QAEngineerAgent
    from agents.devops_engineer import DevOpsEngineerAgent
    from core.message_types import Message, MessageType

    await init_db()

    bus = MessageBus()
    store = ArtifactStore()

    agents_map = {
        "ceo": CEOAgent("ceo", bus, store, console),
        "pm": ProductManagerAgent("pm", bus, store, console),
        "architect": ArchitectAgent("architect", bus, store, console),
        "backend": BackendDeveloperAgent("backend", bus, store, console),
        "qa": QAEngineerAgent("qa", bus, store, console),
        "devops": DevOpsEngineerAgent("devops", bus, store, console),
    }

    worker_tasks = [
        asyncio.create_task(agent.run(), name=role)
        for role, agent in agents_map.items()
        if role != "ceo"
    ]

    try:
        await agents_map["ceo"].run_development_cycle(goal, phases=phases)
    finally:
        for role in ["pm", "architect", "backend", "qa", "devops"]:
            await bus.publish(Message(
                type=MessageType.SHUTDOWN,
                sender="ceo",
                recipient=role,
                payload={},
                priority=1,
            ))
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    if skip_summary:
        return

    console.print()
    _list_artifacts(console)
    console.print(Panel(
        Text(
            f"All artifacts written to: {WORKSPACE}\n"
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
    parser.add_argument("--list-artifacts", action="store_true", help="List workspace files and exit")
    parser.add_argument("--dry-run", action="store_true", help="Show configuration and exit")
    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="Skip artifact table at end (for scripted / TUI subprocess runs)",
    )

    args = parser.parse_args()
    console = Console()

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
        goal_text = args.goal_file.read_text(encoding="utf-8")

    phases = _resolve_phases(args.preset, args.phases)

    if args.dry_run:
        model = os.getenv("AGENTFORGE_MODEL", "claude-sonnet-4-6")
        thinking = os.getenv("AGENTFORGE_THINKING", "false")
        phase_desc = "default (full pipeline)" if phases is None else str([p[0] for p in phases])
        console.print(Panel(
            f"[bold]Model:[/bold] {model}\n"
            f"[bold]Thinking:[/bold] {thinking}\n"
            f"[bold]ROOT:[/bold] {ROOT}\n"
            f"[bold]Workspace:[/bold] {WORKSPACE}\n"
            f"[bold]Preset:[/bold] {args.preset}\n"
            f"[bold]Phases:[/bold] {phase_desc}\n\n"
            f"[bold]Sprint Goal:[/bold]\n{goal_text.strip()}",
            title="[cyan]AgentForge Dry Run[/cyan]",
        ))
        sys.exit(0)

    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print(
            "[red]Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.[/red]"
        )
        sys.exit(1)

    asyncio.run(_run_cycle(goal_text, phases, skip_summary=args.skip_summary))


if __name__ == "__main__":
    main()
