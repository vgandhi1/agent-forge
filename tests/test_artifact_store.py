import pytest

from core import artifact_store


@pytest.mark.asyncio
async def test_write_rejects_traversal(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(artifact_store, "WORKSPACE", tmp_path)
    with pytest.raises(ValueError, match="traversal|escapes|safe|Invalid"):
        await artifact_store.ArtifactStore.write("../../../etc/passwd", "x")


@pytest.mark.asyncio
async def test_write_and_read_roundtrip(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(artifact_store, "WORKSPACE", tmp_path)
    await artifact_store.ArtifactStore.write("docs/a.md", "# hello")
    text = await artifact_store.ArtifactStore.read("docs/a.md")
    assert text == "# hello"
