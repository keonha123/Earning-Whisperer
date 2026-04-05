"""
strategies/orchestrator.py — EarningWhisperer AI Engine v3.1.0
7대 트레이딩 전략 자동 선택 오케스트레이터

전략 우선순위 (숫자가 낮을수록 우선):
  1. SHORT_SQUEEZE    — 공매도 스퀴즈
  2. GAP_AND_GO       — 갭업 모멘텀 매수
  3. GAP_FILL         — 과잉 갭다운 역매수
  4. NEWS_BREAKOUT    — 어닝 비트 돌파
  5. SECTOR_CONTAGION — 섹터 파급 효과
  6. IV_CRUSH         — 내재변동성 붕괴
  7. WHISPER_PLAY     — 어닝 위스퍼 플레이
  8. CONTRARIAN       — 과잉반응 역추세

최대 2개 전략 동시 실행 (포트폴리오 집중 방지)
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from models.request_models import MarketData
from models.signal_models import GeminiAnalysisResult, StrategyName, WhisperSignal

logger = logging.getLogger(__name__)

# 전략별 최대 보유 기간 (일)
STRATEGY_HOLD_DAYS = {
    StrategyName.SHORT_SQUEEZE:    2,
    StrategyName.GAP_AND_GO:       1,
    StrategyName.GAP_FILL:         1,
    StrategyName.NEWS_BREAKOUT:    3,
    StrategyName.SECTOR_CONTAGION: 2,
    StrategyName.IV_CRUSH:         1,
    StrategyName.WHISPER_PLAY:     1,
    StrategyName.CONTRARIAN:       2,
    StrategyName.SENTIMENT_ONLY:   1,
    StrategyName.ERROR_FALLBACK:   1,
}


class StrategyOrchestrator:
    """시장 데이터와 Gemini 분석 결과를 기반으로 최적 트레이딩 전략을 선택합니다."""

    def select_strategy(
        self,
        market_data: Optional[MarketData],
        gemini_result: GeminiAnalysisResult,
        raw_score: float,
    ) -> Tuple[StrategyName, int, Optional[WhisperSignal], bool]:
        """주요 전략, 보유 기간, 위스퍼 시그널, 섹터 파급 여부를 반환합니다.

        Returns:
            (primary_strategy, hold_days_max, whisper_signal, sector_contagion)
        """
        if market_data is None:
            return StrategyName.SENTIMENT_ONLY, 1, None, False

        candidates: List[Tuple[int, StrategyName]] = []

        # 우선순위 1: SHORT_SQUEEZE
        if self._check_short_squeeze(market_data):
            candidates.append((1, StrategyName.SHORT_SQUEEZE))

        # 우선순위 2: GAP_AND_GO
        if self._check_gap_and_go(market_data, raw_score):
            candidates.append((2, StrategyName.GAP_AND_GO))

        # 우선순위 3: GAP_FILL
        if self._check_gap_fill(market_data):
            candidates.append((3, StrategyName.GAP_FILL))

        # 우선순위 4: NEWS_BREAKOUT
        if self._check_news_breakout(market_data, gemini_result):
            candidates.append((4, StrategyName.NEWS_BREAKOUT))

        # 우선순위 5: SECTOR_CONTAGION
        sector_contagion = self._check_sector_contagion(market_data, gemini_result)
        if sector_contagion:
            candidates.append((5, StrategyName.SECTOR_CONTAGION))

        # 우선순위 6: IV_CRUSH
        if self._check_iv_crush(market_data):
            candidates.append((6, StrategyName.IV_CRUSH))

        # 우선순위 7: WHISPER_PLAY
        whisper_signal = self._classify_whisper(market_data)
        if whisper_signal != WhisperSignal.UNKNOWN:
            candidates.append((7, StrategyName.WHISPER_PLAY))

        # 우선순위 8: CONTRARIAN
        if self._check_contrarian(market_data, raw_score):
            candidates.append((8, StrategyName.CONTRARIAN))

        if not candidates:
            return StrategyName.SENTIMENT_ONLY, 1, whisper_signal, sector_contagion

        # 우선순위 정렬 후 최상위 1개 선택
        candidates.sort(key=lambda x: x[0])
        _, primary = candidates[0]
        hold_days = STRATEGY_HOLD_DAYS.get(primary, 1)

        logger.info(
            "전략 선택: %s (보유 %d일), 후보=%s",
            primary.value,
            hold_days,
            [s.value for _, s in candidates],
        )
        return primary, hold_days, whisper_signal, sector_contagion

    # ── 개별 전략 조건 ────────────────────────────────────────────────────────

    @staticmethod
    def _check_short_squeeze(md: MarketData) -> bool:
        return (
            md.short_interest_pct is not None
            and md.days_to_cover is not None
            and md.volume_ratio is not None
            and md.short_interest_pct > 10.0
            and md.days_to_cover > 3.0
            and md.volume_ratio > 2.0
        )

    @staticmethod
    def _check_gap_and_go(md: MarketData, raw_score: float) -> bool:
        return (
            md.gap_pct is not None
            and md.premarket_volume_ratio is not None
            and md.gap_pct > 3.0
            and raw_score > 0.5
            and md.premarket_volume_ratio > 2.0
        )

    @staticmethod
    def _check_gap_fill(md: MarketData) -> bool:
        """갭다운 과잉 반응 역매수."""
        if md.gap_pct is None:
            return False
        return md.gap_pct < -3.0

    @staticmethod
    def _check_news_breakout(md: MarketData, result: GeminiAnalysisResult) -> bool:
        return (
            md.current_price is not None
            and md.ma20 is not None
            and md.volume_ratio is not None
            and md.current_price > md.ma20
            and md.volume_ratio > 1.5
            and result.catalyst_type in ("EARNINGS_BEAT", "GUIDANCE_UP")
        )

    @staticmethod
    def _check_sector_contagion(md: MarketData, result: GeminiAnalysisResult) -> bool:
        """섹터 파급 효과 감지 (REGULATORY_RISK 또는 MACRO_COMMENTARY + 높은 거래량)."""
        if md.volume_ratio is None:
            return False
        is_macro_catalyst = result.catalyst_type in ("REGULATORY_RISK", "MACRO_COMMENTARY")
        return is_macro_catalyst and md.volume_ratio > 2.0

    @staticmethod
    def _check_iv_crush(md: MarketData) -> bool:
        return (
            md.iv_rank is not None
            and md.hours_to_earnings is not None
            and md.iv_rank > 70.0
            and md.hours_to_earnings < 2.0
        )

    @staticmethod
    def _classify_whisper(md: MarketData) -> WhisperSignal:
        """어닝 위스퍼 대비 결과를 분류합니다."""
        if md.whisper_eps is None or md.avg_analyst_est is None:
            return WhisperSignal.UNKNOWN

        diff_pct = (md.whisper_eps - md.avg_analyst_est) / max(abs(md.avg_analyst_est), 0.01) * 100

        if diff_pct > 2.0:
            return WhisperSignal.ABOVE_WHISPER
        elif diff_pct < -2.0:
            return WhisperSignal.BELOW_WHISPER
        else:
            return WhisperSignal.AT_WHISPER

    @staticmethod
    def _check_contrarian(md: MarketData, raw_score: float) -> bool:
        """과잉반응 역추세 감지."""
        if md.gap_pct is None or md.rsi_14 is None:
            return False
        # 급락 후 RSI 과매도 + 감성은 강세 → 역추세 매수
        oversold_bounce = md.gap_pct < -5.0 and md.rsi_14 < 30 and raw_score > 0.3
        return oversold_bounce
