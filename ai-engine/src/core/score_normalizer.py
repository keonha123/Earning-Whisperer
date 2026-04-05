"""
core/score_normalizer.py — EarningWhisperer AI Engine v3.1.0
raw_score 정규화 모듈

핵심 알고리즘:
  1. base_score = sign(direction) × magnitude × confidence
  2. Tetlock 패널티: 극단적 확신(magnitude > 0.9)에 패널티
  3. 완곡어법 패널티: euphemism_count당 -0.05
  4. NumPy 벡터화: 멀티 티커 배치 처리 지원

수정 이력:
  v3.1.0  배치 처리 인터페이스 추가, 단일 처리 로직 분리
  v3.0.1  BUG-06 수정: euphemism.penalty=None → float(None) TypeError 크래시
           → None 안전 처리 + try/except 추가
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import numpy as np

from ..models.signal_models import GeminiAnalysisResult

logger = logging.getLogger(__name__)

_DIRECTION_SIGN = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}

# Tetlock 패널티: 극단적 확신 표현에 정확도 패널티
_TETLOCK_THRESHOLD = 0.90   # magnitude ≥ 이 값이면 패널티 적용
_TETLOCK_PENALTY   = -0.05  # 패널티 크기

# 완곡어법 패널티: 1개당 신뢰도 감소
_EUPHEMISM_PENALTY_PER_COUNT = -0.05
_MAX_EUPHEMISM_PENALTY       = -0.30  # 최대 페널티 캡


def compute_raw_score(result: GeminiAnalysisResult) -> float:
    """GeminiAnalysisResult → raw_score(-1.0 ~ +1.0) 변환.

    BUG-06 수정:
        - 구버전: euphemism_penalty = float(result.euphemism.penalty) → None이면 TypeError
        - 수정: 모든 Optional 필드를 None-safe 처리, try/except 래핑

    Args:
        result: Gemini 분석 결과 객체

    Returns:
        -1.0 ~ +1.0 사이의 raw_score
    """
    try:
        sign = _DIRECTION_SIGN.get(result.direction, 0.0)
        magnitude = _safe_float(result.magnitude, default=0.5)
        confidence = _safe_float(result.confidence, default=0.5)
        euphemism_count = max(0, int(result.euphemism_count or 0))

        # 1. 기본 점수
        base_score = sign * magnitude * confidence

        # 2. Tetlock 패널티 (극단적 확신에 패널티)
        tetlock_penalty = _TETLOCK_PENALTY if magnitude >= _TETLOCK_THRESHOLD else 0.0

        # 3. 완곡어법 패널티
        euphemism_penalty = max(
            _EUPHEMISM_PENALTY_PER_COUNT * euphemism_count,
            _MAX_EUPHEMISM_PENALTY,
        )

        # Tetlock penalty should reduce score magnitude symmetrically and stay neutral-safe.
        tetlock_adjustment = tetlock_penalty * sign
        raw = base_score + tetlock_adjustment + euphemism_penalty * abs(sign)
        return float(np.clip(raw, -1.0, 1.0))

    except (TypeError, ValueError, AttributeError) as exc:
        logger.error("raw_score 계산 오류 (result=%s): %s", result, exc)
        return 0.0


def compute_raw_score_batch(results: Sequence[GeminiAnalysisResult]) -> np.ndarray:
    """여러 GeminiAnalysisResult를 NumPy 벡터화로 일괄 처리합니다.

    멀티 티커 동시 분석 시 루프보다 효율적입니다.

    Args:
        results: GeminiAnalysisResult 목록

    Returns:
        shape (N,)의 float64 numpy 배열 (각 원소 -1.0 ~ +1.0)
    """
    if not results:
        return np.array([], dtype=np.float64)

    signs       = np.array([_DIRECTION_SIGN.get(r.direction, 0.0) for r in results])
    magnitudes  = np.clip([_safe_float(r.magnitude, 0.5) for r in results], 0.0, 1.0)
    confidences = np.clip([_safe_float(r.confidence, 0.5) for r in results], 0.0, 1.0)
    euph_counts = np.array([max(0, int(r.euphemism_count or 0)) for r in results])

    base_scores = signs * magnitudes * confidences

    tetlock_penalties = np.where(magnitudes >= _TETLOCK_THRESHOLD, _TETLOCK_PENALTY, 0.0)

    euphemism_penalties = np.clip(
        _EUPHEMISM_PENALTY_PER_COUNT * euph_counts,
        _MAX_EUPHEMISM_PENALTY,
        0.0,
    )

    tetlock_adjustments = tetlock_penalties * signs
    raw_scores = base_scores + tetlock_adjustments + euphemism_penalties * np.abs(signs)
    return np.clip(raw_scores, -1.0, 1.0)


def _safe_float(value: Optional[float], default: float = 0.0) -> float:
    """None-safe float 변환 헬퍼."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
