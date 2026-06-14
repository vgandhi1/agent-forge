from core.grounding import extract_salient_terms, grounding_gap

GOAL = (
    "Deliver review items #8-#10 as in-place changes to CLaimLens and QualityMind-RAG. "
    "Add an optional source_type enum on the ClaimNarrative model, extend evaluate.py to "
    "write models/metrics.json, and make data/generate_sample_data.py mirror published "
    "warranty theme frequencies."
)


def test_extracts_named_entities():
    terms = extract_salient_terms(GOAL)
    assert "claimlens" in terms
    assert "qualitymind-rag" in terms
    assert "claimnarrative" in terms
    assert "source_type" in terms
    assert "evaluate.py" in terms
    # File regex keeps the path prefix; snake regex also yields the bare identifier.
    assert "data/generate_sample_data.py" in terms
    assert "generate_sample_data" in terms


def test_filters_common_words():
    terms = extract_salient_terms("The system should process the data files for all users.")
    # No domain-specific entities → nothing salient to grade on.
    assert terms == set() or all(t not in {"system", "data", "files", "users"} for t in terms)


def test_grounded_artifact_passes():
    good = (
        "# CLaimLens Requirements\n"
        "Add source_type to the ClaimNarrative model. Extend evaluate.py and "
        "generate_sample_data.py. Integrate with QualityMind-RAG."
    )
    assert grounding_gap(GOAL, good) == []


def test_off_domain_artifact_flagged():
    # The DailyEase hallucination (F1): fluent, but references none of the goal entities.
    daily_ease = (
        "# DailyEase Requirements\n"
        "DailyEase helps users manage tasks, habits, finance, and wellness with reminders."
    )
    gap = grounding_gap(GOAL, daily_ease)
    assert gap, "off-domain artifact should be flagged"
    assert "claimlens" in gap
    assert "claimnarrative" in gap


def test_partial_grounding_below_threshold_flagged():
    # Mentions one entity in passing but is otherwise about the wrong product.
    partial = (
        "# DailyEase\n"
        "A tasks and habits app. It vaguely mentions source_type once but is not CLaimLens."
    )
    # source_type present, claimlens present as the word 'CLaimLens'? It says 'not CLaimLens' → present.
    # Still below 40% coverage of the full entity set → flagged.
    gap = grounding_gap(GOAL, partial)
    assert gap


def test_vague_goal_not_graded():
    # Fewer than min_terms salient entities → gate does not apply (no false positives).
    assert grounding_gap("Build a simple app for users", "totally unrelated text") == []
