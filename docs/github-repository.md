# GitHub repository: `agent-forge`

**Live repo:** https://github.com/vgandhi1/agent-forge  

Description and topics were applied via `gh repo edit`; re-run the commands below if you change them.

## Public or private?

| Choose **public** if… | Choose **private** if… |
|------------------------|-------------------------|
| You want visibility, portfolio, or open contributions | The product roadmap, prompts, or workflows are confidential |
| You are fine shipping **code only** (no secrets) | Your org requires restricted access by default |

**Secrets:** `.env` and API keys stay **out of git** (see `.gitignore`). A public repo is safe **only if** you never commit keys, tokens, or customer data.

**Recommendation:** Start **private** while iterating; flip to **public** when you want to share. Open source: **public** + add a `LICENSE`.

---

## Fields to copy into GitHub

### Repository name
```
agent-forge
```

### Short description (repository subtitle — one line)

```
Multi-agent software team (CEO, PM, architect, backend, QA, DevOps) orchestrated with Claude—CLI, TUI, and local web UI. FastAPI artifacts, pytest, uv.
```

### Topics (add under “About” → gear icon → Topics)

```
python
anthropic
claude
multi-agent
ai-agents
agentic-ai
fastapi
asyncio
software-development
automation
orchestration
codegen
pytest
uv
textual
rich
```

### Website (optional)

Leave blank, or set to your future docs site.

---

## Create and push (GitHub CLI)

1. Authenticate (token invalid? renew here):

   ```bash
   gh auth login -h github.com
   ```

2. From the **repository root** (this folder), after `git` is initialized and committed:

   ```bash
   # Public
   gh repo create agent-forge --public --source=. --remote=origin --description "Multi-agent software team (CEO, PM, architect, backend, QA, DevOps) orchestrated with Claude—CLI, TUI, and local web UI. FastAPI artifacts, pytest, uv." --push

   # Private
   gh repo create agent-forge --private --source=. --remote=origin --description "Multi-agent software team (CEO, PM, architect, backend, QA, DevOps) orchestrated with Claude—CLI, TUI, and local web UI. FastAPI artifacts, pytest, uv." --push
   ```

3. Add topics (UI or CLI):

   ```bash
   gh repo edit --add-topic python --add-topic anthropic --add-topic claude --add-topic multi-agent --add-topic ai-agents --add-topic agentic-ai --add-topic fastapi --add-topic asyncio --add-topic software-development --add-topic automation --add-topic orchestration --add-topic codegen --add-topic pytest --add-topic uv --add-topic textual --add-topic rich
   ```

---

## Create and push (manual)

1. On GitHub: **New repository** → name `agent-forge` → create **without** README (this repo already has one).
2. Locally:

   ```bash
   git remote add origin https://github.com/vgandhi1/agent-forge.git
   git branch -M main
   git push -u origin main
   ```

Replace `YOUR_USER` and use SSH remote if you prefer.
