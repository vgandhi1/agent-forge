from core.artifact_quality import is_graded_doc, thin_artifact_reason

# The actual F3 architecture.md: section headers + "will be documented separately" placeholders.
F3_ARCHITECTURE = """# Architecture
- System Overview Diagram (ASCII art)
- Technology Stack (with versions and rationale)
- Database Schema (table definitions with types and constraints)

## Features #8-#10
Detailed architecture for features #8-#10 will be addressed in subsequent documents or tickets.

## Integration with Ollama via WSL
The integration with Ollama via WSL will be detailed in a separate document or ticket.

## Synthetic Data Generation
The design for synthetic data generation will also be documented separately.
"""

SUBSTANTIVE = """# Architecture

## Database Schema
The ClaimNarrative table stores id, text, source_type, and label columns. The label is one of
the five locked taxonomy values and is indexed for the Pareto trend report aggregation query.

## API Design
POST /classify accepts a ClaimNarrative and returns label + confidence. When confidence is
below 0.55 the response sets needs_review=true so a human triages it before it counts.
"""


def test_is_graded_doc():
    assert is_graded_doc("docs/architecture.md")
    assert is_graded_doc("workspace/docs/requirements.md")
    assert not is_graded_doc("dailyease/app/main.py")
    assert not is_graded_doc("reports/qa_report.md")


def test_placeholder_dominant_doc_flagged():
    reason = thin_artifact_reason("docs/architecture.md", F3_ARCHITECTURE)
    assert reason is not None
    assert "placeholder" in reason


def test_two_line_stub_flagged():
    stub = "# Architecture\n- Reviewer did not submit a verdict — resubmit the artifact for review.\n"
    reason = thin_artifact_reason("docs/architecture.md", stub)
    assert reason is not None  # echoes reviewer error


def test_short_stub_flagged():
    reason = thin_artifact_reason("docs/architecture.md", "# Architecture\n\nTODO.\n")
    assert reason is not None


def test_substantive_doc_passes():
    assert thin_artifact_reason("docs/architecture.md", SUBSTANTIVE) is None


def test_non_graded_path_ignored():
    assert thin_artifact_reason("dailyease/main.py", "x = 1") is None
