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
| `/agentforge-resume <goal>` | Skip completed phases for the same goal | `--resume` |
| `/agentforge-artifacts` | List generated files | `--list-artifacts` |
| `/agentforge-dry-run [goal]` | Show config, no API calls | `--dry-run` |

**Claude Code** picks these up automatically (project commands). To use them in **every** project, copy
them to your global commands dir:

```bash
cp .claude/commands/agentforge*.md ~/.claude/commands/
```

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
- Everything above works directly in a shell; the assistant is only a convenience for issuing commands.

---

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

See also: [USAGE.md](USAGE.md) · [ollama.md](ollama.md) · [agents_plan.md](agents_plan.md).
