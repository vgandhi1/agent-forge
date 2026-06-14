"""Post-run artifact sanity: catch thin/placeholder spec documents at the deploy gate.

The architect in agentforge-failure.md (F3) emitted a document that was all section headers
and "will be documented separately" placeholders — fluent-looking but empty of design. The
reviewer death-spiral (F2) meant it was force-accepted anyway. As a model-independent backstop,
the deploy gate re-reads the accepted spec docs and refuses to ship one that has no real
content. Pairs with the goal-grounding gate (on-topic) — this covers the non-trivial half.

Pure functions only (no I/O) so they are unit-testable.
"""
from __future__ import annotations

import re

# Spec documents we grade for substance. Code and reports are out of scope (they have their
# own verify step) — only the prose deliverables the architect/PM author.
_GRADED_DOCS = ("requirements.md", "architecture.md", "design.md")

_MIN_SUBSTANTIVE_CHARS = 200

# "Will be documented later" style deferrals — fluent filler that carries no design.
_PLACEHOLDER = re.compile(
    r"""(?ix)
    will\s+be\s+(addressed|documented|detailed|added|covered|provided|defined|implemented|specified|elaborated) |
    (in|as)\s+a\s+(separate|subsequent|future|follow[- ]?up|later)\s+(document|ticket|doc|pr|sprint|phase|section) |
    documented\s+separately |
    addressed\s+(later|separately|elsewhere) |
    \bTBD\b | \bTODO\b | to\s+be\s+(determined|defined|decided|added|completed)
    """
)

# The reviewer's no-verdict fallback string — if it shows up *in an artifact*, the agent echoed
# the error back as its document (exactly the F3 architecture.md).
_REVIEWER_ERROR = "did not submit a verdict"


def _body_paragraphs(content: str) -> list[str]:
    """Non-empty lines that are neither markdown headings nor bullets (the actual prose)."""
    out: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-", "*", ">")):
            continue
        out.append(line)
    return out


def is_graded_doc(path: str) -> bool:
    """True if ``path`` is a spec document we grade for substance."""
    name = path.rsplit("/", 1)[-1].lower()
    return name.endswith(tuple(d for d in _GRADED_DOCS)) or name in _GRADED_DOCS


def thin_artifact_reason(path: str, content: str) -> str | None:
    """Return why a graded spec doc is thin/placeholder, or None if it has real substance.

    Flags three failure shapes seen in F3: a near-empty stub, a document dominated by
    "will be documented separately" deferrals, and one that echoes the reviewer error string.
    Non-graded paths (code, reports) and substantive docs return None.
    """
    if not is_graded_doc(path):
        return None

    text = content.strip()
    if _REVIEWER_ERROR in text.lower():
        return "echoes the reviewer error string instead of real content"

    # Substantive characters = everything that is not a heading line.
    substantive = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#")).strip()
    if len(substantive) < _MIN_SUBSTANTIVE_CHARS:
        return f"only {len(substantive)} chars of non-heading content (stub)"

    paras = _body_paragraphs(text)
    if paras:
        placeholder = sum(1 for p in paras if _PLACEHOLDER.search(p))
        if placeholder / len(paras) >= 0.5:
            return f"{placeholder}/{len(paras)} body paragraphs are deferred placeholders (no design)"

    return None
