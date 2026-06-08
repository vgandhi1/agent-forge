import pytest

from core import paths, artifact_store

Store = artifact_store.ArtifactStore


@pytest.fixture
def target(monkeypatch, tmp_path):
    """Re-root onto a fake target repo; restore code+metadata roots after."""
    repo = tmp_path / "my-api"
    repo.mkdir()
    orig_ws, orig_md = artifact_store.WORKSPACE, artifact_store.METADATA_ROOT
    code_root, meta_root = paths.resolve_roots(str(repo))
    artifact_store.configure_roots(code_root, meta_root)
    yield repo, code_root, meta_root
    artifact_store.configure_roots(orig_ws, orig_md)


def test_resolve_roots_default_is_single_tree():
    code, meta = paths.resolve_roots(None)
    assert code == meta  # default sandbox: code and metadata share the tree


def test_resolve_roots_target_isolates_metadata(tmp_path):
    code, meta = paths.resolve_roots(str(tmp_path))
    assert code == tmp_path.resolve()
    assert meta == (tmp_path / ".agentforge").resolve()


@pytest.mark.asyncio
async def test_code_writes_land_in_target(target):
    repo, code_root, _ = target
    await Store.write("src/app.py", "print('hi')")
    assert (repo / "src" / "app.py").read_text() == "print('hi')"


@pytest.mark.asyncio
async def test_metadata_isolated_from_source_tree(target):
    repo, code_root, meta_root = target
    await Store.write("handoff/backend.md", "done")
    await Store.write("reports/qa_report.md", "ok")
    # AgentForge bookkeeping goes under .agentforge, NOT into the user's source tree
    assert (meta_root / "handoff" / "backend.md").read_text() == "done"
    assert not (repo / "handoff").exists()
    assert not (repo / "reports").exists()


@pytest.mark.asyncio
async def test_read_back_routes_metadata_and_code(target):
    await Store.write("src/app.py", "code")
    await Store.write("handoff/backend.md", "meta")
    assert await Store.read("src/app.py") == "code"
    assert await Store.read("handoff/backend.md") == "meta"


@pytest.mark.asyncio
async def test_grep_scopes_to_target_code(target):
    await Store.write("src/app.py", "TODO target-bug")
    out = Store.grep("TODO")
    assert "src/app.py" in out
