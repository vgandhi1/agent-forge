"""Selective context condensing.

Agents used to pass fixed byte slices of upstream docs (e.g. ``arch[:4000]``), which
silently drops the entire tail of a document. ``condense_markdown`` instead keeps whole
sections, prioritizing the ones relevant to the current task, and labels what it dropped.
"""
from __future__ import annotations


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
