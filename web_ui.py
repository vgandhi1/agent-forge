"""
Local browser UI for AgentForge (127.0.0.1 only).

Streams the same subprocess as CLI/TUI; presets and goals are validated server-side.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
import uvicorn

from core.phases import PHASE_PRESETS

REPO_ROOT = Path(__file__).resolve().parent
MAIN_PY = REPO_ROOT / "main.py"

ALLOWED_PRESETS = frozenset(["full", *PHASE_PRESETS.keys()])
MAX_GOAL_CHARS = 500_000

# Browsers request /favicon.ico by default; serve SVG at both paths (Content-Type: image/svg+xml).
_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#0e1116"/>
  <path fill="#e8a54b" d="M9 22 16 10l7 12h-5v4h-6v-4H9Z"/>
</svg>"""

_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="color-scheme" content="dark"/>
  <title>AgentForge</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml"/>
  <link rel="alternate icon" href="/favicon.ico"/>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    :root {
      --bg-0: #060708;
      --bg-1: #0e1116;
      --card: rgba(16, 20, 28, 0.72);
      --stroke: rgba(232, 165, 75, 0.22);
      --stroke-strong: rgba(232, 165, 75, 0.45);
      --accent: #e8a54b;
      --accent-glow: rgba(232, 165, 75, 0.35);
      --text: #eef0f4;
      --muted: #8b93a3;
      --success: #6ee7a8;
      --danger: #ff8a8a;
      --mono: "JetBrains Mono", ui-monospace, monospace;
      --sans: "Outfit", system-ui, sans-serif;
      --radius: 16px;
      --radius-sm: 10px;
    }
    *, *::before, *::after { box-sizing: border-box; }
    html { height: 100%; }
    body {
      margin: 0;
      min-height: 100%;
      font-family: var(--sans);
      color: var(--text);
      background: var(--bg-0);
      background-image:
        radial-gradient(ellipse 120% 80% at 50% -20%, rgba(232, 165, 75, 0.14), transparent 55%),
        radial-gradient(ellipse 60% 50% at 100% 0%, rgba(90, 140, 255, 0.06), transparent 45%),
        linear-gradient(180deg, var(--bg-1) 0%, var(--bg-0) 40%);
      line-height: 1.5;
    }
    .noise {
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: 0.035;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
      z-index: 0;
    }
    .wrap {
      position: relative;
      z-index: 1;
      max-width: 920px;
      margin: 0 auto;
      padding: 2.5rem 1.25rem 3rem;
    }
    header {
      text-align: center;
      margin-bottom: 2rem;
    }
    .brand {
      font-size: clamp(2rem, 5vw, 2.75rem);
      font-weight: 700;
      letter-spacing: -0.03em;
      margin: 0 0 0.35rem;
      background: linear-gradient(135deg, #fff 0%, var(--accent) 55%, #c77d2e 100%);
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }
    .tagline {
      color: var(--muted);
      font-size: 1.05rem;
      font-weight: 500;
      margin: 0 0 1rem;
    }
    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      justify-content: center;
    }
    .badge {
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 0.35rem 0.75rem;
      border-radius: 999px;
      border: 1px solid var(--stroke);
      background: rgba(255,255,255,0.03);
      color: var(--muted);
    }
    .badge-accent { border-color: var(--stroke-strong); color: var(--accent); }
    .card {
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      background: var(--card);
      border: 1px solid var(--stroke);
      border-radius: var(--radius);
      padding: 1.75rem 1.75rem 1.5rem;
      box-shadow:
        0 0 0 1px rgba(255,255,255,0.04) inset,
        0 24px 48px -24px rgba(0,0,0,0.6),
        0 0 80px -40px var(--accent-glow);
    }
    .field { margin-bottom: 1.25rem; }
    .field:last-of-type { margin-bottom: 1rem; }
    label {
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin-bottom: 0.5rem;
    }
    select, textarea {
      width: 100%;
      font-family: inherit;
      font-size: 1rem;
      color: var(--text);
      background: rgba(6, 8, 10, 0.65);
      border: 1px solid var(--stroke);
      border-radius: var(--radius-sm);
      padding: 0.75rem 1rem;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    select {
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='%23e8a54b' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 1rem center;
      padding-right: 2.5rem;
    }
    select:hover, textarea:hover { border-color: var(--stroke-strong); }
    select:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    textarea {
      min-height: 11rem;
      resize: vertical;
      line-height: 1.55;
    }
    textarea::placeholder { color: var(--muted); opacity: 0.7; }
    .hint {
      font-size: 0.85rem;
      color: var(--muted);
      margin: 0.5rem 0 0;
    }
    .hint code {
      font-family: var(--mono);
      font-size: 0.82em;
      color: var(--accent);
      background: rgba(232, 165, 75, 0.08);
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 1rem;
      margin-top: 0.25rem;
    }
    #run {
      font-family: var(--sans);
      font-size: 1rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      color: #0a0c0f;
      background: linear-gradient(165deg, #ffd089 0%, var(--accent) 45%, #c77d2e 100%);
      border: none;
      border-radius: var(--radius-sm);
      padding: 0.85rem 1.75rem;
      cursor: pointer;
      box-shadow: 0 4px 20px -4px var(--accent-glow);
      transition: transform 0.15s, box-shadow 0.2s, filter 0.2s;
    }
    #run:hover:not(:disabled) {
      filter: brightness(1.06);
      box-shadow: 0 8px 28px -6px var(--accent-glow);
      transform: translateY(-1px);
    }
    #run:active:not(:disabled) { transform: translateY(0); }
    #run:disabled {
      opacity: 0.55;
      cursor: not-allowed;
      filter: grayscale(0.3);
    }
    #status {
      font-size: 0.9rem;
      font-weight: 500;
      color: var(--muted);
      margin: 0;
      min-height: 1.35em;
    }
    #status.running { color: var(--accent); }
    #status.done { color: var(--success); }
    #status.bad { color: var(--danger); }
    #error {
      margin: 0.75rem 0 0;
      padding: 0.75rem 1rem;
      border-radius: var(--radius-sm);
      background: rgba(255, 100, 100, 0.08);
      border: 1px solid rgba(255, 138, 138, 0.35);
      color: var(--danger);
      font-size: 0.9rem;
      display: none;
    }
    #error:not(:empty) { display: block; }
    .console-wrap {
      margin-top: 1.75rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--stroke);
      overflow: hidden;
      background: rgba(4, 5, 7, 0.9);
      box-shadow: 0 0 40px -20px rgba(0,0,0,0.8) inset;
    }
    .console-head {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.6rem 1rem;
      background: rgba(255,255,255,0.03);
      border-bottom: 1px solid var(--stroke);
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
    }
    .dots { display: flex; gap: 6px; margin-right: 0.5rem; }
    .dots span {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--stroke);
    }
    .dots span:nth-child(1) { background: #ff6b6b; opacity: 0.85; }
    .dots span:nth-child(2) { background: #ffd166; opacity: 0.85; }
    .dots span:nth-child(3) { background: #6ee7a8; opacity: 0.85; }
    #log {
      margin: 0;
      padding: 1rem 1.1rem 1.25rem;
      min-height: 14rem;
      max-height: min(42vh, 420px);
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--mono);
      font-size: 0.8rem;
      line-height: 1.55;
      color: #c8cdd8;
      scrollbar-width: thin;
      scrollbar-color: var(--stroke-strong) transparent;
    }
    #log::-webkit-scrollbar { width: 8px; }
    #log::-webkit-scrollbar-thumb {
      background: var(--stroke-strong);
      border-radius: 4px;
    }
    .empty-log { color: var(--muted); font-style: italic; }
    footer {
      text-align: center;
      margin-top: 2rem;
      font-size: 0.8rem;
      color: var(--muted);
    }
    footer a { color: var(--accent); text-decoration: none; }
    footer a:hover { text-decoration: underline; }
    @media (prefers-reduced-motion: reduce) {
      #run { transition: none; }
    }
  </style>
