---
description: Run AgentForge multi-agent pipeline from the repo (CLI / TUI / web)
---

Use AgentForge in this repository for structured intake, design, implementation, testing, and delivery.

## Prerequisites: uv + environment variables

**Packages (virtualenv):** from repo root:

```bash
uv sync
```

**Environment variables:** copy the template and set secrets:

```bash
cp .env.example .env
# Edit .env — required: ANTHROPIC_API_KEY
```

Runtime loading: AgentForge uses **`python-dotenv`** (loads project `.env` on startup). Optionally: `uv run --env-file .env …` or `export UV_ENV_FILE=.env` for uv’s default file.

**Full guide:** [USAGE.md](../../USAGE.md) · **Architecture:** [agents_plan.md](../../agents_plan.md) · **Local models:** [docs/ollama.md](../../docs/ollama.md)

---

## Commands (use `uv run` prefix if you use uv)

Replace `python main.py` with `uv run python main.py` when using uv without activating `.venv`.

- Full pipeline: `python main.py` or `python main.py --preset full --goal "Your goal"`
- Intake (PM): `python main.py --preset intake --goal "..."`  
- Design: `python main.py --preset design --goal "..."`  
- Implement: `python main.py --preset implement --goal "..."`  
- Feature testing: `python main.py --preset test --goal "..."`  
- Ship (DevOps): `python main.py --preset ship --goal "..."`  
- Improvements: `python main.py --preset improve --goal "..."`  
- Custom order: `python main.py --phases pm,backend,qa --goal "..."`  
- **TUI:** `python main.py --tui`  
- **Web UI:** `python main.py --web` → http://127.0.0.1:8755  
- List outputs: `python main.py --list-artifacts`  
- Dry run: `python main.py --dry-run`  

**Examples with uv:**

```bash
uv run python main.py --dry-run
uv run python main.py --preset intake --goal "Login requirements"
uv run agentforge --list-artifacts
```

Optional env vars (in `.env` or shell): `AGENTFORGE_ROOT`, `AGENTFORGE_WORKSPACE`, `AGENTFORGE_MODEL`, `AGENTFORGE_THINKING` — see `agents_plan.md`.
