# AgentForge — how to use the agent team

AgentForge runs a **CEO-led team** of AI agents (Product Manager, Architect, Backend, QA, DevOps) that read and write files under `workspace/`. You can drive it from:

| Interface | What it is | Best for |
|-----------|------------|----------|
| **CLI** | `python main.py` or `uv run python main.py` | Scripts, CI, one-shot runs |
| **TUI** | `python main.py --tui` (Textual) | Interactive terminal, preset buttons, live log |
| **Web UI** | `python main.py --web` | Browser on your machine, streamed logs |

There is **no hosted cloud UI**; the web server listens on **127.0.0.1** only.

---

## Quick reference: uv + environment variables

| Step | Command / action |
|------|------------------|
| Install uv | See [uv installation](https://docs.astral.sh/uv/getting-started/installation/) |
| Create venv + install deps | `uv sync` (uses `pyproject.toml` + `uv.lock`) |
| Create env-var file | `cp .env.example .env` then edit (set **`ANTHROPIC_API_KEY`**) |
| Run CLI without `activate` | `uv run python main.py --dry-run` |
| Force uv to load `.env` for subprocess | `uv run --env-file .env python main.py …` |
| Default env file for every `uv run` | `export UV_ENV_FILE=.env` (shell) |

The application also calls **`load_dotenv()`**, so a `.env` file in the **project root** is picked up when Python starts—`uv run python main.py` is usually enough.

---

## 1. One-time setup

From the **repository root** (directory that contains `main.py`).

### Option A — uv (recommended)

[uv](https://docs.astral.sh/uv/) manages the **virtual environment** and installs dependencies from `pyproject.toml` + **`uv.lock`** (reproducible versions).

Install uv (pick one):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
# Windows: winget install astral-sh.uv  — or see uv docs
```

Create the env and install everything (editable project + all deps):

```bash
uv sync
cp .env.example .env
```

#### Setting environment variables

1. **File-based (recommended):** edit `.env` next to `main.py`. Required for runs: **`ANTHROPIC_API_KEY`**. Optional: `AGENTFORGE_MODEL`, `AGENTFORGE_THINKING`, `AGENTFORGE_ROOT`, `AGENTFORGE_WORKSPACE`, `AGENTFORGE_DB` (see `agents_plan.md` and `.env.example`).
2. **Shell (ad hoc):** `export ANTHROPIC_API_KEY=sk-ant-...` then run `uv run python main.py …` (no `.env` needed if all vars are exported).
3. **uv-injected:** `uv run --env-file .env python main.py …` — same keys as in the file; useful if something must see variables before `dotenv` runs.
4. **uv default file:** `export UV_ENV_FILE=.env` so you do not repeat `--env-file`.

Run commands **without** activating the venv (uv uses `.venv` automatically):

```bash
uv run python main.py --dry-run
uv run python main.py --preset intake --goal "Your goal"
uv run python main.py --tui
uv run python main.py --web
```

The `agentforge` console script:

```bash
uv run agentforge --list-artifacts
```

After changing dependencies in `pyproject.toml`:

```bash
uv lock
uv sync
```

### Option B — pip + venv

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                   # optional: `agentforge` command
cp .env.example .env
```

Set variables the same way: **edit `.env`** (loaded by dotenv) and/or **export** in the shell before `python main.py`.

---

## 2. Terminal (CLI)

Your cwd should be the **repository root**. With **uv**, prefer `uv run python …`; with **pip**, activate `.venv` first.

| Action | With venv activated | With uv (no activate) |
|--------|-------------------|------------------------|
| Full pipeline (default goal) | `python main.py` | `uv run python main.py` |
| Custom goal | `python main.py --goal "…"` | `uv run python main.py --goal "…"` |
| Goal from file | `python main.py --goal-file ./my-intake.md` | `uv run python main.py --goal-file ./my-intake.md` |
| Custom agent order | `python main.py --phases pm,qa --goal "…"` | `uv run python main.py --phases pm,qa --goal "…"` |
| Show config (no API calls) | `python main.py --dry-run` | `uv run python main.py --dry-run` |
| List generated files | `python main.py --list-artifacts` | `uv run python main.py --list-artifacts` |

### Presets (which agents run)

| Preset | Agents (order) |
|--------|------------------|
| `full` (default) | PM → architect → backend → QA → DevOps |
| `intake` | PM only — requirements / PRD |
| `design` | PM + architect |
| `implement` | Backend only (expects docs may already exist) |
| `test` | QA only — tests + `pytest` under `workspace/dailyease` |
| `ship` | DevOps only — Docker, CI, deployment doc |
| `improve` | Backend + QA — improvements pass |

Examples:

```bash
# pip + activated venv
python main.py --preset intake --goal "Requirements for habit streaks export"

# uv
uv run python main.py --preset test --goal "Increase coverage on finance routers"
uv run python main.py --preset full --goal-file ./sprint-goal.md
```

If `ANTHROPIC_API_KEY` is missing, the CLI exits with an error (except `--dry-run` and `--list-artifacts`).

---

## 3. Terminal UI (TUI)

```bash
python main.py --tui
# or
uv run python main.py --tui
```

1. Type your **sprint goal** in the input (multi-line is OK).  
2. Press a **preset** button (Full, Intake, Design, etc.).  
3. Watch the **log** panel; it runs the same `main.py` subprocess as the CLI.  
4. Press **q** to quit the TUI (the run continues until the subprocess finishes).

The TUI writes your goal to a temporary file and invokes `--goal-file`, so special characters and newlines are safe.

---

## 4. Browser UI (local)

```bash
python main.py --web
# or
uv run python main.py --web
```

Default URL: **http://127.0.0.1:8755**

Custom port:

```bash
uv run python main.py --web --web-port 9000
```

Stop the server with **Ctrl+C** in the terminal.

---

## 5. With Claude Code

This repo includes `.claude/commands/agentforge.md`. Run AgentForge in a terminal **in the same project folder** where `workspace/` and `.env` live, while you use Claude Code for editing and review.

---

## 6. Where outputs go

- **Artifacts:** `workspace/` (docs, `dailyease/` app, `reports/`, etc.)  
- **Agent memory / logs (SQLite):** `agentforge.db` in `AGENTFORGE_ROOT` (default: repo root)

```bash
uv run python main.py --list-artifacts
```

---

## 7. Troubleshooting

| Issue | What to try |
|-------|-------------|
| `ModuleNotFoundError` | Run `uv sync` or activate `.venv` and `pip install -r requirements.txt` |
| `ANTHROPIC_API_KEY not set` | Add it to `.env`, or `export ANTHROPIC_API_KEY=…`, or `uv run --env-file .env …` |
| Vars not visible to subprocess | Use `uv run --env-file .env` or `export UV_ENV_FILE=.env` |
| `pytest` fails in **test** preset | Run `implement` or `full` first so `workspace/dailyease` exists; install that app’s `requirements.txt` into the venv if needed |
| Web UI won’t connect | Open `127.0.0.1` and the port from `--web-port` |

For architecture details (message bus, CEO approvals, caching), see `agents_plan.md`.
