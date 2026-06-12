# Running AgentForge from any AI coding assistant

AgentForge is a **self-contained command-line app** — `uv run python main.py …` (or `agentforge …`).
It calls its own LLM (Anthropic or local Ollama, set in `.env`) and writes files under `workspace/`.

That means **any** AI coding assistant that can run a terminal command can drive it: Claude Code,
Cursor, OpenAI Codex CLI, Aider, Continue, Cline, Windsurf, plain shell — no per-tool plugin required.
The assistant just runs the command; AgentForge does the multi-agent work itself.

> Key mental model: your assistant's model and AgentForge's model are **separate**. Your assistant
> launches AgentForge as a subprocess; AgentForge then uses whatever provider/model you set in `.env`.

---

## Universal quickstart (works in every tool)

From the repo root (the folder with `main.py`):

```bash
# 1. Install deps (creates .venv)
uv sync

# 2. Configure the provider
cp .env.example .env
#   Claude:  set ANTHROPIC_API_KEY=...
#   Local:   set AGENTFORGE_LLM_PROVIDER=ollama   (see docs/ollama.md)

# 3. Preview config (no API calls), then run
uv run python main.py --dry-run
uv run python main.py --preset intake --goal "Your goal here"
```

Full flags, presets, and quality gates: [USAGE.md](USAGE.md). Local models: [ollama.md](ollama.md).

Tell your assistant something like:
> "Run `uv run python main.py --preset intake --goal '...'` from the repo root and show me the output."

> "From the AgentForge repo root, run `uv run python main.py --dry-run` and tell me which provider and models it will use."

> "Run the full AgentForge pipeline for this goal: `uv run python main.py --goal 'Build a habit-tracking API'`, run it in the background, and summarize the artifacts in `workspace/` when it finishes."

---

## Command set (chat-pluggable)

AgentForge ships **slash commands** in `.claude/commands/` so you can drive the whole system from chat —
type the command, pass the goal as the argument:

| Slash command | What it runs | Underlying CLI |
|---------------|--------------|----------------|
| `/agentforge <goal>` | Full pipeline (PM → Architect → Backend → QA → DevOps) | `main.py --goal "<goal>"` |
| `/agentforge-intake <goal>` | Requirements (PM) | `--preset intake` |
| `/agentforge-design <goal>` | Requirements + architecture | `--preset design` |
| `/agentforge-implement <goal>` | FastAPI app (Backend) | `--preset implement` |
| `/agentforge-test <goal>` | QA tests + pytest | `--preset test` |
| `/agentforge-ship <goal>` | Docker/CI/runbook (DevOps) | `--preset ship` |
| `/agentforge-improve <goal>` | Refactor + re-verify | `--preset improve` |
| `/agentforge-debug <goal>` | Reproduce → patch → re-verify a bug (+ regression test) | `--preset debug` |
| `/agentforge-fix <goal>` | Apply a known fix + covering test | `--preset fix` |
| `/agentforge-harden <goal>` | Production-readiness pass (audit → patch → ops) | `--preset harden` |
| `/agentforge-data <goal>` | Factory data layer: ingestion, contracts, ETL, quality | `--preset data` |
| `/agentforge-ml <goal>` | Industrial ML layer: features, model, eval, inference | `--preset ml` |
| `/agentforge-factory <goal>` | End-to-end data + AI app lifecycle | `--preset factory` |
| `/agentforge-resume <goal>` | Skip completed phases for the same goal | `--resume` |
| `/agentforge-artifacts` | List generated files | `--list-artifacts` |
| `/agentforge-dry-run [goal]` | Show config, no API calls | `--dry-run` |

**Claude Code** picks these up automatically as **project** commands (when the session is opened in
this repo). The shipped files call `uv run python main.py`, which assumes the repo root is the cwd.

To use the commands in **every** project, you need two things — the binary on `PATH`, and global
command copies that call it:

