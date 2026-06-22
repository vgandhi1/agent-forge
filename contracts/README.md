# Contract-revision POC

Proof that the AgentForge **orchestration engine** (multi-turn tool loop, independent reviewer
gate, revision cycle, scope/escalation tools) transfers to a non-SDLC domain — revising binary
documents — by swapping only the **tool layer** and the **personas**. Nothing under `core/` or
`agents/` is changed.

## What it does

Drives a `Drafter → Counsel → Reviewer` loop that edits real documents:

- **`.docx`** — clause-level text edits via the python-docx object model (formatting preserved).
- **`.pptx`** — slide/shape text edits via python-pptx.
- **`.pdf` (flattened / image-only)** — the title is *pixels*, not text. `retitle_pdf` removes the
  old title with content-aware **inpainting** (blends with the paper texture) and typesets a new
  one in a runtime-discovered serif font. `read_pdf` **OCRs** the title band so the reviewer can
  verify the rendered result — closing the gate without hardcoded boxes, fonts, or paths.

## Files

| File | Role |
|------|------|
| `doc_tools.py` | `DocStore` — path-sandboxed read/edit tools for docx, pptx, pdf (+ OCR) |
| `personas.py`  | Drafter / Counsel / Reviewer system prompts + Anthropic tool schemas |
| `llm.py`       | Provider adapter — Anthropic or local Ollama (same as AgentForge) |
| `poc.py`       | The orchestrator: tool loop + reviewer gate + revision cycle |
| `make_sample.py` | Generates a sample NDA `.docx` to revise |

## Install

```bash
uv pip install -e ".[contracts]"
# OCR needs the tesseract binary on PATH:  apt install tesseract-ocr   (or brew install tesseract)
```

## Run

```bash
# Offline proof — exercises the doc tools with NO LLM call
uv run python -m contracts.poc --dry-run

# Agentic loop on the sample NDA (provider/model from .env: Anthropic or Ollama)
uv run python -m contracts.poc --instruction "Extend the term from two (2) years to five (5) years."

# Against an existing document (relative to --root)
uv run python -m contracts.poc --root /path/to/dir --target "report.pdf" \
  --instruction "Retitle the poster to '(6) Habits of Mentally Strong People'."
```

## Notes / limitations

- **Raster fidelity is approximate** — serif is a discovered system font (not the original face);
  inpainting is clean over light/uniform paper, less so over heavy texture.
- **Local-Ollama tool-calling needs a working GPU backend.** On AMD cards whose arch lacks a
  bundled `rocblas` TensileLibrary (e.g. gfx1103 / Radeon 780M on older Ollama builds), `/api/chat`
  with tools returns HTTP 500 — upgrade Ollama to a build that ships kernels for the card, or run
  on CPU / Anthropic. Plain (non-tool) generation is unaffected.
