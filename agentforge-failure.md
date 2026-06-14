# AgentForge Design-Preset Failure — Investigation Report

**Date:** 2026-06-13
**Run:** `agentforge --preset design --goal "Deliver review items #8-#10 ... CLaimLens / QualityMind-RAG ..."`
**Outcome:** Sprint reported "complete" but **both deliverables were unusable**. Items #8–#10 were
subsequently implemented by hand (see `quality-engineering/CLaimLens/docs/`).
**Severity:** High — pipeline emitted a green "Sprint Complete" + "Deploy recorded" on
garbage output. Failure was silent at the orchestration layer.

---

## 1. TL;DR

The run used the **local Ollama model `qwen2.5:7b-instruct`** because **no
`ANTHROPIC_API_KEY` was configured** (`.env` has `AGENTFORGE_LLM_PROVIDER=ollama`, and the
key is absent). That model was too weak for the task and produced:

- `workspace/docs/requirements.md` — a **hallucinated, wrong product** ("DailyEase", a
  consumer tasks/habits/finance app) instead of the CLaimLens warranty-NLP goal.
- `workspace/docs/architecture.md` — a **2-line stub** with no architecture at all.

The orchestrator did not catch either: PM output was *approved* by the reviewer despite
being off-domain, and the architect output was *force-accepted* after hitting the
max-revision cap with unresolved findings — then the deploy gate recorded success.

---

## 2. Configuration at time of failure

From `Agents/agent-forge/.env`:

| Setting | Value |
|---|---|
| `AGENTFORGE_LLM_PROVIDER` | `ollama` |
| `AGENTFORGE_OLLAMA_HOST` | `http://172.17.48.1:11434` (Windows host via WSL2 gateway) |
| `AGENTFORGE_OLLAMA_MODEL` | `qwen2.5:7b-instruct` (all roles — no per-role overrides set) |
| `ANTHROPIC_API_KEY` | **absent / empty** |
| Per-role Anthropic models | all commented out |

**Root contributing condition:** AgentForge's default provider is `anthropic`, but the
environment had no Anthropic key, so the operator had switched the whole pipeline to a
single 7B local model serving **every** role (lead, PM, architect, reviewer). A 7B
instruct model is not reliable for multi-step spec authoring + structured tool/verdict
output.

---

## 3. Timeline (local WSL time; deploy record is UTC, +5h offset)

```
17:19:38  PM phase start (model ok)
17:21:32  PM wrote docs/requirements.md
17:23:28  PM tool loop done (1 call, 2 steps)
17:23:52  Reviewer audit start (attempt 1)
17:25:38  Reviewer APPROVED pm artifact   ← off-domain doc approved
17:26:04  ARCHITECT phase start
~17:31    Reviewer rejected architect (must-fix: "Reviewer did not submit a verdict — resubmit")
~17:31    Architect revision 1
~17:33    Reviewer audit attempt 2 (13–14 tool calls, no valid verdict)
~17:41    Reviewer rejected again → max revisions hit
          [FLAGGED] accepted architect artifact after max revisions with unresolved findings
17:41:04  Sprint Complete → Deploy gate: Verify skipped (autonomous) → Deploy recorded
```

The architect↔reviewer loop burned ~14 model calls per audit cycle across 3 cycles and
never converged because the reviewer could not emit a structured verdict.

---

## 4. Failure modes (distinct bugs, ranked)

