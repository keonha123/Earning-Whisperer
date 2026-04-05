"""
tests/test_core.py — EarningWhisperer AI Engine v3.1.0
핵심 모듈 단위 테스트 (40개)

실행: pytest tests/test_core.py -v
"""

from __future__ import annotations

import pytest

from core.composite_scorer import (
    calculate_composite_score,
    get_score_breakdown,
)
from core.five_gate_filter import FiveGateFilter
from core.integrity_validator import validate_integrity, _detect_direction
from core.pead_calculator import calculate_sue_score, classify_pead_signal
from core.regime_classifier import (
    apply_regime_multiplier,
    classify_regime,
)
from core.risk_manager import (
    calculate_position_size,
    calculate_stop_take_profit,
    determine_signal_strength,
)
from core.score_normalizer import compute_raw_score, compute_raw_score_batch
from models.request_models import AnalyzeRequest, MarketData
from models.signal_models import (
    GeminiAnalysisResult,
    MarketRegime,
    SignalStrength,
)


# ── 테스트용 픽스처 ───────────────────────────────────────────────────────────

@pytest.fixture
def bullish_result() -> GeminiAnalysisResult:
    return GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.87,
        confidence=0.91,
        rationale="테스트용 강세 분석 결과",
        catalyst_type="EARNINGS_BEAT",
        euphemism_count=0,
        negative_word_ratio=0.05,
    )


@pytest.fixture
def bearish_result() -> GeminiAnalysisResult:
    return GeminiAnalysisResult(
        direction="BEARISH",
        magnitude=0.70,
        confidence=0.85,
        rationale="테스트용 약세 분석 결과",
        catalyst_type="EARNINGS_MISS",
        euphemism_count=1,
        negative_word_ratio=0.35,
    )


@pytest.fixture
def full_market_data() -> MarketData:
    return MarketData(
        current_price=901.20,
        prev_close=879.50,
        price_change_pct=2.47,
        rsi_14=62.3,
        macd_signal=0.025,
        bb_position=0.71,
        atr_14=18.5,
        volume_ratio=2.8,
        ma20=855.0,
        high_52w=974.0,
        vix=16.4,
        earnings_surprise_pct=15.2,
        avg_analyst_est=5.12,
        whisper_eps=5.25,
        gap_pct=3.1,
        premarket_volume_ratio=4.2,
        put_call_ratio=0.65,
        iv_rank=72.0,
        short_interest_pct=2.8,
        days_to_cover=1.3,
    )


# ── ScoreNormalizer 테스트 ────────────────────────────────────────────────────

class TestScoreNormalizer:

    def test_bullish_positive_score(self, bullish_result):
        score = compute_raw_score(bullish_result)
        assert score > 0.0
        assert -1.0 <= score <= 1.0

    def test_bearish_negative_score(self, bearish_result):
        score = compute_raw_score(bearish_result)
        assert score < 0.0

    def test_neutral_near_zero(self):
        result = GeminiAnalysisResult(
            direction="NEUTRAL", magnitude=0.3, confidence=0.5,
            rationale="중립", catalyst_type="MACRO_COMMENTARY",
        )
        score = compute_raw_score(result)
        assert score == 0.0  # NEUTRAL → sign=0

    def test_none_euphemism_no_crash(self):
        """BUG-06 회귀 테스트: euphemism_count=None이어도 크래시 없음."""
        result = GeminiAnalysisResult(
            direction="BULLISH", magnitude=0.7, confidence=0.8,
            rationale="테스트", catalyst_type="EARNINGS_BEAT",
            euphemism_count=None,
        )
        score = compute_raw_score(result)
        assert -1.0 <= score <= 1.0

    def test_high_euphemism_reduces_score(self, bullish_result):
        no_euph = compute_raw_score(bullish_result)
        high_euph = GeminiAnalysisResult(
            direction="BULLISH", magnitude=0.87, confidence=0.91,
            rationale="테스트", catalyst_type="EARNINGS_BEAT",
            euphemism_count=5,
        )
        with_euph = compute_raw_score(high_euph)
        assert with_euph < no_euph  # 완곡어법 많으면 점수 낮아짐

    def test_batch_shape(self, bullish_result, bearish_result):
        import numpy as np
        results = [bullish_result, bearish_result]
        scores = compute_raw_score_batch(results)
        assert scores.shape == (2,)
        assert scores[0] > 0 and scores[1] < 0

    def test_clip_within_range(self):
        result = GeminiAnalysisResult(
            direction="BULLISH", magnitude=1.0, confidence=1.0,
            rationale="극단", catalyst_type="EARNINGS_BEAT",
            euphemism_count=0,
        )
        score = compute_raw_score(result)
        assert -1.0 <= score <= 1.0


