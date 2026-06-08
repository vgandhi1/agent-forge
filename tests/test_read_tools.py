import pytest

from core import artifact_store

Store = artifact_store.ArtifactStore


@pytest.fixture
def ws(monkeypatch, tmp_path):
    monkeypatch.setattr(artifact_store, "WORKSPACE", tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 11)) + "\nTODO fix bug\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "util.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_read_paginated_window_and_footer(ws):
    out = await Store.read_paginated("src/app.py", offset=0, limit=3)
    assert "1\tline 1" in out
    assert "3\tline 3" in out
    assert "line 4" not in out
    assert "more lines (use offset=3)" in out


@pytest.mark.asyncio
async def test_read_paginated_offset(ws):
    out = await Store.read_paginated("src/app.py", offset=10, limit=5)
    assert "11\tTODO fix bug" in out
    assert "more lines" not in out  # last window


@pytest.mark.asyncio
async def test_read_paginated_missing(ws):
    out = await Store.read_paginated("src/nope.py")
    assert out.startswith("[File not found:")


def test_glob_files_lists_and_scopes(ws):
    out = Store.glob_files("*.py", "src")
    assert "src/app.py" in out
    assert "src/util.py" in out


def test_glob_files_cap(ws):
    for i in range(5):
        (ws / "src" / f"f{i}.py").write_text("x", encoding="utf-8")
    out = Store.glob_files("*.py", "src", cap=2)
    assert "more (narrow the pattern)" in out


def test_glob_files_no_match(ws):
    assert Store.glob_files("*.rs", "src") == "[no matches]"


def test_grep_finds_match(ws):
    out = Store.grep("TODO", "src")
    assert "src/app.py:11: TODO fix bug" in out


def test_grep_no_match(ws):
    assert Store.grep("zzz-not-here", "src") == "[no matches]"


def test_grep_invalid_regex(ws):
    out = Store.grep("(unclosed", "src")
    assert out.startswith("[Invalid regex:")


def test_grep_glob_filter(ws):
    out = Store.grep("helper", "src", glob="util.py")
    assert "src/util.py:1: def helper():" in out


def test_read_tools_reject_traversal(ws):
    with pytest.raises(ValueError):
        Store.glob_files("*", "../../etc")
