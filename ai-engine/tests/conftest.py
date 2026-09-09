from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest

# 테스트는 배포 튜닝(.env)에 의존하면 안 된다.
#
# EMBEDDING_PROVIDER 를 gemini 로 두면 테스트가 실제 Gemini API 를 호출한다 —
# 느리고, 네트워크가 없으면 실패하고, 무료 등급 한도를 테스트가 소진한다.
# 관련도 임계값도 마찬가지다. 임베딩 모델을 바꿀 때마다 게이트 로직 테스트가
# 같이 깨지면 그건 테스트가 검증하는 대상이 아니다.
#
# 모듈 임포트 전에 설정해야 Settings 캐시에 반영된다.
import os

os.environ.setdefault("VECTOR_STORE_BACKEND", "memory")
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["EXTERNAL_EMBEDDING_PROVIDER"] = "hash"
os.environ["EMBEDDING_DIMENSION"] = "256"
os.environ["EXTERNAL_EMBEDDING_DIMENSION"] = "256"
os.environ["FACT_CHECK_STRONG_RELEVANCE_SCORE"] = "0.42"
os.environ["FACT_CHECK_MODERATE_RELEVANCE_SCORE"] = "0.34"

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
