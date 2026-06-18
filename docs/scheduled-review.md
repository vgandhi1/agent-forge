# Scheduled review & PR automation (not in core)

AgentForge is **one-shot**: each invocation runs and exits. There is no built-in interval
scheduler, daemon, `git push`, or `gh pr create`. To get "loop on interval → review → PR if
needed", wrap it in **external orchestration** with three layers:

1. **Scheduler** — cron, GitHub Actions `schedule:`, or Cursor `/loop` (the host, not AgentForge)
2. **AgentForge run** — e.g. `--preset harden --strict-review --target-repo . --deploy-commit --deploy-branch agentforge/scheduled-…`
3. **PR wrapper** — if verify passed and `git rev-list` shows commits → `git push` + `gh pr create`

The reference wrapper lives at [`scripts/scheduled-review-pr.sh`](../scripts/scheduled-review-pr.sh).
Make it executable once: `chmod +x scripts/scheduled-review-pr.sh`.

Recommended preset for unattended fix cycles: `harden` or `debug` with `--strict-review`,
`--deploy-gate --auto-approve`, and `--deploy-commit --deploy-branch <name>`.

## What exists today

| Piece | Behavior |
|-------|----------|
| `--resume` | Continue interrupted sprint for same goal — not periodic |
| `--deploy-commit` + `--deploy-branch` | Local commit on a branch — PR-ready, not pushed |
| `AGENTFORGE_JSON_LOG` | Observability for wrappers |

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TARGET_REPO` | cwd | Repo AgentForge reviews (`--target-repo`) |
| `BASE_BRANCH` | `main` | PR base; also used to count commits ahead |
| `AGENTFORGE_PRESET` | `harden` | Preset (`debug`, `fix`, `harden`, `factory`, …) |
| `AGENTFORGE_GOAL` | see script | Sprint goal text |
| `AGENTFORGE_BRANCH` | `agentforge/scheduled-<UTC ts>` | Override branch name |
| `AGENTFORGE_BIN` | auto-detect | Explicit `agentforge` or `python main.py` path |
| `AGENTFORGE_DRY_PR` | unset | Set `1` to skip push/PR (smoke the AgentForge run only) |
| `ANTHROPIC_API_KEY` | — | Required unless using Ollama (`AGENTFORGE_LLM_PROVIDER=ollama`) |

## Local cron example

```cron
# Every Monday 02:00 — review the factory app repo
0 2 * * 1 TARGET_REPO=/srv/factory-app /opt/agent-forge/scripts/scheduled-review-pr.sh >> /var/log/agentforge-scheduled.log 2>&1
```

## GitHub Actions (reference workflow)

Copy this into `.github/workflows/agentforge-scheduled.yml` in **your application repo** (adjust
`TARGET_REPO` / checkout paths), or in the `agent-forge` repo to dogfood it on itself. Requires the
repo secret `ANTHROPIC_API_KEY` and `permissions` for push + PR. It is **not** committed as an
active workflow here so a checkout never starts billing scheduled runs unexpectedly.

```yaml
name: AgentForge scheduled review

on:
  schedule:
    # Weekly — Monday 06:00 UTC (adjust to your timezone / cadence)
    - cron: "0 6 * * 1"
  workflow_dispatch:
    inputs:
      preset:
        description: AgentForge preset
        required: false
        default: harden
      goal:
        description: Sprint goal
        required: false
        default: "Scheduled production review: tests, security, and drift"

permissions:
  contents: write
  pull-requests: write

concurrency:
  group: agentforge-scheduled-${{ github.repository }}
  cancel-in-progress: false

jobs:
  review-and-pr:
    runs-on: ubuntu-latest
    # Skip fork PRs; scheduled runs are always on the default repo
    if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install AgentForge
        run: uv sync --group dev
        working-directory: agent-forge
        # If this workflow lives IN agent-forge (dogfood), use:
        # working-directory: .

      - name: Run scheduled review and open PR if needed
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          TARGET_REPO: ${{ github.workspace }}
          BASE_BRANCH: ${{ github.event.repository.default_branch }}
          AGENTFORGE_PRESET: ${{ github.event.inputs.preset || 'harden' }}
          AGENTFORGE_GOAL: ${{ github.event.inputs.goal || 'Scheduled production review: tests, security, and drift' }}
        run: ./scripts/scheduled-review-pr.sh
        working-directory: agent-forge
        # Dogfood in agent-forge repo only: working-directory: .

      - name: Upload deploy record
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: agentforge-deploy-record
          path: .agentforge/reports/deploy_record.md
          if-no-files-found: ignore
```

### Workflow notes

- **Dogfooding `agent-forge`:** put the workflow in the `agent-forge` repo; set both
  `working-directory` comments to `.` and `TARGET_REPO: ${{ github.workspace }}`.
- **Application repo:** vendor or submodule `agent-forge`, or `uv tool install` / `pip install`
  from GitHub and set `AGENTFORGE_BIN=agentforge`; point `TARGET_REPO` at the app checkout.
- **Cost control:** use `workflow_dispatch` only until you trust unattended runs; add `if:` on the
  schedule job to skip when there are no new commits on `main` since the last run.
- **Secrets:** never log `ANTHROPIC_API_KEY`; the script does not echo credentials.

## Cursor `/loop` equivalent

```text
/loop 6h Run agent-forge/scripts/scheduled-review-pr.sh with TARGET_REPO set to the open project.
      If AGENTFORGE_DRY_PR=1 first, smoke once before enabling push/PR.
```