# ── CompositeScorer 테스트 ────────────────────────────────────────────────────

class TestCompositeScorer:

    def test_no_vix_parameter(self):
        """BUG-01 회귀 테스트: vix 파라미터가 없어야 함."""
        import inspect
        sig = inspect.signature(calculate_composite_score)
        assert "vix" not in sig.parameters, "vix 파라미터가 제거되지 않음 (BUG-01)"

    def test_result_range(self):
        score = calculate_composite_score(
            raw_score=0.87, sue_score=3.21, momentum_score=0.65, volume_ratio=2.8
        )
        assert -1.0 <= score <= 1.0

    def test_positive_inputs_positive_output(self):
        score = calculate_composite_score(
            raw_score=0.8, sue_score=2.0, momentum_score=0.5, volume_ratio=2.0
        )
        assert score > 0.0

    def test_none_inputs_handled(self):
        score = calculate_composite_score(
            raw_score=0.5, sue_score=None, momentum_score=None, volume_ratio=None
        )
        assert -1.0 <= score <= 1.0

    def test_breakdown_sums_to_composite(self):
        bd = get_score_breakdown(
            raw_score=0.87, sue_score=3.21, momentum_score=0.65, volume_ratio=2.8
        )
        total = bd.sentiment_contrib + bd.pead_contrib + bd.momentum_contrib + bd.volume_contrib
        assert abs(total - bd.composite) < 0.01

    def test_breakdown_explainability(self):
        bd = get_score_breakdown(
            raw_score=0.8, sue_score=0.0, momentum_score=0.0, volume_ratio=1.0
        )
        # sentiment_contrib가 가장 커야 함 (가중치 0.40으로 제일 높음)
        assert bd.sentiment_contrib >= bd.pead_contrib
        assert bd.sentiment_contrib >= bd.momentum_contrib


# ── IntegrityValidator 테스트 ─────────────────────────────────────────────────

class TestIntegrityValidator:

    def test_bullish_text_bullish_direction_passes(self):
        text = "Revenue exceeded expectations, record growth in data center."
        result = GeminiAnalysisResult(
            direction="BULLISH", magnitude=0.8, confidence=0.9,
            rationale="강세", catalyst_type="EARNINGS_BEAT",
        )
        is_valid, _ = validate_integrity(text, result)
        assert is_valid

    def test_negation_no_growth_is_bearish(self):
        """BUG-05 회귀 테스트: 'no growth'는 BEARISH로 처리해야 함."""
        direction = _detect_direction("we saw no growth in revenues this quarter")
        assert direction != "BULLISH"

    def test_bearish_text_bullish_direction_fails(self):
        text = "We missed earnings badly, declining revenues, cutting guidance."
        result = GeminiAnalysisResult(
            direction="BULLISH", magnitude=0.9, confidence=0.9,
            rationale="강세 주장", catalyst_type="EARNINGS_BEAT",
        )
        is_valid, _ = validate_integrity(text, result)
        assert not is_valid

    def test_low_confidence_skips_check(self):
        text = "We missed earnings badly."
        result = GeminiAnalysisResult(
            direction="BULLISH", magnitude=0.9, confidence=0.20,  # 낮은 신뢰도
            rationale="테스트", catalyst_type="EARNINGS_BEAT",
        )
        is_valid, reason = validate_integrity(text, result)
        assert is_valid  # 낮은 신뢰도 → 검사 면제

    def test_negated_bearish_word_bullish(self):
        direction = _detect_direction("we did not miss our targets this quarter")
        # "not miss" → bullish 신호
        assert direction in ("BULLISH", "NEUTRAL", "UNKNOWN")


# ── RegimeClassifier 테스트 ───────────────────────────────────────────────────

class TestRegimeClassifier:

    def test_extreme_fear_high_vix(self):
        md = MarketData(vix=40.0)
        regime = classify_regime(md)
        assert regime == MarketRegime.EXTREME_FEAR

    def test_high_volatility_mid_vix(self):
        md = MarketData(vix=28.0)
        regime = classify_regime(md)
        assert regime == MarketRegime.HIGH_VOLATILITY

    def test_bull_trend_low_vix_high_bb(self):
        md = MarketData(vix=12.0, bb_position=0.80)
        regime = classify_regime(md)
        assert regime == MarketRegime.BULL_TREND

    def test_bear_trend_low_vix_low_bb(self):
        md = MarketData(vix=12.0, bb_position=0.20)
        regime = classify_regime(md)
        assert regime == MarketRegime.BEAR_TREND

    def test_normal_regime_no_data(self):
        regime = classify_regime(None)
        assert regime == MarketRegime.NORMAL

    def test_regime_multiplier_extreme_fear_zero(self):
        adj = apply_regime_multiplier(0.9, MarketRegime.EXTREME_FEAR)
        assert adj == 0.0  # 극단 공포 → 신호 0

    def test_regime_multiplier_bull_trend_amplifies(self):
        base = 0.7
        adj = apply_regime_multiplier(base, MarketRegime.BULL_TREND)
        assert adj > base  # 강세 → 증폭


