# AgentForge — how to use the agent team

AgentForge runs a **Lead-orchestrated team** of AI agents (Product Manager, Architect, Backend, QA, DevOps) that read and write files under `workspace/`. You can drive it from:

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

### Ollama (local LLM)

Set `AGENTFORGE_LLM_PROVIDER=ollama` and run [Ollama](https://ollama.com/) (`ollama serve`). Each role can use a different model via `AGENTFORGE_OLLAMA_MODEL_LEAD`, `AGENTFORGE_OLLAMA_MODEL_PM`, … (see `.env.example`). Defaults fall back to `AGENTFORGE_OLLAMA_MODEL` or `llama3.2`. Use models that support **tool calling** for best results.

`AGENTFORGE_OLLAMA_HOST` must resolve to **loopback** by default (SSRF-safe). For Docker Compose on a private bridge, set `AGENTFORGE_OLLAMA_TRUST_LAN=1` and read the warning in `.env.example`.

The **web UI** exposes provider choice, Ollama URL, **Refresh models**, and per-role model fields; those values are passed into the run as environment overrides.

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
| Debug logging | `python main.py -v --dry-run` | `uv run python main.py -v --dry-run` |
| Log file | `python main.py -v --log-file ./run.log` | `uv run python main.py -v --log-file ./run.log` |
| Require deploy sign-off | `python main.py --deploy-gate` | `uv run python main.py --deploy-gate` |
| Plan-before-build (backend) | `python main.py --plan-gate --goal "…"` | `uv run python main.py --plan-gate --goal "…"` |
| Resume completed phases | `python main.py --resume --goal "…"` | `uv run python main.py --resume --goal "…"` |

`--goal-file` must point to an **existing regular file**; otherwise the CLI exits with code `2` and a short error (no traceback).

### Quality gates & flags

The pipeline runs autonomously by default. These flags add checkpoints; **all default off**, so leaving them unset keeps the original behavior. Always-on quality controls (independent reviewer, scope lock, escalation, selective context) need no flags.

| Flag | Env var | What it does |
|------|---------|--------------|
| `--deploy-gate` | `AGENTFORGE_DEPLOY_GATE=1` | After all phases: run a pytest smoke check, then ask for human go/no-go before the deploy step. Without a TTY it does **not** approve (fail-safe). |
| `--auto-approve` | — | With `--deploy-gate`, approve automatically (unattended runs). |
| `--deploy-commit` | `AGENTFORGE_DEPLOY_COMMIT=1` | On approval, commit the generated `workspace/dailyease` app to its **own** git repo (init if needed; never touches the AgentForge repo). |
| `--plan-gate` | `AGENTFORGE_PLAN_GATE=1` | Backend proposes a build plan; the Lead confirms or redirects before any code is written. Fail-open if no response. |
| `--resume` | — | Skip phases already completed for the **same goal**, reading `handoff/checkpoint.json`; restores upstream artifact references. |

Examples:

```bash
# Gated, attended deploy (you approve interactively)
uv run python main.py --deploy-gate --goal "Ship reminders v2"

# Gated, unattended deploy that also versions the generated app
uv run python main.py --deploy-gate --auto-approve --deploy-commit --goal "Nightly build"

# Plan-first build, then resume later if interrupted (same --goal)
uv run python main.py --plan-gate --goal "Finance module"
uv run python main.py --resume    --goal "Finance module"
```

Outputs from these: `reports/deploy_record.md` (deploy decision + verify result), `reports/known_gaps.md` (deferred out-of-scope items + reviewer drift), `handoff/<role>.md` and `handoff/checkpoint.json` (per-phase trail + resume state). Preview any combination with `--dry-run`.

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

If `ANTHROPIC_API_KEY` is missing, the CLI exits with an error unless you use **`AGENTFORGE_LLM_PROVIDER=ollama`** (then Ollama is used and the Anthropic key is not required). `--dry-run` and `--list-artifacts` never call either API.

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
5. Press **c** to **cancel** the running subprocess (kill).

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

Use **LLM provider & per-role models** on the page to choose Anthropic vs Ollama, set `AGENTFORGE_OLLAMA_HOST`, refresh installed tags, and assign a model per role (optional; blanks use `.env` defaults).

---

## 5. With Claude Code

This repo includes `.claude/commands/agentforge.md`. Run AgentForge in a terminal **in the same project folder** where `workspace/` and `.env` live, while you use Claude Code for editing and review.

---

## 6. Where outputs go

- **Artifacts:** `workspace/` (docs, `dailyease/` app, `reports/`, etc.)  
- **Reviews & gates:** `workspace/reports/deploy_record.md` (deploy decision + verify), `workspace/reports/known_gaps.md` (deferred items + reviewer drift)  
- **Handoff trail / resume state:** `workspace/handoff/<role>.md` and `workspace/handoff/checkpoint.json`  
- **Agent memory / logs (SQLite):** `agentforge.db` in `AGENTFORGE_ROOT` (default: repo root)

```bash
uv run python main.py --list-artifacts
```

---

## 7. Troubleshooting

| Issue | What to try |
|-------|-------------|
| `ModuleNotFoundError` | Run `uv sync` or activate `.venv` and `pip install -r requirements.txt` |
| `ANTHROPIC_API_KEY not set` | Add it to `.env`, or switch the web UI / env to **Ollama** (`AGENTFORGE_LLM_PROVIDER=ollama`) |
| Ollama connection / tags | Ensure `ollama serve` is running; URL must be loopback unless `AGENTFORGE_OLLAMA_TRUST_LAN=1` |
| Vars not visible to subprocess | Use `uv run --env-file .env` or `export UV_ENV_FILE=.env` |
| `pytest` fails in **test** preset | Run `implement` or `full` first so `workspace/dailyease` exists; install that app’s `requirements.txt` into the venv if needed |
| Web UI won’t connect | Open `127.0.0.1` and the port from `--web-port` |
| `--deploy-gate` won’t approve | No interactive terminal → it fail-safes to *not approve*. Add `--auto-approve` for unattended runs |
| `--resume` runs everything | Checkpoint goal must match the current `--goal`; a changed goal resets the checkpoint |

### Tests (development)

```bash
uv sync --group dev
uv run pytest
```

For architecture details (message bus, Lead approvals, caching), see `agents_plan.md`.
