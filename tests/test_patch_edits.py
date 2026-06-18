"""Tests for patch-based edits: the ``edit_file`` tool (anchored search/replace).

These exercise the surgical-edit path in isolation. The artifact store is re-rooted onto a
temp dir so real reads/writes happen without touching the package ``workspace/``; LLM calls are
faked so the suite stays fast and deterministic.
"""

from types import SimpleNamespace

import pytest
from rich.console import Console

from agents.base_agent import (
    BaseAgent,
    _EDIT_FILE_TOOL,
    _EDIT_SMALL_FILE_LINES,
    _whitespace_tolerant_replace,
)
from core import artifact_store
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus


# --------------------------------------------------------------------------- helpers


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str, tool_input: dict, _id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=_id)


def _response(blocks: list, stop_reason: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=blocks, usage=usage, stop_reason=stop_reason)


class _DummyAgent(BaseAgent):
    async def run(self) -> None:  # pragma: no cover - not used
        pass


@pytest.fixture
def agent(monkeypatch, tmp_path):
    """A backend agent re-rooted onto a temp code tree; roots restored after."""
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")  # no Anthropic client / API key
    orig_ws, orig_md = artifact_store.WORKSPACE, artifact_store.METADATA_ROOT
    artifact_store.configure_roots(tmp_path, tmp_path)

    a = _DummyAgent("backend", MessageBus(), ArtifactStore(), Console())

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(a.memory, "remember", _noop)
    yield a, tmp_path
    artifact_store.configure_roots(orig_ws, orig_md)


# --------------------------------------------------------------------------- tool shape


def test_edit_file_tool_shape():
    assert _EDIT_FILE_TOOL["name"] == "edit_file"
    required = _EDIT_FILE_TOOL["input_schema"]["required"]
    assert required == ["path", "old_string", "new_string"]


# --------------------------------------------------------------------------- success paths