# ── RiskManager 테스트 ────────────────────────────────────────────────────────

class TestRiskManager:

    def test_strong_signal_strength(self):
        s = determine_signal_strength(0.80)
        assert s == SignalStrength.STRONG

    def test_moderate_signal_strength(self):
        s = determine_signal_strength(0.55)
        assert s == SignalStrength.MODERATE

    def test_weak_signal_strength(self):
        s = determine_signal_strength(0.30)
        assert s == SignalStrength.WEAK

    def test_position_size_bounded(self, full_market_data):
        pos = calculate_position_size(0.8, 0.9, full_market_data)
        assert 0.0 <= pos <= 0.25

    def test_position_zero_on_neutral(self, full_market_data):
        pos = calculate_position_size(0.0, 0.5, full_market_data)
        assert pos == 0.0

    def test_high_vix_reduces_position(self):
        low_vix_md  = MarketData(vix=15.0)
        high_vix_md = MarketData(vix=30.0)
        pos_low  = calculate_position_size(0.8, 0.9, low_vix_md)
        pos_high = calculate_position_size(0.8, 0.9, high_vix_md)
        assert pos_high < pos_low

    def test_stop_take_profit_ratio_strong(self):
        sl, tp, sl_pct, tp_pct, pf = calculate_stop_take_profit(
            SignalStrength.STRONG, current_price=100.0, atr_14=2.0, is_long=True
        )
        assert sl == 97.0      # 100 - 1.5×2
        assert tp == 106.0     # 100 + 3.0×2
        assert abs(pf - 2.0) < 0.01

    def test_no_atr_returns_none(self):
        sl, tp, *_ = calculate_stop_take_profit(
            SignalStrength.STRONG, current_price=100.0, atr_14=None, is_long=True
        )
        assert sl is None and tp is None


# ── FiveGateFilter 테스트 ─────────────────────────────────────────────────────

class TestFiveGateFilter:

    def _make_filter(self) -> FiveGateFilter:
        return FiveGateFilter()

    def test_all_gates_pass(self, full_market_data, bullish_result):
        f = self._make_filter()
        result = f.apply(
            composite_score=0.75,
            raw_score=0.80,
            confidence=0.90,
            euphemism_count=0,
            sue_score=2.5,
            momentum_score=0.6,
            market_data=full_market_data,
            gemini_result=bullish_result,
            regime=MarketRegime.BULL_TREND,
            adj_composite=0.86,
        )
        assert result.trade_approved

    def test_extreme_fear_blocks_all(self, full_market_data, bullish_result):
        f = self._make_filter()
        high_vix_md = MarketData(vix=40.0, volume_ratio=3.0)
        result = f.apply(
            composite_score=0.9, raw_score=0.9, confidence=0.95,
            euphemism_count=0, sue_score=3.0, momentum_score=0.8,
            market_data=high_vix_md,
            gemini_result=bullish_result,
            regime=MarketRegime.EXTREME_FEAR,
            adj_composite=0.0,
        )
        assert not result.trade_approved
        from models.signal_models import GateLabel
        assert GateLabel.G5 in result.failed_gates

    def test_low_composite_fails_g1(self, full_market_data, bullish_result):
        f = self._make_filter()
        result = f.apply(
            composite_score=0.1,   # 임계값 0.55 미만
            raw_score=0.1, confidence=0.5,
            euphemism_count=0, sue_score=None, momentum_score=None,
            market_data=full_market_data,
            gemini_result=bullish_result,
            regime=MarketRegime.NORMAL,
            adj_composite=0.1,
        )
        assert not result.trade_approved
        from models.signal_models import GateLabel
        assert GateLabel.G1 in result.failed_gates

    def test_pass_rates_update(self, full_market_data, bullish_result):
        f = self._make_filter()
        # 2번 호출
        for _ in range(2):
            f.apply(
                composite_score=0.75, raw_score=0.80, confidence=0.90,
                euphemism_count=0, sue_score=2.0, momentum_score=0.6,
                market_data=full_market_data, gemini_result=bullish_result,
                regime=MarketRegime.NORMAL, adj_composite=0.75,
            )
        rates = f.get_pass_rates()
        assert rates["g1"] is not None
