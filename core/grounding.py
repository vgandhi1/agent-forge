"""Goal-grounding gate: cheap, model-independent relevance check for artifacts.

A weak model can author a fluent document for the *wrong* product (see the DailyEase
hallucination in agentforge-failure.md, F1). Before an artifact is handed to the reviewer
we check that it actually references the concrete, named entities in the sprint goal
(product names, file names, identifiers). This catches off-domain drift with a keyword
check — no extra model call — and is independent of which LLM produced the text.

Pure functions only (no I/O) so they are unit-testable.
"""
from __future__ import annotations

import re

# Tokens that look salient but carry no domain signal — never count them as entities.
_STOPWORDS = frozenset({
    "this", "that", "with", "from", "into", "your", "their", "there", "these", "those",
    "should", "could", "would", "must", "will", "shall", "have", "https", "http", "www",
    "data", "code", "file", "files", "test", "tests", "user", "users", "system", "api",
    "the", "and", "for", "are", "not",
})

# CamelCase / PascalCase / hyphenated brand names, e.g. CLaimLens, QualityMind-RAG, ClaimNarrative.
_CAMEL = re.compile(r"\b[A-Za-z][A-Za-z0-9]*[A-Z0-9][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b")
# File names, e.g. evaluate.py, generate_sample_data.py, metrics.json.
_FILE = re.compile(r"\b[\w./-]+\.(?:py|md|json|ya?ml|toml|sql|txt|csv|ini|cfg)\b", re.IGNORECASE)
# snake_case identifiers, e.g. source_type, generate_sample_data.
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
# ALL-CAPS acronyms length >= 3, e.g. RAG, NFR.
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")
# Backtick- or quote-wrapped names.
_QUOTED = re.compile(r"[`\"']([A-Za-z][\w./-]{2,})[`\"']")


def extract_salient_terms(goal: str) -> set[str]:
    """Extract the concrete, named entities a faithful artifact should reference.

    Returns a lowercased set of product names, file names, identifiers, and acronyms found
    in the goal. Common English/boilerplate words are filtered out so the gate keys on
    domain-specific terms only.
    """
    terms: set[str] = set()
    for pat in (_CAMEL, _FILE, _SNAKE, _ACRONYM):
        terms.update(m.group(0) for m in pat.finditer(goal))
    terms.update(m.group(1) for m in _QUOTED.finditer(goal))

    cleaned: set[str] = set()
    for t in terms:
        norm = t.strip().lower()
        if len(norm) < 4 and not norm.isupper():
            # Keep short acronyms (RAG) but drop tiny noise tokens.
            if not (len(norm) >= 3 and t.isupper()):
                continue
        if norm in _STOPWORDS:
            continue
        cleaned.add(norm)
    return cleaned


def grounding_gap(goal: str, text: str, *, min_terms: int = 3, min_coverage: float = 0.4) -> list[str]:
    """Return the salient goal terms missing from ``text`` when it is under-grounded.

    The gate only applies when the goal has at least ``min_terms`` salient entities (a vague
    goal is not graded). When it applies and the artifact references fewer than
    ``min_coverage`` of those entities, the full list of *missing* terms is returned so the
    rejection notes are actionable. An empty list means the artifact is sufficiently grounded
    (or the gate did not apply).
    """
    terms = extract_salient_terms(goal)
    if len(terms) < min_terms:
        return []  # goal too vague to grade — do not block
    lowered = text.lower()
    present = {t for t in terms if t in lowered}
    coverage = len(present) / len(terms)
    if coverage >= min_coverage:
        return []
    return sorted(terms - present)