</head>
<body>
  <div class="noise" aria-hidden="true"></div>
  <div class="wrap">
    <header>
      <h1 class="brand">AgentForge</h1>
      <p class="tagline">Run your multi-agent team from the browser — same pipeline as the CLI.</p>
      <div class="badges">
        <span class="badge badge-accent">Local</span>
        <span class="badge">Lead · PM · Architect · Backend · QA · DevOps</span>
        <span class="badge">Live log stream</span>
      </div>
    </header>

    <div class="card">
      <div class="field">
        <label for="preset">Workflow preset</label>
        <select id="preset" aria-label="Workflow preset">
          <option value="full">Full pipeline — PM → architect → backend → QA → DevOps</option>
          <option value="intake">Intake — requirements only</option>
          <option value="design">Design — PM + architect</option>
          <option value="implement">Implement — backend only</option>
          <option value="test">Test — QA + pytest</option>
          <option value="ship">Ship — DevOps only</option>
          <option value="improve">Improve — backend + QA</option>
        </select>
      </div>
      <div class="field">
        <label for="goal">Sprint goal / intake</label>
        <textarea id="goal" placeholder="Describe what to build, test, ship, or improve. Be specific — your Lead agent delegates from this."></textarea>
        <p class="hint">Artifacts are written to <code>workspace/</code> in the project root. Ensure <code>ANTHROPIC_API_KEY</code> is set (e.g. in <code>.env</code>).</p>
      </div>
      <div class="actions">
        <button type="button" id="run">Run team</button>
        <p id="status" class="hint" aria-live="polite"></p>
      </div>
      <p id="error" role="alert"></p>

      <div class="console-wrap">
        <div class="console-head">
          <span class="dots" aria-hidden="true"><span></span><span></span><span></span></span>
          Output stream
        </div>
        <pre id="log" class="empty-log" aria-live="polite">Waiting for a run…</pre>
      </div>
    </div>

    <footer>
      AgentForge · loopback only by default · <a href="https://github.com/vgandhi1/agent-forge" rel="noopener noreferrer">GitHub</a>
    </footer>
  </div>

  <script>
    const logEl = document.getElementById("log");
    const errEl = document.getElementById("error");
    const statusEl = document.getElementById("status");
    const runBtn = document.getElementById("run");

    function setStatus(text, state) {
      statusEl.textContent = text || "";
      statusEl.className = "hint";
      if (state === "running") statusEl.className = "running";
      else if (state === "done") statusEl.className = "done";
      else if (state === "bad") statusEl.className = "bad";
    }

    function appendLog(text) {
      if (logEl.classList.contains("empty-log")) {
        logEl.textContent = "";
        logEl.classList.remove("empty-log");
      }
      logEl.textContent += text;
      logEl.scrollTop = logEl.scrollHeight;
    }

    runBtn.addEventListener("click", () => {
      errEl.textContent = "";
      logEl.textContent = "";
      logEl.classList.add("empty-log");
      logEl.textContent = "Waiting for a run…";
      const preset = document.getElementById("preset").value;
      const goal = document.getElementById("goal").value;
      setStatus("Connecting…", "running");
      runBtn.disabled = true;

      const wsProto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(wsProto + "://" + location.host + "/ws/run");

      const finish = () => { runBtn.disabled = false; };

      ws.onopen = () => {
        setStatus("Running pipeline…", "running");
        ws.send(JSON.stringify({ preset, goal }));
      };

      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) {
          appendLog(ev.data + "\\n");
          return;
        }
        if (msg.type === "line") {
          appendLog(msg.text + "\\n");
        } else if (msg.type === "exit") {
          if (msg.code === 0) {
            setStatus("Finished successfully.", "done");
          } else {
            setStatus("Finished with exit code " + msg.code, "bad");
          }
          ws.close();
          finish();
        } else if (msg.type === "error") {
          const prefix = msg.code ? "[" + msg.code + "] " : "";
          errEl.textContent = prefix + (msg.message || "Error");
          setStatus("", "");
          ws.close();
          finish();
        }
      };

      ws.onerror = () => {
        errEl.textContent = "WebSocket error — is the server running?";
        setStatus("", "");
        finish();
      };

      ws.onclose = () => {
        if (runBtn.disabled) finish();
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

    @app.get("/favicon.svg", response_class=Response)
    async def favicon_svg() -> Response:
        return Response(
            content=_FAVICON_SVG.encode("utf-8"),
            media_type="image/svg+xml",
        )

    @app.get("/favicon.ico", response_class=Response)
    async def favicon_ico() -> Response:
        return Response(
            content=_FAVICON_SVG.encode("utf-8"),
            media_type="image/svg+xml",
        )

    @app.websocket("/ws/run")
    async def run_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            raw = await websocket.receive_text()
            data = json.loads(raw)
        except (json.JSONDecodeError, WebSocketDisconnect):
            await websocket.send_json({
                "type": "error",
                "code": "INVALID_JSON",
                "message": 'Send a JSON object with string fields "preset" and "goal". Example: {"preset":"full","goal":"…"}',
            })
            return

        preset = str(data.get("preset", "full")).lower()
        goal = str(data.get("goal", ""))

        if preset not in ALLOWED_PRESETS:
            await websocket.send_json({
                "type": "error",
                "code": "INVALID_PRESET",
                "message": f'Preset "{preset}" is not allowed. Use the dropdown values (full, intake, design, implement, test, ship, improve).',
            })
            return
        if not goal.strip():
            await websocket.send_json({
                "type": "error",
                "code": "EMPTY_GOAL",
                "message": "Enter a sprint goal in the text area before clicking Run team.",
            })
            return
        if len(goal) > MAX_GOAL_CHARS:
            await websocket.send_json({
                "type": "error",
                "code": "GOAL_TOO_LONG",
                "message": f"Goal exceeds maximum length ({MAX_GOAL_CHARS} characters). Shorten the text or split into a file and use the CLI with --goal-file.",
            })
            return

        if not MAIN_PY.is_file():
            await websocket.send_json({
                "type": "error",
                "code": "MAIN_PY_MISSING",
                "message": "Server misconfiguration: main.py not found next to web_ui.py.",
            })
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
        except OSError:
            try:
                os.unlink(goal_path)
            except OSError:
                pass
            await websocket.send_json({
                "type": "error",
                "code": "PROCESS_START_FAILED",
                "message": "Could not start the Python subprocess. Check that Python is available and main.py is executable.",
            })
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
    log = logging.getLogger("agentforge.web")
    if host not in ("127.0.0.1", "::1", "localhost"):
        log.warning(
            "Web UI bound to %s — use a reverse proxy and auth on untrusted networks; "
            "default is loopback-only.",
            host,
        )
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
