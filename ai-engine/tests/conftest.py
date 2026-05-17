from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import _pytest.pathlib as _pytest_pathlib

    _pytest_pathlib.cleanup_dead_symlinks = lambda root: None
except Exception:
    pass


@pytest.fixture
def tmp_path():
    base = ROOT / "tests" / "_tmp_runtime"
    base.mkdir(parents=True, exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
