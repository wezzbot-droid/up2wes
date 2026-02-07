from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def local_tmp_path() -> Path:
    """
    Fixture de tmpdir repo-local (Windows-friendly) sem usar plugin tmpdir do pytest.
    """
    base = REPO_ROOT / "dataset" / "out" / "test_tmp"
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"case_{uuid.uuid4().hex}"
    p.mkdir(parents=True, exist_ok=True)
    try:
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)
