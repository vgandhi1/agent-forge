"""Web UI structured-progress parsing (web_ui._parse_event_line).

Closes feedback.md Part 3 (#6): the Web UI streamed raw log lines; it now parses the
AGENTFORGE_JSON_LOG events emitted on stderr into typed progress.
"""

from __future__ import annotations

import json

from web_ui import _parse_event_line


def test_parses_well_formed_event():
    line = json.dumps({"event": "phase_complete", "ts": "2026-06-08T00:00:00Z", "role": "qa"})
    event = _parse_event_line(line)
    assert event is not None
    assert event["event"] == "phase_complete"
    assert event["role"] == "qa"


def test_ignores_plain_log_text():
    assert _parse_event_line("Phase: BACKEND") is None
    assert _parse_event_line("") is None


def test_ignores_json_without_event_field():
    assert _parse_event_line(json.dumps({"role": "qa", "count": 3})) is None


def test_ignores_non_object_json():
    assert _parse_event_line("[1, 2, 3]") is None
    assert _parse_event_line("42") is None


def test_ignores_malformed_json():
    assert _parse_event_line('{"event": "phase_complete"') is None
