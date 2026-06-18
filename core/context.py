"""Selective context condensing.

Agents used to pass fixed byte slices of upstream docs (e.g. ``arch[:4000]``), which
silently drops the entire tail of a document. ``condense_markdown`` instead keeps whole
sections, prioritizing the ones relevant to the current task, and labels what it dropped.
"""
from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Good enough for budget gating, not billing."""
    return (len(text or "") + 3) // 4


def rolling_state_block(
    entries: dict[str, str],
    *,
    max_chars: int = 4000,
    keep_recent: int = 12,
) -> str:
    """Pack an ordered decisions/state log into a bounded "tightly packed state block".

    ``entries`` is chronological (dict insertion order; most recent last). When the full render
    fits in ``max_chars`` it is returned verbatim. Otherwise the most recent ``keep_recent`` entries
    are kept verbatim (recency matters most), as many older entries as the remaining budget allows
    are kept truncated, and any further-back entries collapse into a single count line. This bounds
    the cross-phase context replay that otherwise grows unbounded and triggers token exhaustion /
    "lost in the middle" during long adaptive loops.
    """
    items = list(entries.items())
    if not items:
        return ""

    def render(pairs: list[tuple[str, str]]) -> list[str]:
        return [f"- {k}: {v}" for k, v in pairs]

    full = "\n".join(render(items))
    if len(full) <= max_chars:
        return full

    keep_recent = max(0, keep_recent)
    recent = items[len(items) - keep_recent:] if keep_recent else []
    older = items[: len(items) - len(recent)]
    recent_lines = render(recent)

    budget = max_chars - len("\n".join(recent_lines))
    older_kept: list[str] = []
    omitted = 0
    for k, v in reversed(older):  # newest-older first
        snippet = v[:80].rstrip()
        line = f"- {k}: {snippet}" + ("…" if len(v) > 80 else "")
        if budget - (len(line) + 1) > 0:
            older_kept.append(line)
            budget -= len(line) + 1
        else:
            omitted += 1
    older_kept.reverse()

    parts: list[str] = []
    if omitted:
        parts.append(f"- …[{omitted} earlier decision(s) condensed]")
    parts.extend(older_kept)
    parts.extend(recent_lines)
    return "\n".join(parts)


def _split_sections(text: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))
    return sections


def condense_markdown(text: str, max_chars: int, prefer: list[str] | None = None) -> str:
    """Return ``text`` shortened to ~``max_chars``, keeping the most relevant sections whole.

    Sections (split on Markdown headings) that contain any ``prefer`` keyword are kept first;
    remaining budget is filled in document order. A document with no headings is truncated with
    an explicit marker. Returns the input unchanged when it already fits.
    """
    text = text or ""
    if len(text) <= max_chars:
        return text

    keywords = [k.lower() for k in (prefer or [])]
    sections = _split_sections(text)

    def relevance(section: str) -> int:
        s = section.lower()
        return sum(s.count(k) for k in keywords)

    # Most relevant first, ties broken by original order (stable).
    order = sorted(range(len(sections)), key=lambda i: (-relevance(sections[i]), i))

    chosen: dict[int, str] = {}
    budget = max_chars
    for i in order:
        if budget <= 0:
            break
        section = sections[i]
        if len(section) <= budget:
            chosen[i] = section
            budget -= len(section)
        elif budget > 200:
            chosen[i] = section[:budget].rstrip() + "\n…[section truncated]"
            budget = 0

    if not chosen:  # single oversized section, no headings
        return text[:max_chars].rstrip() + "\n\n…[context condensed to fit]"

    out = "\n".join(chosen[i] for i in sorted(chosen))
    if len(chosen) < len(sections):
        out += "\n\n…[context condensed: less-relevant sections omitted]"
    return out


def doc_reference(
    path: str,
    content: str,
    *,
    label: str,
    digest_chars: int = 1800,
    prefer: list[str] | None = None,
) -> str:
    """Build a path-first context block: a short digest plus a pointer to read the full doc.

    Workers now have ``read_file`` (paginated), so instead of inlining a large condensed blob —
    which silently drops the rest of the document — give a small orientation digest and the
    canonical path so the agent reads the full doc on demand. Returns ``""`` when there is no
    content. When the doc already fits inside ``digest_chars`` it is inlined whole (no pointer
    needed). Otherwise the block names the path and tells the agent to ``read_file`` for detail.
    """
    content = content or ""
    if not content.strip():
        return ""
    if len(content) <= digest_chars:
        return f"{label} (full, at `{path}`):\n```markdown\n{content}\n```\n\n"
    digest = condense_markdown(content, digest_chars, prefer)
    return (
        f"{label} — digest below; **read the full document with read_file at `{path}`** "
        f"before relying on details:\n```markdown\n{digest}\n```\n\n"
    )
