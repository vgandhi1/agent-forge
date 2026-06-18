#!/usr/bin/env python
"""LLM-as-a-Judge: score artifact quality against a rubric.

The deterministic test suite uses *faked* LLM calls — great for orchestrator plumbing,
but it can't catch a silently degraded prompt that still produces structurally valid
output. This module closes that gap: a small, cheap model grades a produced artifact
against an explicit rubric and returns numeric scores, so prompt-quality regressions
become visible.

Design:

* The **core is pure** — ``build_prompt`` / ``parse_verdict`` / ``weighted_score`` have no
  I/O, so they're unit-testable with a fake completer.
* The **LLM call is injected** as a ``Completer`` (``str -> str``). ``default_completer``
  wires the real provider (Anthropic or Ollama) and is only used in live mode.
* Scores are normalised to 0..1 and compared to a threshold for a pass/fail verdict.

This never runs in the default eval/CI path; it is opt-in (``run_evals.py --judge`` or a
``@pytest.mark.live`` test) because it costs tokens and is non-deterministic.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

# A completer turns a prompt into the model's raw text response.
Completer = Callable[[str], str]

DEFAULT_JUDGE_MODEL_ANTHROPIC = "claude-3-5-haiku-latest"
DEFAULT_JUDGE_MODEL_OLLAMA = "llama3.2"
DEFAULT_THRESHOLD = 0.7
DEFAULT_SCALE = 5
_MAX_ARTIFACT_CHARS = 6000


class JudgeError(RuntimeError):
    """Raised when a judge verdict cannot be parsed into the rubric's criteria."""


@dataclass(frozen=True)
class Criterion:
    """One rubric dimension the judge scores from 1..scale."""

    key: str
    description: str
    weight: float = 1.0


@dataclass
class JudgeResult:
    scores: dict[str, int]
    rationale: dict[str, str]
    weighted: float
    threshold: float
    passed: bool
    raw: str = field(repr=False, default="")


def parse_criteria(raw: Sequence[dict] | None) -> list[Criterion]:
    """Build ``Criterion`` objects from a scenario's ``rubric:`` list.

    Each item needs ``key`` + ``description``; ``weight`` defaults to 1.0.
    """
    criteria: list[Criterion] = []
    for item in raw or []:
        if not isinstance(item, dict) or "key" not in item or "description" not in item:
            raise JudgeError("each rubric item needs 'key' and 'description'")
        weight = float(item.get("weight", 1.0))
        if weight <= 0:
            raise JudgeError(f"rubric '{item['key']}' weight must be > 0")
        criteria.append(Criterion(str(item["key"]), str(item["description"]), weight))
    if not criteria:
        raise JudgeError("rubric must define at least one criterion")
    return criteria


def build_prompt(
    goal: str,
    artifact_name: str,
    artifact_text: str,
    criteria: Sequence[Criterion],
    *,
    scale: int = DEFAULT_SCALE,
    max_chars: int = _MAX_ARTIFACT_CHARS,
) -> str:
    """Render the judging prompt. The artifact is truncated to bound token cost."""
    body = artifact_text.strip()
    if len(body) > max_chars:
        body = body[:max_chars] + "\n…[truncated for judging]…"
    lines = [
        "You are a strict but fair senior engineer grading a work artifact produced by an "
        "AI software team. Score ONLY against the rubric. Do not reward verbosity.",
        "",
        f"GOAL THE ARTIFACT SERVES:\n{goal.strip()}",
        "",
        f"RUBRIC (score each {1}-{scale}; {scale} = excellent, 1 = absent/wrong):",
    ]
    for c in criteria:
        lines.append(f"- {c.key}: {c.description}")
    lines += [
        "",
        f"ARTIFACT ({artifact_name}):",
        "-----",
        body,
        "-----",
        "",
        "Respond with ONLY a JSON object, no prose, of the form:",
        '{"scores": {' + ", ".join(f'"{c.key}": <int>' for c in criteria) + "}, "
        '"rationale": {' + ", ".join(f'"{c.key}": "<one sentence>"' for c in criteria) + "}}",
    ]
    return "\n".join(lines)


