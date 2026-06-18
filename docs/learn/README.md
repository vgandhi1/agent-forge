# The Forge — Agentic Systems learning module

An interactive, multi-page learning module that teaches **agentic systems** (theory) alongside their
**practical implementation in AgentForge**.

## Structure

A self-contained static site — no build step, no dependencies (fonts load from Google Fonts).

| File | Part | Content |
|------|------|---------|
| `agentic-systems.html` | Home | Entry point: what "agentic" means, theory↔practice framing, curriculum map |
| `theory.html` | 01 · Theory | The core loop (interactive), tool use, planning, memory, multi-agent, guardrails |
| `practice.html` | 02 · In AgentForge | Each idea mapped to real code: org, tool loop, `--adaptive`, context guards, guardrails |
| `labs.html` | 03 · Labs | Six copyable CLI exercises |
| `quiz.html` | 04 · Quiz | Knowledge check + glossary + source map |
| `index.html` | — | Redirect to `agentic-systems.html` (so the Pages root resolves) |
| `assets/forge.css` · `assets/forge.js` | — | Shared styles + interactivity (tab nav, copy buttons, loop simulator, quiz, progress ring) |

The top tab-bar links all pages; a progress ring (persisted in `localStorage`) tracks completion across
the whole module.

## View locally

Just open `agentic-systems.html` in a browser, or serve the folder:

```bash
cd docs/learn && python3 -m http.server 8000
# → http://localhost:8000/
```

## Deploy to GitHub Pages

Automated by [`.github/workflows/pages.yml`](../../.github/workflows/pages.yml).

**One-time setup:** repo **Settings → Pages → Build and deployment → Source = "GitHub Actions"**.

After that, any push to `main` touching `docs/learn/**` publishes to
**https://vgandhi1.github.io/agent-forge/**. All links are relative, so it works under that subpath.