### F1 — Model substituted a hallucinated product for the actual goal (PM)
`requirements.md` describes "DailyEase" with Tasks / Habits / Finance / Wellness modules.
The real goal (CLaimLens warranty-narrative classifier, items #8–#10) appears only as
loose keywords crammed into the wrong modules (e.g. `source_type` filed under "Tasks
Module"). Zero mention of CLaimLens, QualityMind-RAG, `ClaimNarrative`, the locked
5-label taxonomy, `evaluate.py`, or `generate_sample_data.py`.
→ **Cause:** 7B model anchored on a generic SaaS-PRD template from its training prior and
ignored the concrete goal. Classic small-model instruction-drift.

### F2 — Reviewer cannot produce a structured verdict (architect phase)
Every architect audit ended with the must-fix *"Reviewer did not submit a verdict —
resubmit the artifact for review."* The reviewer agent ran 13–14 tool calls per cycle but
never returned the verdict schema the orchestrator expected.
→ **Cause:** 7B model cannot reliably follow the tool-call / structured-output contract
for the reviewer role. The architect was therefore never given actionable feedback.

### F3 — Architect produced a stub, never a design
`architecture.md` in full:
```
# Architecture
- Reviewer did not submit a verdict — resubmit the artifact for review.
```
The architect echoed the reviewer's error string back as its "document."
→ **Cause:** starved of a real verdict (F2), the architect had no signal and degenerated.

### F4 — Runtime/config context leaked into the design brief
`workspace/handoff/architect.md` brief contains: *"focusing on integrating Ollama within
Windows using WSL (ollama_integration_technique)"*. The model injected its own execution
environment into the product brief — irrelevant to the goal.
→ **Cause:** context bleed; the small model mixed system/runtime context into task output.

### F5 — Orchestrator reports success on unusable output (process bug, model-independent)
This is the most important finding for the framework itself:
- The reviewer **approved** an off-domain PM artifact (no goal-grounding / relevance gate).
- The architect artifact was **force-accepted** after max revisions *with unresolved
  findings*, then flowed straight into a **deploy record** marked success.
- "Verify: skipped — autonomous run" + `deploy_record.md` "Decision: autonomous" means a
  flagged-quality-debt run still ends in a green terminal state.

Even with a weak model, a pipeline should **fail closed**, not emit "Sprint Complete".

---

## 5. Root cause

**Primary:** No `ANTHROPIC_API_KEY` → fallback to a single 7B local model (`qwen2.5:7b-instruct`)
across all roles → it lacked the capability for goal-faithful spec authoring (F1) and for
structured reviewer verdicts (F2 → F3 → F4).

**Secondary (framework):** AgentForge lacks (a) a goal-grounding / relevance gate on PM
output, and (b) a fail-closed policy when an artifact is accepted only via the
max-revision override with unresolved findings. The "[FLAGGED]" state should block the
deploy gate, not pass through it (F5).

---

## 6. Recommendations

### Local-only operation (Ollama, multiple models) — required path

This deployment runs **local models only** (no Anthropic key; CLaimLens itself is fully
offline). A single 7B model serving every role is the proximate cause of F1–F4. Fix is to
match model capability to role difficulty using the per-role override env vars
(`AGENTFORGE_OLLAMA_MODEL_<ROLE>`), which resolve for **every** role including `reviewer`
(verified — note `reviewer` is not listed in `.env.example` but is supported).

The structure-heavy roles — **reviewer** (tool/verdict contract → F2) and **PM / architect**
(instruction-following → F1) — must not run on a 7B tag. Recommended `.env`:

```bash
AGENTFORGE_LLM_PROVIDER=ollama
AGENTFORGE_OLLAMA_HOST=http://172.17.48.1:11434   # Windows host via WSL2 gateway
AGENTFORGE_OLLAMA_TRUST_LAN=1

# Floor for cheap roles (devops / data_engineer / ml_engineer fall back to this)
AGENTFORGE_OLLAMA_MODEL=qwen2.5:7b-instruct

# Structure-heavy roles — bump these (fixes F1/F2)
AGENTFORGE_OLLAMA_MODEL_REVIEWER=qwen2.5:14b-instruct
AGENTFORGE_OLLAMA_MODEL_PM=qwen2.5:14b-instruct
AGENTFORGE_OLLAMA_MODEL_ARCHITECT=qwen2.5:14b-instruct
AGENTFORGE_OLLAMA_MODEL_LEAD=qwen2.5:14b-instruct

# Code roles — coder variant
AGENTFORGE_OLLAMA_MODEL_BACKEND=qwen2.5-coder:14b
AGENTFORGE_OLLAMA_MODEL_QA=qwen2.5-coder:7b
```

Pull the tags first (only `qwen2.5:7b-instruct` was installed at failure time):

```bash
ollama pull qwen2.5:14b-instruct
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:7b
```

Sizing by VRAM (q4):

| VRAM | Reviewer / PM / Architect / Lead | Code roles | Notes |
|---|---|---|---|
| ~8 GB | `qwen2.5:7b-instruct` (floor) | 7b | Reviewer **will** flake; the new preflight aborts early instead of looping. |
| ~16 GB | `qwen2.5:14b-instruct` | `qwen2.5-coder:14b` / `:7b` | Sweet spot — clears F1/F2. |
| 24 GB+ | `qwen2.5:32b-instruct` | `qwen2.5-coder:14b` | Best local fidelity. |

Why qwen2.5: it is the installed family and advertises `tools` capability (`/api/tags`).
The reviewer's `submit_review` needs reliable tool-calling; qwen2.5 becomes dependable at
14B+. Verify resolution with `agentforge-dry-run` (shows the per-role model table, no API call).

### Framework hardening (model-independent) — status

3. **Goal-grounding gate — ✅ implemented.** `core/grounding.py` extracts the goal's named
   entities (product names, file names, identifiers) and `LeadAgent._grounding_gap` rejects a
   PM/architect artifact that references too few of them, *before* spending a reviewer call.
   This catches the F1 DailyEase substitution immediately. Bypass: `AGENTFORGE_SKIP_GROUNDING=1`.
4. **Fail-closed on flagged accept — ✅ implemented** (PR #13). An artifact force-accepted
   after the max-revision cap now **blocks** the deploy by default (autonomous *and* gated)
   and exits non-zero (2). `--allow-quality-debt` / `AGENTFORGE_ALLOW_QUALITY_DEBT` is the
   explicit escape hatch; `--strict-review` is now a deprecated no-op (its behavior is default).
5. **Verdict-schema preflight — ✅ implemented.** `LeadAgent._reviewer_preflight` smoke-tests
   the reviewer model on a trivial fixture before any phase; if it cannot emit a structured
   verdict the run aborts early with a clear error naming the reviewer model and a stronger-tag
   suggestion — instead of the F2 death-spiral that burned ~40+ calls. Bypass:
   `AGENTFORGE_SKIP_REVIEWER_PREFLIGHT=1`.
6. **Context hygiene — ⬜ open.** Strip runtime/system/config context from role briefs so it
   cannot leak into product artifacts (F4).

### Verification
7. ⬜ Open: add a post-run assertion that emitted docs are non-trivial (length / section
   presence) and on-topic before recording a deploy. (The grounding gate (#3) now covers the
   on-topic half at review time.)

---

## 7. Evidence / artifacts

- `workspace/docs/requirements.md` — DailyEase hallucination (F1).
- `workspace/docs/architecture.md` — 2-line stub (F3).
- `workspace/handoff/architect.md` — leaked Ollama/WSL brief (F4); review note "lacks
  necessary details".
- `workspace/reports/deploy_record.md` — "complete / autonomous" + "⚠ Unresolved review
  findings (quality debt) ... accepted after 3 revision cycles" (F5).
- `workspace/handoff/checkpoint.json` — completed: [pm, architect].
- Run log: `/tmp/af_design.log` (phase timings, repeated "did not submit a verdict").

## 8. Resolution

Items #8–#10 were implemented by hand against the real repos and guardrails:
- Specs: `quality-engineering/CLaimLens/docs/REQUIREMENTS-items-8-10.md`,
  `ARCHITECTURE-items-8-10.md`.
- Code: CLaimLens `claimlens/`, `evaluate.py`, `data/generate_sample_data.py` — 58 tests
  pass, ruff clean, holdout macro-F1 0.896 ≥ 0.88.
- **No item was blocked by missing API keys** — the CLaimLens path is fully offline. The
  only API-key impact was degrading AgentForge itself.