@pytest.mark.asyncio
async def test_edit_file_replaces_unique_snippet(agent):
    a, root = agent
    (root / "calc.py").write_text("def add(a, b):\n    return a - b  # bug\n", encoding="utf-8")

    out = await a._edit_file_handler({
        "path": "calc.py",
        "old_string": "return a - b  # bug",
        "new_string": "return a + b",
    })

    assert "Edited calc.py" in out
    assert (root / "calc.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    # the edited path is tracked for the caller to report
    assert any(p.endswith("calc.py") for p in a._edited_files)


@pytest.mark.asyncio
async def test_edit_file_empty_new_string_deletes_snippet(agent):
    a, root = agent
    (root / "f.txt").write_text("keep\nDELETE_ME\nkeep2\n", encoding="utf-8")

    out = await a._edit_file_handler({"path": "f.txt", "old_string": "DELETE_ME\n", "new_string": ""})

    assert "Edited f.txt" in out
    assert (root / "f.txt").read_text(encoding="utf-8") == "keep\nkeep2\n"


@pytest.mark.asyncio
async def test_edit_file_replace_all(agent):
    a, root = agent
    (root / "f.py").write_text("x = 1\nx = 1\nx = 1\n", encoding="utf-8")

    out = await a._edit_file_handler({
        "path": "f.py", "old_string": "x = 1", "new_string": "x = 2", "replace_all": True,
    })

    assert "replaced 3 occurrence(s)" in out
    assert (root / "f.py").read_text(encoding="utf-8") == "x = 2\nx = 2\nx = 2\n"


# --------------------------------------------------------------------------- error paths (no raise)


@pytest.mark.asyncio
async def test_edit_file_snippet_not_found(agent):
    a, root = agent
    (root / "f.py").write_text("hello\n", encoding="utf-8")
    out = await a._edit_file_handler({"path": "f.py", "old_string": "nope", "new_string": "x"})
    assert "not found" in out
    assert (root / "f.py").read_text(encoding="utf-8") == "hello\n"  # unchanged


@pytest.mark.asyncio
async def test_edit_file_ambiguous_match_requires_unique(agent):
    a, root = agent
    (root / "f.py").write_text("v = 1\nv = 1\n", encoding="utf-8")
    out = await a._edit_file_handler({"path": "f.py", "old_string": "v = 1", "new_string": "v = 2"})
    assert "occurs 2 times" in out
    assert (root / "f.py").read_text(encoding="utf-8") == "v = 1\nv = 1\n"  # unchanged


@pytest.mark.asyncio
async def test_edit_file_missing_file(agent):
    a, _ = agent
    out = await a._edit_file_handler({"path": "ghost.py", "old_string": "a", "new_string": "b"})
    assert "cannot edit ghost.py" in out


@pytest.mark.asyncio
async def test_edit_file_empty_old_string_rejected(agent):
    a, _ = agent
    out = await a._edit_file_handler({"path": "f.py", "old_string": "", "new_string": "x"})
    assert "must be non-empty" in out


@pytest.mark.asyncio
async def test_edit_file_identical_strings_noop(agent):
    a, root = agent
    (root / "f.py").write_text("same\n", encoding="utf-8")
    out = await a._edit_file_handler({"path": "f.py", "old_string": "same", "new_string": "same"})
    assert "identical" in out


@pytest.mark.asyncio
async def test_edit_file_path_traversal_blocked(agent):
    a, root = agent
    # A file outside the code root that a traversal would target.
    outside = root.parent / "secret.txt"
    outside.write_text("top secret\n", encoding="utf-8")
    out = await a._edit_file_handler({
        "path": "../secret.txt", "old_string": "top secret", "new_string": "pwned",
    })
    # Rejected before any read/write; the outside file is untouched.
    assert out.startswith("[edit_file error:")
    assert outside.read_text(encoding="utf-8") == "top secret\n"


# --------------------------------------------------------------------------- loop wiring


# --------------------------------------------------------------------------- fallback ladder (critique #1)


def test_ws_tolerant_replace_unit():
    # indentation differs between anchor and file → still a unique, line-aligned match
    content = "def f():\n    return 1\n"
    status, out = _whitespace_tolerant_replace(content, "        return 1", "    return 2")
    assert status == "ok"
    assert out == "def f():\n    return 2\n"


def test_ws_tolerant_replace_ambiguous():
    status, out = _whitespace_tolerant_replace("x = 1\nx = 1\n", "   x = 1", "x = 2")
    assert status == "ambiguous" and out is None


def test_ws_tolerant_replace_none_and_blank_anchor():
    assert _whitespace_tolerant_replace("a\nb\n", "zzz", "q")[0] == "none"
    # all-blank anchor must not match everywhere
    assert _whitespace_tolerant_replace("a\nb\n", "   ", "q")[0] == "none"


@pytest.mark.asyncio
async def test_edit_file_recovers_from_indentation_drift(agent):
    a, root = agent
    (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    # anchor has the wrong indentation (8 spaces vs the file's 4) — exact match would miss
    out = await a._edit_file_handler({
        "path": "m.py", "old_string": "        return 1", "new_string": "    return 2",
    })
    assert "matched ignoring whitespace" in out
    assert (root / "m.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"


@pytest.mark.asyncio
async def test_edit_file_small_file_hint_suggests_rewrite(agent):
    a, root = agent
    (root / "small.py").write_text("a = 1\n", encoding="utf-8")
    out = await a._edit_file_handler({"path": "small.py", "old_string": "zzz", "new_string": "q"})
    assert "not found" in out and "rewrite it wholesale with write_file" in out


@pytest.mark.asyncio
async def test_edit_file_large_file_hint_suggests_reanchor(agent):
    a, root = agent
    big = "\n".join(f"line {i}" for i in range(_EDIT_SMALL_FILE_LINES + 50)) + "\n"
    (root / "big.py").write_text(big, encoding="utf-8")
    out = await a._edit_file_handler({"path": "big.py", "old_string": "zzz", "new_string": "q"})
    assert "not found" in out and "larger, exact snippet" in out


@pytest.mark.asyncio
async def test_edit_tools_injected_and_reset(agent, monkeypatch):
    """run_tool_loop(edit_tools=True) exposes edit_file and resets the edited-files list."""
    a, root = agent
    (root / "m.py").write_text("status = 'old'\n", encoding="utf-8")
    a._edited_files = ["stale-entry"]  # must be cleared at loop start

    calls = {"n": 0}

    async def fake_ollama_create(messages, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            names = {t["name"] for t in (tools or [])}
            assert "edit_file" in names
            return _response(
                [_tool_block("edit_file", {
                    "path": "m.py", "old_string": "status = 'old'", "new_string": "status = 'new'",
                })],
                stop_reason="tool_use",
            )
        return _response([_text_block("done")])

    monkeypatch.setattr(a, "_ollama_create", fake_ollama_create)

    result = await a.run_tool_loop(
        user_message="fix it", tool_handlers={}, tools=[], edit_tools=True, max_steps=4,
    )

    assert any(name == "edit_file" for name, _ in result["tool_calls"])
    assert (root / "m.py").read_text(encoding="utf-8") == "status = 'new'\n"
    assert "stale-entry" not in a._edited_files
    assert any(p.endswith("m.py") for p in a._edited_files)
