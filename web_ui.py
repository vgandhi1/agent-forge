"""
Local browser UI for AgentForge (127.0.0.1 only).

Streams the same subprocess as CLI/TUI; presets and goals are validated server-side.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

from core.phases import PHASE_PRESETS

REPO_ROOT = Path(__file__).resolve().parent
MAIN_PY = REPO_ROOT / "main.py"

ALLOWED_PRESETS = frozenset(["full", *PHASE_PRESETS.keys()])
MAX_GOAL_CHARS = 500_000

_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AgentForge</title>
  <style>
    :root { font-family: system-ui, sans-serif; }
    body { max-width: 56rem; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.25rem; }
    label { display: block; margin-top: 1rem; font-weight: 600; }
    select, textarea, button { width: 100%; box-sizing: border-box; margin-top: 0.35rem; }
    textarea { min-height: 10rem; font-family: ui-monospace, monospace; font-size: 0.9rem; }
    button { margin-top: 1rem; padding: 0.6rem 1rem; cursor: pointer; max-width: 12rem; }
    #log {
      margin-top: 1.5rem; white-space: pre-wrap; background: #111; color: #e6e6e6;
      padding: 1rem; border-radius: 6px; min-height: 12rem; max-height: 28rem; overflow: auto;
      font-size: 0.8rem;
    }
    .hint { color: #555; font-size: 0.85rem; margin-top: 0.5rem; }
    .err { color: #b00020; margin-top: 0.5rem; }
  </style>
</head>
<body>
  <h1>AgentForge — local team runner</h1>
  <p>Runs the same agent pipeline as the terminal. Requires <code>ANTHROPIC_API_KEY</code> in the environment or <code>.env</code> next to <code>main.py</code>.</p>

  <label for="preset">Preset</label>
  <select id="preset" aria-label="Workflow preset">
    <option value="full">full — PM → architect → backend → QA → DevOps</option>
    <option value="intake">intake — PM requirements only</option>
    <option value="design">design — PM + architect</option>
    <option value="implement">implement — backend only</option>
    <option value="test">test — QA + pytest</option>
    <option value="ship">ship — DevOps only</option>
    <option value="improve">improve — backend + QA</option>
  </select>

  <label for="goal">Sprint goal / intake</label>
  <textarea id="goal" placeholder="Describe what to build, test, or ship…"></textarea>
  <p class="hint">Output files go to <code>workspace/</code> under the project root. Logs stream below.</p>

  <button type="button" id="run">Run team</button>
  <p id="status" class="hint"></p>
  <p id="error" class="err" role="alert"></p>
  <div id="log" aria-live="polite"></div>

  <script>
    const logEl = document.getElementById("log");
    const errEl = document.getElementById("error");
    const statusEl = document.getElementById("status");

    function appendLog(text) {
      logEl.textContent += text;
      logEl.scrollTop = logEl.scrollHeight;
    }

    document.getElementById("run").addEventListener("click", async () => {
      errEl.textContent = "";
      logEl.textContent = "";
      const preset = document.getElementById("preset").value;
      const goal = document.getElementById("goal").value;
      statusEl.textContent = "Connecting…";

      const wsProto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(wsProto + "://" + location.host + "/ws/run");

      ws.onopen = () => {
        statusEl.textContent = "Running…";
        ws.send(JSON.stringify({ preset, goal }));
      };

      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { appendLog(ev.data + "\\n"); return; }
        if (msg.type === "line") appendLog(msg.text + "\\n");
        else if (msg.type === "exit") {
          statusEl.textContent = msg.code === 0 ? "Finished." : "Finished with exit " + msg.code;
          ws.close();
        } else if (msg.type === "error") {
          errEl.textContent = msg.message || "Error";
          statusEl.textContent = "";
          ws.close();
        }
      };

      ws.onerror = () => {
        errEl.textContent = "WebSocket error (is the server running?)";
        statusEl.textContent = "";
      };
    });
  </script>
</body>
</html>
"""


def create_app() -> FastAPI:
    app = FastAPI(title="AgentForge Web UI", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.websocket("/ws/run")
    async def run_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            raw = await websocket.receive_text()
            data = json.loads(raw)
        except (json.JSONDecodeError, WebSocketDisconnect):
            await websocket.send_json({"type": "error", "message": "Invalid message"})
            return

        preset = str(data.get("preset", "full")).lower()
        goal = str(data.get("goal", ""))

        if preset not in ALLOWED_PRESETS:
            await websocket.send_json({"type": "error", "message": "Invalid preset"})
            return
        if not goal.strip():
            await websocket.send_json({"type": "error", "message": "Goal cannot be empty"})
            return
        if len(goal) > MAX_GOAL_CHARS:
            await websocket.send_json({"type": "error", "message": "Goal too long"})
            return

        if not MAIN_PY.is_file():
            await websocket.send_json({"type": "error", "message": "main.py not found on server"})
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
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(MAIN_PY),
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
        except OSError as e:
            try:
                os.unlink(goal_path)
            except OSError:
                pass
            await websocket.send_json({"type": "error", "message": "Failed to start process"})
            return

        assert proc.stdout is not None
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                await websocket.send_json({"type": "line", "text": text.rstrip("\r\n")})
            code = await proc.wait()
            await websocket.send_json({"type": "exit", "code": int(code or 0)})
        except (WebSocketDisconnect, asyncio.CancelledError):
            proc.kill()
        finally:
            try:
                os.unlink(goal_path)
            except OSError:
                pass

    return app


def run_server(host: str = "127.0.0.1", port: int = 8755) -> None:
    """Bind to loopback only by default (local development)."""
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
