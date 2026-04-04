"""
core/pead_calculator.py — EarningWhisperer AI Engine v3.1.0
PEAD(Post-Earnings Announcement Drift) SUE 점수 계산 모듈

이론적 배경:
  Post-Earnings Announcement Drift는 어닝 서프라이즈 방향으로
  주가가 수일~수주에 걸쳐 계속 드리프트하는 현상입니다.
  SUE(Standardized Unexpected Earnings) = (실제 EPS - 예상 EPS) / 표준편차
  SUE > 3: 강력 매수 드리프트, SUE < -3: 강력 매도 드리프트
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from ..models.request_models import MarketData

logger = logging.getLogger(__name__)

# 역사적 EPS 표준편차 추정값 (데이터가 없을 때 사용)
_DEFAULT_EPS_STD = 0.50


def calculate_sue_score(market_data: Optional[MarketData]) -> Optional[float]:
    """SUE 점수를 계산합니다.

    SUE = (실제 EPS - 예상 EPS) / 표준편차

    표준편차를 직접 알 수 없을 때는 EPS 서프라이즈 % 와 컨센서스 EPS로 추정합니다:
        실제 EPS = avg_analyst_est × (1 + earnings_surprise_pct / 100)
        표준편차 ≈ |avg_analyst_est| × 0.10  (경험적 추정)

    Args:
        market_data: 시장 데이터 객체 (None이면 None 반환)

    Returns:
        -5.0 ~ +5.0 사이의 SUE 점수 (None이면 데이터 부족)
    """
    if market_data is None:
        return None

    md = market_data
    surprise_pct = md.earnings_surprise_pct
    analyst_est  = md.avg_analyst_est

    if surprise_pct is None:
        logger.debug("earnings_surprise_pct 없음 → SUE 계산 불가")
        return None

    # 방법 1: analyst_est로 실제 EPS 복원 → 표준편차 추정
    if analyst_est is not None and abs(analyst_est) > 0.001:
        actual_eps  = analyst_est * (1.0 + surprise_pct / 100.0)
        unexpected  = actual_eps - analyst_est
        std_est     = max(abs(analyst_est) * 0.10, _DEFAULT_EPS_STD)
        sue = unexpected / std_est
    else:
        # 방법 2: surprise_pct만 있을 때 단순 스케일링
        # 10% 서프라이즈 ≈ SUE 1.0
        sue = surprise_pct / 10.0

    # -5.0 ~ +5.0 클리핑
    sue_clipped = float(np.clip(sue, -5.0, 5.0))
    logger.debug("SUE 점수: %.3f (surprise_pct=%.1f%%)", sue_clipped, surprise_pct)
    return sue_clipped


def classify_pead_signal(sue_score: float) -> str:
    """SUE 점수 기반 PEAD 시그널 분류."""
    if sue_score >= 3.0:
        return "STRONG_BEAT"
    elif sue_score >= 1.0:
        return "MODERATE_BEAT"
    elif sue_score >= -1.0:
        return "IN_LINE"
    elif sue_score >= -3.0:
        return "MODERATE_MISS"
    else:
        return "STRONG_MISS"
