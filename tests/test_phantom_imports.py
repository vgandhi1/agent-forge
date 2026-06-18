"""Tests for phantom-import / hallucinated-dependency detection.

Two layers: the pure detectors in ``core/artifact_quality`` (no I/O), and the QA agent's
``_scan_phantom_imports`` wiring (re-rooted onto a temp tree, real `find_spec` resolution).
"""

import pytest
from rich.console import Console

from agents.qa_engineer import QAEngineerAgent
from core import artifact_quality
from core import artifact_store
from core.artifact_store import ArtifactStore
from core.message_bus import MessageBus
from core.profile import Profile


# --------------------------------------------------------------------------- pure detectors


def test_imported_modules_extracts_top_level():
    src = (
        "import os\n"
        "import os.path\n"
        "import numpy as np\n"
        "from collections import OrderedDict\n"
        "from . import sibling\n"          # relative — skipped
        "from .pkg import thing\n"          # relative — skipped
        "from a.b.c import d\n"
    )
    assert artifact_quality.imported_modules(src) == {"os", "numpy", "collections", "a"}


def test_imported_modules_bad_syntax_is_empty():
    assert artifact_quality.imported_modules("def (oops:\n") == set()


def test_phantom_imports_excludes_stdlib_and_known():
    src = "import os\nimport fastapi\nimport ghost_pkg\n"
    # fastapi is "known" (declared dep); os is stdlib; ghost_pkg is neither
    assert artifact_quality.phantom_imports(src, known={"fastapi"}) == {"ghost_pkg"}


def test_phantom_imports_empty_when_all_known():
    src = "import os\nfrom typing import List\nimport mypkg\n"
    assert artifact_quality.phantom_imports(src, known={"mypkg"}) == set()


# --------------------------------------------------------------------------- QA agent wiring


@pytest.fixture
def qa(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTFORGE_LLM_PROVIDER", "ollama")
    orig_ws, orig_md = artifact_store.WORKSPACE, artifact_store.METADATA_ROOT
    artifact_store.configure_roots(tmp_path, tmp_path)
    agent = QAEngineerAgent("qa", MessageBus(), ArtifactStore(), Console())
    yield agent, tmp_path
    artifact_store.configure_roots(orig_ws, orig_md)


@pytest.mark.asyncio
async def test_scan_flags_only_real_phantom(qa):
    agent, root = qa
    app = root / "dailyease"
    (app / "models").mkdir(parents=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "models" / "__init__.py").write_text("", encoding="utf-8")
    # os/json: stdlib · pytest: installed · dailyease: local · ghostpkg_zzz9: phantom
    (app / "main.py").write_text(
        "import os\n"
        "import json\n"
        "import pytest\n"
        "from dailyease import models\n"
        "import ghostpkg_zzz9\n",
        encoding="utf-8",
    )

    findings = await agent._scan_phantom_imports(Profile(app_root="dailyease"))

    assert findings == {"dailyease/main.py": ["ghostpkg_zzz9"]}


@pytest.mark.asyncio
async def test_scan_clean_code_has_no_findings(qa):
    agent, root = qa
    app = root / "dailyease"
    app.mkdir(parents=True)
    (app / "main.py").write_text("import os\nimport sys\nimport pytest\n", encoding="utf-8")

    findings = await agent._scan_phantom_imports(Profile(app_root="dailyease"))

    assert findings == {}
