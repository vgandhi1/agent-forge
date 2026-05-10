# AgentForge

[![CI](https://github.com/vgandhi1/agent-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/vgandhi1/agent-forge/actions/workflows/ci.yml)

**Repository:** [github.com/vgandhi1/agent-forge](https://github.com/vgandhi1/agent-forge) · **License:** [MIT](LICENSE)

Multi-agent pipeline (**Lead** orchestrator, PM, Architect, Backend, QA, DevOps) that writes artifacts under `workspace/`.

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
   Edit `.env` and set at least **`ANTHROPIC_API_KEY`**. Other keys are documented in `agents_plan.md` and `.env.example`.

**Ways those variables reach the process:**

| Method | When to use |
|--------|-------------|
| **`.env` in project root** | Recommended. `python-dotenv` loads it when AgentForge starts. Works with `uv run python main.py …`. |
| **`uv run --env-file .env …`** | Loads the file into the subprocess environment before Python starts. |
| **`export VAR=value`** | Shell-only; use for one-off runs or CI secrets injected by the runner. |
| **`UV_ENV_FILE=/path/to/.env`** | Makes `uv run` use that file by default (see [uv run](https://docs.astral.sh/uv/reference/cli/#uv-run)). |

Run without manually activating the venv:

```bash
uv run python main.py --dry-run
uv run python main.py --preset intake --goal "Your goal"
uv run agentforge --list-artifacts
```

## Troubleshooting (quick)

Missing packages → run `uv sync` (or `pip install -r requirements.txt`). API errors → set `ANTHROPIC_API_KEY` in `.env`. **Details:** [USAGE.md](USAGE.md) §7.

## Full instructions

- **[USAGE.md](USAGE.md)** — CLI, TUI, web UI, presets, pip fallback, troubleshooting  
- **[agents_plan.md](agents_plan.md)** — architecture, env var table, deployment phases  
- **[docs/github-repository.md](docs/github-repository.md)** — GitHub description, topics, `gh repo create`, public vs private  

Claude Code shortcut: [.claude/commands/agentforge.md](.claude/commands/agentforge.md)
