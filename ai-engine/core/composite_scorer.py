# core/composite_scorer.py
# 복합 점수 계산: 감성(40%) + PEAD(25%) + 모멘텀(20%) + 거래량(15%)
# VIX 시장 국면 보정계수 적용
from typing import Optional
from config import settings


def calculate_momentum_score(
    macd_signal: Optional[float],
    rsi_14: Optional[float],
    bb_position: Optional[float],
) -> float:
    """
    기술적 지표 복합 모멘텀 점수 (-1.0 ~ +1.0).

    가중치:
      MACD 히스토그램 방향: 50%
      RSI 반전 신호:        30% (과매도=+, 과매수=-)
      볼린저밴드 위치:       20% (하단=+, 상단=-)
    """
    score = 0.0

    # MACD 히스토그램: 양수=상승 모멘텀, 음수=하락 모멘텀
    if macd_signal is not None:
        score += (1.0 if macd_signal > 0 else -1.0) * 0.5

    # RSI: 과매도(낮음)=반등 기대=양수, 과매수(높음)=하락 기대=음수
    if rsi_14 is not None:
        # rsi_14=30 → (50-30)/50 = +0.4 (과매도 → 반등)
        # rsi_14=70 → (50-70)/50 = -0.4 (과매수 → 하락)
        rsi_score = (50.0 - rsi_14) / 50.0
        score += rsi_score * 0.3

    # 볼린저밴드: 하단(0)=반등 기대=양수, 상단(1)=하락 기대=음수
    if bb_position is not None:
        bb_score = (0.5 - bb_position) * 2.0  # 0→+1, 0.5→0, 1→-1
        score += bb_score * 0.2

    return round(max(-1.0, min(1.0, score)), 4)


def calculate_composite_score(
    raw_score: float,
    sue_score: Optional[float],
    momentum_score: float,
    volume_ratio: float = 1.0,
    vix: Optional[float] = None,
) -> float:
    """
    복합 점수 = 가중 합산 × VIX 보정계수.

    가중치 (합계 1.0):
      감성(raw_score):  40%  Gemini 핵심 신호
      PEAD(sue_score):  25%  어닝 드리프트 방향
      모멘텀:           20%  기술적 지표 방향
      거래량:           15%  이상 거래량 확인

    VIX 보정:
      VIX < 25:  ×1.00 (정상)
      VIX 25-30: ×0.70 (주의)
      VIX 30-35: ×0.50 (고위험)
      VIX >= 35: ×0.30 (극한 공포)
    """
    w_sentiment = settings.w_sentiment   # 0.40
    w_sue       = settings.w_sue         # 0.25
    w_momentum  = settings.w_momentum    # 0.20
    w_volume    = settings.w_volume      # 0.15

    # 거래량 점수: 평균 초과분을 raw_score 방향으로 변환
    # volume_ratio=2.0 → vol_excess=0.5 → vol_score=±0.5 (방향에 따라)
    vol_excess = min(1.0, max(0.0, (volume_ratio - 1.0) / 2.0))
    vol_score  = vol_excess * (1.0 if raw_score >= 0 else -1.0)

    # SUE 정규화: -5~+5 → -1~+1
    sue_normalized = max(-1.0, min(1.0, (sue_score or 0.0) / 3.0))

    # 가중 합산
    composite_raw = (
        w_sentiment * raw_score +
        w_sue       * sue_normalized +
        w_momentum  * momentum_score +
        w_volume    * vol_score
    )

    # VIX 보정계수 (고변동성 구간 신호 약화)
    if vix is not None:
        if vix >= 35:    vix_mult = 0.30
        elif vix >= 30:  vix_mult = 0.50
        elif vix >= 25:  vix_mult = 0.70
        else:            vix_mult = 1.00
        composite_raw *= vix_mult

    return round(max(-1.0, min(1.0, composite_raw)), 4)
