"""Textual TUI for AgentForge — run presets from the terminal with streamed logs."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static

REPO_ROOT = Path(__file__).resolve().parent


class AgentForgeTui(App[None]):
    CSS = """
    Screen { align: center middle; }
    #main { width: 100%; height: 100%; padding: 1 2; }
    #goal_input { width: 100%; min-height: 3; }
    #log { height: 1fr; border: solid $primary; min-height: 12; }
    #buttons Horizontal { height: auto; margin-top: 1; }
    Button { margin-right: 1; }
    #hint { margin-top: 1; color: $text-muted; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            yield Static("AgentForge — intake, design, implement, test, ship", classes="title")
            yield Label("Sprint goal / intake request")
            yield Input(placeholder="Describe what you want built, tested, or improved…", id="goal_input")
            with Horizontal(id="buttons"):
                yield Button("Full pipeline", id="btn_full", variant="primary")
                yield Button("Intake", id="btn_intake")
                yield Button("Design", id="btn_design")
                yield Button("Implement", id="btn_implement")
                yield Button("Test", id="btn_test")
                yield Button("Ship", id="btn_ship")
                yield Button("Improve", id="btn_improve")
            yield RichLog(id="log", highlight=True, markup=True)
            yield Static(
                "Runs the same CLI as Claude Code / terminal: Python subprocess, Rich logs here. "
                "Requires ANTHROPIC_API_KEY in the environment or .env next to main.py.",
                id="hint",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#goal_input", Input).value = os.environ.get("AGENTFORGE_DEFAULT_GOAL", "").strip()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        preset_map = {
            "btn_full": "full",
            "btn_intake": "intake",
            "btn_design": "design",
            "btn_implement": "implement",
            "btn_test": "test",
            "btn_ship": "ship",
            "btn_improve": "improve",
        }
        pid = event.button.id or ""
        preset = preset_map.get(pid)
        if not preset:
            return
        goal = self.query_one("#goal_input", Input).value.strip()
        if not goal:
            self.query_one(RichLog).write("[yellow]Set a sprint goal first.[/yellow]")
            return
        self.run_subprocess(preset, goal)

    @work(exclusive=True)
    async def run_subprocess(self, preset: str, goal: str) -> None:
        log = self.query_one(RichLog)
        log.clear()
        log.write(f"[cyan]Starting preset=[/cyan][bold]{preset}[/bold] …")

        main_py = REPO_ROOT / "main.py"
        if not main_py.is_file():
            log.write("[red]main.py not found next to tui_main.py[/red]")
            return

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".md",
            delete=False,
        ) as tmp:
            tmp.write(goal)
            goal_path = tmp.name

        env = os.environ.copy()
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(main_py),
            "--preset",
            preset,
            "--goal-file",
            goal_path,
            "--skip-summary",
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )

        assert proc.stdout is not None
        code = -1
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    log.write(line.decode("utf-8", errors="replace").rstrip())
                except Exception:
                    log.write("[dim](log line omitted)[/dim]")

            code = await proc.wait()
        finally:
            try:
                os.unlink(goal_path)
            except OSError:
                pass
        if code == 0:
            log.write("[green]Done.[/green] Use CLI --list-artifacts or open workspace/ for outputs.")
        else:
            log.write(f"[red]Exited with code {code}[/red]")


def launch_tui() -> None:
    AgentForgeTui().run()
