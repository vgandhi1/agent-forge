---
description: AgentForge — end-to-end factory data + AI application lifecycle for a goal
argument-hint: [factory app goal]
allowed-tools: Bash(uv run:*), Bash(python main.py:*)
---

Run the **factory** preset — the full data + AI lifecycle (PM → Architect → Data Engineer →
ML Engineer → Backend → QA → DevOps, with reviewer gating):

```bash
uv run python main.py --preset factory --goal "$ARGUMENTS"
```

- Greenfield equivalent of `/agentforge` (full) but with data + ML layers added.
- Long run (7 phases × generate + review) — let it run; consider `--plan-gate` for control and
  `--dry-run` to preview provider/models first. Artifacts land under `workspace/`.
- If `$ARGUMENTS` is empty, ask the Project Owner for the goal first.