def _extract_json(raw: str) -> dict:
    """Pull the first JSON object out of a model response (tolerates code fences/prose)."""
    if not raw or not raw.strip():
        raise JudgeError("empty judge response")
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise JudgeError("no JSON object found in judge response")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeError(f"judge response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JudgeError("judge JSON must be an object")
    return data


def parse_verdict(
    raw: str, criteria: Sequence[Criterion], *, scale: int = DEFAULT_SCALE
) -> tuple[dict[str, int], dict[str, str]]:
    """Parse + clamp a judge response into ``(scores, rationale)`` for every criterion."""
    data = _extract_json(raw)
    scores_raw = data.get("scores", data)
    rationale_raw = data.get("rationale", {})
    if not isinstance(scores_raw, dict):
        raise JudgeError("'scores' must be an object")
    scores: dict[str, int] = {}
    rationale: dict[str, str] = {}
    for c in criteria:
        if c.key not in scores_raw:
            raise JudgeError(f"judge omitted required criterion '{c.key}'")
        try:
            value = int(round(float(scores_raw[c.key])))
        except (TypeError, ValueError) as exc:
            raise JudgeError(f"criterion '{c.key}' score is not numeric") from exc
        scores[c.key] = max(1, min(scale, value))
        if isinstance(rationale_raw, dict):
            rationale[c.key] = str(rationale_raw.get(c.key, ""))
        else:
            rationale[c.key] = ""
    return scores, rationale


def weighted_score(
    scores: dict[str, int], criteria: Sequence[Criterion], *, scale: int = DEFAULT_SCALE
) -> float:
    """Normalise weighted criterion scores to a single 0..1 value."""
    if scale <= 1:
        raise JudgeError("scale must be > 1")
    total_weight = sum(c.weight for c in criteria)
    if total_weight <= 0:
        raise JudgeError("total rubric weight must be > 0")
    acc = 0.0
    for c in criteria:
        normalised = (scores[c.key] - 1) / (scale - 1)  # 1->0.0 … scale->1.0
        acc += c.weight * normalised
    return acc / total_weight


def judge(
    goal: str,
    artifact_name: str,
    artifact_text: str,
    criteria: Sequence[Criterion],
    completer: Completer,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    scale: int = DEFAULT_SCALE,
) -> JudgeResult:
    """Grade ``artifact_text`` against ``criteria`` using ``completer`` for the LLM call."""
    prompt = build_prompt(goal, artifact_name, artifact_text, criteria, scale=scale)
    raw = completer(prompt)
    scores, rationale = parse_verdict(raw, criteria, scale=scale)
    weighted = weighted_score(scores, criteria, scale=scale)
    return JudgeResult(
        scores=scores,
        rationale=rationale,
        weighted=weighted,
        threshold=threshold,
        passed=weighted >= threshold,
        raw=raw,
    )


# --------------------------------------------------------------------------------------
# Default (live) completer — only imported/used when actually judging with a real model.
# --------------------------------------------------------------------------------------

def _provider() -> str:
    return os.getenv("AGENTFORGE_LLM_PROVIDER", "anthropic").strip().lower()


def _anthropic_complete(prompt: str, model: str, *, max_tokens: int = 1024) -> str:
    from anthropic import Anthropic  # local import: keeps the pure core import-light

    client = Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in msg.content if getattr(block, "type", None) == "text"
    )


def _ollama_complete(prompt: str, model: str) -> str:
    import httpx

    from core.ollama_url import validate_ollama_base_url

    base = validate_ollama_base_url(
        os.getenv("AGENTFORGE_OLLAMA_BASE_URL", "http://localhost:11434")
    )
    resp = httpx.post(
        f"{base}/api/chat",
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
        timeout=httpx.Timeout(120.0, connect=15.0),
    )
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "")


def default_completer() -> Completer:
    """Return a live completer bound to the configured provider/model.

    Honour ``AGENTFORGE_JUDGE_MODEL`` to force a specific (ideally small/cheap) judge model.
    """
    provider = _provider()
    if provider == "ollama":
        model = os.getenv("AGENTFORGE_JUDGE_MODEL", DEFAULT_JUDGE_MODEL_OLLAMA)
        return lambda prompt: _ollama_complete(prompt, model)
    model = os.getenv("AGENTFORGE_JUDGE_MODEL", DEFAULT_JUDGE_MODEL_ANTHROPIC)
    return lambda prompt: _anthropic_complete(prompt, model)
