"""Data-mocking tools: deterministic synthetic datasets for local pipeline/model testing, plus the
generate_mock_data tool handler that writes a fixture through the sandboxed artifact store."""

import csv
import io
import json

import pytest
from rich.console import Console

from agents.data_engineer import DataEngineerAgent
from core import artifact_store, mockdata
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


# --------------------------------------------------------------------------- pure generator


_SCHEMA = [
    {"name": "id", "type": "id"},
    {"name": "temp_c", "type": "float", "min": 20.0, "max": 30.0, "precision": 2},
    {"name": "rpm", "type": "int", "min": 1000, "max": 2000},
    {"name": "state", "type": "category", "values": ["ok", "warn", "fault"]},
    {"name": "ok", "type": "bool"},
    {"name": "ts", "type": "timestamp"},
]


def test_generate_rows_deterministic_and_bounded():
    a = mockdata.generate_rows(_SCHEMA, 10, seed=42)
    b = mockdata.generate_rows(_SCHEMA, 10, seed=42)
    assert a == b  # deterministic per seed
    assert len(a) == 10
    # id sequential & unique
    assert [r["id"] for r in a] == list(range(1, 11))
    for r in a:
        assert 20.0 <= r["temp_c"] <= 30.0
        assert 1000 <= r["rpm"] <= 2000
        assert r["state"] in {"ok", "warn", "fault"}
        assert isinstance(r["ok"], bool)


def test_generate_rows_caps_at_max():
    rows = mockdata.generate_rows([{"name": "x", "type": "int"}], 99999)
    assert len(rows) == mockdata.MAX_ROWS


def test_generate_rows_skips_unnamed_columns():
    rows = mockdata.generate_rows([{"type": "int"}, {"name": "y", "type": "int"}], 2)
    assert all(set(r.keys()) == {"y"} for r in rows)


def test_render_csv_json_jsonl():
    rows = mockdata.generate_rows(_SCHEMA, 3, seed=1)

    csv_text = mockdata.render(rows, "csv", _SCHEMA)
    reader = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(reader) == 3
    assert reader[0]["id"] == "1"

    parsed = json.loads(mockdata.render(rows, "json", _SCHEMA))
    assert len(parsed) == 3

    lines = mockdata.render(rows, "jsonl", _SCHEMA).splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["id"] == 1


# --------------------------------------------------------------------------- tool handler


@pytest.fixture
def data_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    orig_ws, orig_md = artifact_store.WORKSPACE, artifact_store.METADATA_ROOT
    artifact_store.configure_roots(tmp_path, tmp_path)
    agent = DataEngineerAgent("data_engineer", MessageBus(), ArtifactStore(), Console())
    yield agent, tmp_path
    artifact_store.configure_roots(orig_ws, orig_md)


@pytest.mark.asyncio
async def test_generate_mock_data_handler_writes_fixture(data_agent):
    agent, root = data_agent
    result = await agent._generate_mock_data_handler({
        "path": "fixtures/sensors.csv",
        "format": "csv",
        "rows": 5,
        "columns": _SCHEMA,
    })

    assert "Generated 5 rows" in result
    written = root / "fixtures" / "sensors.csv"
    assert written.is_file()
    rows = list(csv.DictReader(io.StringIO(written.read_text())))
    assert len(rows) == 5
    assert str(written) in agent._edited_files


@pytest.mark.asyncio
async def test_generate_mock_data_handler_validates_input(data_agent):
    agent, _ = data_agent
    assert "error" in await agent._generate_mock_data_handler({"path": "", "columns": _SCHEMA})
    assert "error" in await agent._generate_mock_data_handler({"path": "f.csv", "columns": []})
    assert "error" in await agent._generate_mock_data_handler({"path": "f.csv", "columns": [{"type": "int"}]})
