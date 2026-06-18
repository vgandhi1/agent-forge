# AgentForge

[![CI](https://github.com/vgandhi1/agent-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/vgandhi1/agent-forge/actions/workflows/ci.yml)

**Repository:** [github.com/vgandhi1/agent-forge](https://github.com/vgandhi1/agent-forge) · **License:** [MIT](LICENSE)

Multi-agent pipeline that builds a real app (**DailyEase**, a FastAPI service) end to end. A **Lead**
orchestrator drives a team — PM, Architect, Backend, QA, DevOps — and an independent **Reviewer** gates
every artifact. All output lands under `workspace/`.

```
PM → Architect → Backend → QA → DevOps  →  deploy gate
        every phase: Reviewer audits the real files before the Lead accepts it
```

**What makes it more than a prompt chain:** a multi-turn tool loop (agents finish large jobs across
turns), an independent reviewer that reads the actual files (silence ≠ approval), scope lock with a
deferred Known-Gaps log, an escalation channel for ambiguity, and an optional deploy gate
(verify → human sign-off → commit). Runs on **Anthropic** or local **Ollama**.

> **Dual-agent contract:** AgentForge runs its **own** LLM pass. Your assistant should **not**
> duplicate implementation work — only launch, monitor, and summarize.

## Environment & package manager (uv)

1. **Install [uv](https://docs.astral.sh/uv/getting-started/installation/)** (handles the virtualenv + locked deps).
2. **Create the environment and install packages:**
   ```bash
   git clone https://github.com/vgandhi1/agent-forge.git
   cd agent-forge
   uv sync     # uses pyproject.toml + uv.lock → .venv
   ```
   If you already have the repo elsewhere, `cd` into that folder (the directory that contains `main.py`).
3. **Create environment variables for the app** (API keys, options):
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set **`ANTHROPIC_API_KEY`** for Claude, or **`AGENTFORGE_LLM_PROVIDER=ollama`** for local models (full setup incl. Windows-Ollama + WSL: **[docs/ollama.md](docs/ollama.md)**).

**Ways those variables reach the process:**

| Method | When to use |
|--------|-------------|
| **`.env` in project root** | Recommended. `python-dotenv` loads it when AgentForge starts. Works with `uv run python main.py …`. |
| **`uv run --env-file .env …`** | Loads the file into the subprocess environment before Python starts. |
| **`export VAR=value`** | Shell-only; use for one-off runs or CI secrets injected by the runner. |
| **`UV_ENV_FILE=/path/to/.env`** | Makes `uv run` use that file by default (see [uv run](https://docs.astral.sh/uv/reference/cli/#uv-run)). |

## Run it

All commands run from the repo root (the folder with `main.py`). `uv run` uses `.venv` automatically —
no `source .venv/bin/activate` needed. (With a pip venv, activate it and drop the `uv run` prefix.)

```bash
# See config without calling any API (good first check)
uv run python main.py --dry-run

# Full pipeline (PM → Architect → Backend → QA → DevOps) with a custom goal
uv run python main.py --goal "Build the MVP of DailyEase"

# Run only part of the pipeline
uv run python main.py --preset intake  --goal "Capture requirements for reminders v2"
uv run python main.py --preset test    --goal "Expand API tests for the finance module"
uv run python main.py --phases pm,architect,backend --goal "Schema + API for habits only"

# Read the goal from a file
uv run python main.py --goal-file ./sprint-goal.md

# Interactive terminal UI / local browser UI
uv run python main.py --tui
uv run python main.py --web            # http://127.0.0.1:8755

# Inspect results
uv run python main.py --list-artifacts
```

Presets: `full` (default), `intake`, `design`, `implement`, `test`, `ship`, `improve`, plus the
existing-repo bug/hardening presets `debug`, `fix`, `harden` (pair with `--target-repo`), and the
factory data & AI engineering presets `data`, `ml`, `factory` (add Data Engineer + AI/ML Engineer
personas for predictive-maintenance / anomaly-detection / quality-prediction apps).

### Install globally / run from any repo

Install the `agentforge` command once, then run it from inside **any** project — no cloning, no `cd`
into AgentForge:

```bash
# from the agent-forge checkout (folder with main.py):
uv tool install .      # or: pipx install .

# then, from inside any other project directory:
agentforge --preset debug --target-repo . --goal "Fix the failing finance tests"
```

`--target-repo .` operates on the current repo while AgentForge keeps its own `agentforge.db` and
default `workspace/` **out** of that directory. Without `--target-repo`, an installed run sandboxes
into **`~/.agentforge`** (override with `AGENTFORGE_HOME`, or `AGENTFORGE_ROOT` for an absolute
path). Running from the AgentForge source checkout keeps the old behavior (ROOT = repo root). See
**[USAGE.md](docs/USAGE.md)**.

### Quality gates (opt-in flags)

The pipeline is autonomous by default; these add checkpoints. All default **off** — turning none on
leaves behavior unchanged.

```bash
# Require human sign-off before the deploy step (Ctrl-C to decline)
uv run python main.py --deploy-gate

# Same, but approve automatically (unattended) and commit the generated app to its own git repo
uv run python main.py --deploy-gate --auto-approve --deploy-commit

# Backend shows a build plan for the Lead to confirm/redirect before writing code
uv run python main.py --plan-gate --goal "…"

# Resume: skip phases already completed for the same goal (reads handoff/checkpoint.json)
uv run python main.py --resume --goal "…"
```

| Flag | Env | Effect |
|------|-----|--------|
| `--deploy-gate` | `AGENTFORGE_DEPLOY_GATE=1` | pytest smoke verify + human go/no-go before shipping |
| `--auto-approve` | — | with `--deploy-gate`, approve without prompting |
| `--deploy-commit` | `AGENTFORGE_DEPLOY_COMMIT=1` | commit generated `workspace/dailyease` to its own git repo |
| `--plan-gate` | `AGENTFORGE_PLAN_GATE=1` | backend plan → Lead confirm/redirect before code |
| `--adaptive` | `AGENTFORGE_ADAPTIVE=1` | agentic mode: Lead plans phases from the goal, re-routes on outcomes, self-checks the goal is met |
| `--resume` | — | skip phases already completed for the same goal |

Always on: independent reviewer, scope lock (`reports/known_gaps.md`), escalation channel, selective
context. See **[USAGE.md](docs/USAGE.md)** for full details and `--dry-run` to preview any combination.

### Agentic mode (`--adaptive`)

By default AgentForge runs a **fixed pipeline** (the preset's phases, in order). `--adaptive` turns the
Lead into a planner that *adapts* — the difference between a multi-agent script and an agentic system:

```bash
# Lead plans the phases for the goal, re-routes on failures, and checks the goal is met
uv run python main.py --adaptive --preset factory \
  --goal "Build a predictive-maintenance service for CNC machines"
```

What changes when it's on:

- **Plan from the goal** — the Lead proposes the phase sequence (seeded by the preset) instead of
  running a hardcoded list.
- **Re-route on outcomes** — when a phase ends with unresolved review findings or an escalation, the
  Lead can insert one focused follow-up phase next (e.g. route a QA-found defect back to Backend).
  Bounded by a replanning budget so it can never loop forever.
- **Goal self-check** — before declaring "Sprint Complete", the Lead verifies the accepted artifacts
  satisfy the goal and enqueues one bounded remediation round if they don't.

Independently, every **builder** (Backend, Data Engineer, ML Engineer) now has an **act→observe loop**:
they can call `run_tests` / `run_lint` (the project profile's configured commands) to execute their own
code, read the failures, fix the cause, and re-run — not just write code blind. Only profile-configured
commands run; the model never gets arbitrary shell. For changes to files that already exist they make
**surgical `edit_file` edits** (anchored search/replace, path-validated to the code root) instead of
rewriting whole files — safer and cheaper on a real `--target-repo`.

## Troubleshooting (quick)

Missing packages → run `uv sync` (or `pip install -r requirements.txt`). API errors → set `ANTHROPIC_API_KEY` in `.env`. **Details:** [USAGE.md](docs/USAGE.md) §7.

## Full instructions

- **[docs/USAGE.md](docs/USAGE.md)** — CLI, TUI, web UI, presets, gate flags, pip fallback, troubleshooting  
- **[docs/running-with-ai-clis.md](docs/running-with-ai-clis.md)** — drive AgentForge from any AI coding assistant (Claude Code, Cursor, Codex, …), **or with no assistant** from a plain terminal or VS Code Tasks  
- **[docs/ollama.md](docs/ollama.md)** — run on local models; Windows-Ollama + WSL setup, model choice, diagnostics  
- **[docs/agents_plan.md](docs/agents_plan.md)** — architecture, env var table, deployment phases  
- **[docs/evaluation.md](docs/evaluation.md)** — 9-step agent-quality roadmap mapped to AgentForge presets, gates, and metrics  
- **[evals/README.md](evals/README.md)** — fixture-based pipeline eval suite (`run_evals.py`) and scenario contracts  
- **[docs/github-repository.md](docs/github-repository.md)** — GitHub description, topics, `gh repo create`, public vs private  

Claude Code shortcut: [.claude/commands/agentforge.md](.claude/commands/agentforge.md)
