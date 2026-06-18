"""Unified-diff helpers for focused, diff-only reviews.

During ``--adaptive`` re-routing the Reviewer re-reads whole files on every revision, which is
expensive and dilutes focus on the actual fix. These pure helpers produce a bounded unified diff
between a prior snapshot and the current file so the Reviewer can judge the *change*, falling back
to reading the full file only when it needs broader context.
"""
from __future__ import annotations

import difflib


def unified_diff(old: str, new: str, path: str, *, max_chars: int = 4000) -> str:
    """Return a unified diff of ``old`` → ``new`` labeled with ``path``.

    Empty string when there is no change. Truncated with an explicit marker past ``max_chars`` so a
    large rewrite cannot blow the reviewer's context (the reviewer can still read_file for detail).
    """
    if old == new:
        return ""
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    text = "".join(diff)
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…[diff truncated — read_file for the full content]"
    return text