```bash
# 1. Install the binary globally (so `agentforge` resolves from any directory)
uv tool install .            # or: pipx install .

# 2. Copy the commands, then point the global copies at the binary
cp .claude/commands/agentforge*.md ~/.claude/commands/
sed -i 's/uv run python main.py/agentforge/g' ~/.claude/commands/agentforge*.md
sed -i 's/allowed-tools: Bash(uv run:\*), Bash(python main.py:\*)/allowed-tools: Bash(agentforge:*)/' ~/.claude/commands/agentforge*.md
```

Run from a project, add `--target-repo .` to operate on that repo (greenfield presets otherwise
write to AgentForge's own `workspace/` sandbox). `agentforge` reads `ANTHROPIC_API_KEY` from the
environment when no repo `.env` is on the cwd — export it in your shell for global runs.

**Other AI CLIs** (Cursor, Codex, Aider, Continue, Cline, Windsurf): there's no shared slash-command
standard, so use the **CLI form** the table maps to — ask the assistant to run it, e.g.:

> "Run `uv run python main.py --preset test --goal '…'` from the repo root."

The mapping is 1:1, so the slash commands double as a copy-paste cheatsheet for any tool.

---

## Per-assistant notes

### Claude Code
- The command set above is available as `/agentforge…` slash commands (project `.claude/commands/`).
- Long runs: ask it to run in the background / a separate terminal; local models take minutes per phase.

### Cursor
- Open the repo. Use the integrated terminal, or ask the agent to run the `uv run …` command.
- Optionally add a Cursor "task" / run config that invokes `uv run python main.py --dry-run`.

### OpenAI Codex CLI
- Run inside the repo; ask it to execute the quickstart commands. Approve the shell command when prompted.

### Aider / Continue / Cline / Windsurf / others
- All of these can execute shell commands — point them at the repo and have them run the same
  `uv run python main.py …` commands. Nothing AgentForge-specific to configure.

### Plain terminal (no assistant)

The assistant is only a convenience for typing commands — AgentForge needs no AI tool to run.
Open a terminal in the repo root (the folder with `main.py`) and invoke it yourself:

```bash
# One-time: install deps
uv sync                                   # or: pip install -r requirements.txt

# Dry-run (no API calls) — prints provider, models, gates, goal
uv run python main.py --dry-run

# Operate on the repo you have open
uv run python main.py --preset debug --target-repo . --goal "Fix the failing auth test"

# Greenfield run in the workspace/ sandbox
uv run python main.py --preset full --goal "Build a habit-tracking API"
```

Installed globally (`uv tool install .` or `pipx install .`), drop the `uv run python main.py`
prefix and call `agentforge …` from any directory. Full flag list: [USAGE.md](USAGE.md).

### VS Code (Tasks — no assistant, no extension)

AgentForge ships `.vscode/tasks.json`, so you can run it from VS Code's UI without Copilot or any
chat extension:

1. Open the agent-forge folder (or your target repo) in VS Code.
2. **Command Palette** (`Ctrl/Cmd+Shift+P`) → **Tasks: Run Task**.
3. Pick a task — **AgentForge: debug / test / harden / dry-run**.
4. Type the sprint **goal** at the prompt; output streams in a dedicated terminal panel.

The bundled tasks pass `--target-repo "${workspaceFolder}"`, so they act on whatever folder you
have open. Edit `.vscode/tasks.json` to add presets or flags (e.g. `--strict-review`). Requires
`uv` on `PATH` and `ANTHROPIC_API_KEY` in `.env` (or an Ollama setup).

---

## Work on your existing repo (`--target-repo`)

By default AgentForge writes to its own sandbox under `workspace/`. To operate on a repo you
already have open in your editor, point it at that repo with `--target-repo PATH` (or
`AGENTFORGE_TARGET_REPO`):

```bash
# Read, patch, and test the caller's repo instead of the sandbox
uv run python main.py --preset improve --target-repo /path/to/my-api \
  --goal "Fix N+1 queries in the orders router"

# From inside the target repo, "." resolves to that repo
uv run python main.py --preset test --target-repo . --goal "Add edge cases for DELETE"
```

What changes in target-repo mode:

- **Code root** becomes the target repo: workers `read_file` / `list_files` / `grep_code` and
  `write_file` operate on *that* tree, not `workspace/`.
- **Metadata stays isolated** under `<repo>/.agentforge/` — AgentForge's own bookkeeping
  (`handoff/`, `reports/`, checkpoints) is written there, **not** scattered into your source
  tree. The SQLite DB stays under AgentForge's own root, never inside the target repo.
- Add `.agentforge/` to the target repo's `.gitignore` so AgentForge metadata is not committed.

Security: AgentForge only writes inside the resolved code root and its `.agentforge/` metadata
dir — paths are validated against those roots, so a run cannot write to arbitrary locations.
Git commits to the target repo remain opt-in (`--deploy-commit`).

### Structured JSON events for assistants

Host assistants parse Rich console text poorly. Set `AGENTFORGE_JSON_LOG=1` and AgentForge
emits **one JSON object per line on stderr** — your assistant can tail stderr and consume
typed events instead of scraping the console:

```bash
AGENTFORGE_JSON_LOG=1 uv run python main.py --preset improve --target-repo . \
  --goal "..." 2> events.jsonl
```

Event types: `phase_complete`, `files_changed`, `review_verdict`, `pytest_result`,
`exit_summary`. Each line looks like `{"event": "files_changed", "ts": "...", "role": "backend",
"count": 23, ...}`. The flag is **opt-in**: unset, human console output is unchanged. Tell your
assistant to tail stderr JSON when summarizing a run.

## Tips for assistant-driven runs

- **Start with `--dry-run`** — it prints the resolved provider, models, gates, and goal without calling any API.
- **Secrets stay in `.env`**, not in chat. AgentForge loads `.env` via `python-dotenv`; don't paste keys
  into the assistant.
- **Pick the provider deliberately.** Anthropic needs `ANTHROPIC_API_KEY`; Ollama needs a reachable host
  and a tool-calling model — see [ollama.md](ollama.md) (incl. the Windows-Ollama + WSL2 setup).
- **Long jobs:** the full pipeline is 5 phases, each generate + review. On local models this is slow —
  run it unattended (background) rather than under a short timeout. Partial artifacts are kept, so
  `--resume` continues where it stopped.
- **Gates are opt-in** (`--deploy-gate`, `--plan-gate`, `--resume`); default off keeps runs fully autonomous.

---

## Cost & billing (orchestrator vs launcher)

Your assistant and AgentForge are **two separate LLM consumers** — they bill independently:

| Consumer | Role | Billed |
|----------|------|--------|
| Your assistant (Claude Code / Cursor / Codex) | **Launcher** — fires the command, monitors, summarizes | Your assistant's own plan: a Claude/Cursor **subscription** (counts against its limits, no per-token charge), or that tool's **API** auth (per-token). |
| AgentForge | **Orchestrator** — runs the multi-agent build with its own model | The `ANTHROPIC_API_KEY` in `.env` (or env) → **pay-as-you-go per token** on that Anthropic Console account. With Ollama, **$0** (local). |

Key points:
- **AgentForge is the cost driver.** A `full`/`factory` run is many phases × (generate + independent review) × per-role models — far more tokens than the launcher, which only reads a summary.
- The two meters are separate even if the same person owns both. The launcher's subscription does **not** pay for AgentForge's API tokens.
- **Don't let the launcher duplicate the build** (dual-agent contract). If the assistant "becomes" AgentForge and writes the code itself, you pay twice and burn its context.
- **Cut cost:** `--dry-run` (free, no calls) · Ollama provider (local, $0, see [ollama.md](ollama.md)) · per-role model overrides (downgrade non-critical roles) · staged presets (`intake`→`design`→…) instead of one big `full`/`factory`.

See also: [USAGE.md](USAGE.md) · [ollama.md](ollama.md) · [agents_plan.md](agents_plan.md).
