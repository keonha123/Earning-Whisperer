"""
core/composite_scorer.py — EarningWhisperer AI Engine v3.1.0
4지표 복합 점수 계산 모듈

핵심 공식:
  composite = W_sentiment × raw_score
            + W_sue × clip(sue_score / 3.0, -1, +1)
            + W_momentum × momentum_score
            + W_volume × vol_score

수정 이력:
  v3.1.0  get_score_breakdown() 인터페이스 강화, 타입 힌트 완성
  v3.0.1  BUG-01 CRITICAL 수정:
    - 문제: VIX 보정이 composite_scorer와 five_gate_filter 양쪽에서 적용됨
            → 신호 강도가 정상의 21% 수준으로 억제
    - 수정: calculate_composite_score(vix=None) — VIX 파라미터 완전 제거
            VIX 보정은 five_gate_filter.py의 adj_composite에서만 1회 적용
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config import get_settings
from ..models.request_models import MarketData

logger = logging.getLogger(__name__)


@dataclass
class ScoreBreakdown:
    """4지표 기여도 분해 결과 (Explainability)."""

    sentiment_contrib: float  # W_sentiment × raw_score
    pead_contrib: float       # W_sue × clip(sue/3.0, -1, +1)
    momentum_contrib: float   # W_momentum × momentum_score
    volume_contrib: float     # W_volume × vol_score
    composite: float          # 합계

    def to_dict(self) -> dict:
        return {
            "sentiment_contrib": round(self.sentiment_contrib, 4),
            "pead_contrib":      round(self.pead_contrib, 4),
            "momentum_contrib":  round(self.momentum_contrib, 4),
            "volume_contrib":    round(self.volume_contrib, 4),
            "composite":         round(self.composite, 4),
        }


def calculate_composite_score(
    raw_score: float,
    sue_score: Optional[float],
    momentum_score: Optional[float],
    volume_ratio: Optional[float],
    # ⚠️  vix 파라미터 완전 제거 — BUG-01 수정
    # VIX 보정은 five_gate_filter.py에서만 1회 적용
) -> float:
    """4지표 가중 복합 점수를 계산합니다.

    BUG-01 CRITICAL 수정:
        구버전은 이 함수 내부와 five_gate_filter.py 양쪽에서 VIX 보정을 적용했습니다.
        결과적으로 VIX=20일 때 신호가 이중으로 감쇄되어 정상의 21% 수준으로 억제됐습니다.
        수정 후: VIX 보정은 five_gate_filter.py에서만 단 1회 적용합니다.

    Args:
        raw_score:       Gemini 감성 점수 (-1.0 ~ +1.0)
        sue_score:       PEAD SUE 점수 (-5.0 ~ +5.0), None이면 0으로 처리
        momentum_score:  기술적 모멘텀 (-1.0 ~ +1.0), None이면 0으로 처리
        volume_ratio:    거래량 배율 (현재/20일 평균), None이면 1.0으로 처리

    Returns:
        -1.0 ~ +1.0 사이의 composite_score
    """
    settings = get_settings()

    # ── 각 지표 정규화 ────────────────────────────────────────────────────
    # SUE 정규화: -5~+5 → -1~+1
    sue_normalized = float(np.clip(
        (sue_score or 0.0) / 3.0,
        -1.0, 1.0,
    ))

    # 모멘텀: None이면 중립
    mom = float(np.clip(momentum_score or 0.0, -1.0, 1.0))

    # 거래량 점수: 배율 → 방향 있는 점수로 변환
    # volume_ratio=1.0 → vol_score=0, 2.0 → +0.5, 3.0+ → +1.0
    vol = _volume_to_score(volume_ratio)

    # ── 가중 합산 (vix 보정 없음) ─────────────────────────────────────────
    composite = (
        settings.w_sentiment * raw_score
        + settings.w_sue      * sue_normalized
        + settings.w_momentum * mom
        + settings.w_volume   * vol
    )

    return float(np.clip(composite, -1.0, 1.0))


def get_score_breakdown(
    raw_score: float,
    sue_score: Optional[float],
    momentum_score: Optional[float],
    volume_ratio: Optional[float],
) -> ScoreBreakdown:
    """4지표 기여도를 분해하여 Explainability 객체를 반환합니다.

    사용 예:
        breakdown = get_score_breakdown(raw_score=0.87, sue_score=3.21, ...)
        print(breakdown.to_dict())
        # {
        #   "sentiment_contrib": 0.3480,
        #   "pead_contrib":      0.2675,
        #   "momentum_contrib":  0.1300,
        #   "volume_contrib":    0.0675,
        #   "composite":         0.8130
        # }
    """
    settings = get_settings()

    sue_normalized = float(np.clip((sue_score or 0.0) / 3.0, -1.0, 1.0))
    mom = float(np.clip(momentum_score or 0.0, -1.0, 1.0))
    vol = _volume_to_score(volume_ratio)

    sentiment_contrib = settings.w_sentiment * raw_score
    pead_contrib      = settings.w_sue       * sue_normalized
    momentum_contrib  = settings.w_momentum  * mom
    volume_contrib    = settings.w_volume    * vol

    composite = float(np.clip(
        sentiment_contrib + pead_contrib + momentum_contrib + volume_contrib,
        -1.0, 1.0,
    ))

    return ScoreBreakdown(
        sentiment_contrib=round(sentiment_contrib, 4),
        pead_contrib=round(pead_contrib, 4),
        momentum_contrib=round(momentum_contrib, 4),
        volume_contrib=round(volume_contrib, 4),
        composite=round(composite, 4),
    )


def _volume_to_score(volume_ratio: Optional[float]) -> float:
    """거래량 배율을 -1.0~+1.0 점수로 변환합니다.

    변환 규칙:
        volume_ratio ≥ 3.0 → +1.0 (폭발적 거래량)
        volume_ratio = 2.0 → +0.5
        volume_ratio = 1.0 → 0.0 (평균 거래량)
        volume_ratio < 1.0 → 음수 (거래량 부족)
    """
    if volume_ratio is None:
        return 0.0
    # (ratio - 1.0) / 2.0 으로 [0, 2.0] → [0.0, 1.0] 정규화 후 클립
    return float(np.clip((volume_ratio - 1.0) / 2.0, -1.0, 1.0))
