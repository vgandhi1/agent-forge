# AgentForge

**Repository:** [github.com/vgandhi1/agent-forge](https://github.com/vgandhi1/agent-forge)

Multi-agent pipeline (CEO, PM, Architect, Backend, QA, DevOps) that writes artifacts under `workspace/`.

## Environment & package manager (uv)

1. **Install [uv](https://docs.astral.sh/uv/getting-started/installation/)** (handles the virtualenv + locked deps).
2. **Create the environment and install packages:**
   ```bash
   cd /path/to/this/repo   # repository root (where main.py lives)
   uv sync     # uses pyproject.toml + uv.lock → .venv
   ```
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

## Full instructions

- **[USAGE.md](USAGE.md)** — CLI, TUI, web UI, presets, pip fallback, troubleshooting  
- **[agents_plan.md](agents_plan.md)** — architecture, env var table, deployment phases  
- **[docs/github-repository.md](docs/github-repository.md)** — GitHub description, topics, `gh repo create`, public vs private  

Claude Code shortcut: [.claude/commands/agentforge.md](.claude/commands/agentforge.md)
