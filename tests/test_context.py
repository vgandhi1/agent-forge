from core.context import condense_markdown


def test_short_text_unchanged():
    text = "# Title\n\nshort body"
    assert condense_markdown(text, 1000) == text


def test_prefers_relevant_sections():
    finance = "# Finance\n" + ("budget tracking and expenses. " * 30)
    wellness = "# Wellness\n" + ("sleep hydration reminders. " * 30)
    text = wellness + "\n" + finance
    out = condense_markdown(text, len(finance) + 50, prefer=["finance", "budget"])
    assert "# Finance" in out
    assert "# Wellness" not in out  # less relevant section dropped
    assert "condensed" in out


def test_no_headings_truncates_with_marker():
    text = "x" * 5000
    out = condense_markdown(text, 1000)
    assert len(out) <= 1000 + 60
    assert "truncated" in out  # labeled, not a silent prefix cut


def test_keeps_document_order_among_chosen():
    a = "# A\n" + ("api endpoint " * 40)
    b = "# B\n" + ("filler " * 40)
    c = "# C\n" + ("api schema " * 40)
    text = a + "\n" + b + "\n" + c
    # budget fits the two api-relevant sections only
    out = condense_markdown(text, len(a) + len(c) + 40, prefer=["api"])
    assert "# A" in out and "# C" in out and "# B" not in out
    assert out.index("# A") < out.index("# C")  # original order preserved
