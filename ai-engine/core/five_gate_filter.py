"""Five-gate trade filter with thread-safe pass-rate accounting."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from config import get_settings
from models.request_models import MarketData
from models.signal_models import GateLabel, GeminiAnalysisResult, MarketRegime

logger = logging.getLogger(__name__)

CATALYST_VOLUME_THRESHOLDS: Dict[str, float] = {
    "EARNINGS_BEAT": 1.80,
    "EARNINGS_MISS": 1.80,
    "GUIDANCE_UP": 1.50,
    "GUIDANCE_DOWN": 1.50,
    "GUIDANCE_HOLD": 1.20,
    "RESTRUCTURING": 2.00,
    "PRODUCT_NEWS": 1.30,
    "MACRO_COMMENTARY": 1.00,
    "REGULATORY_RISK": 2.00,
    "OPERATIONAL_EXEC": 1.40,
}


@dataclass
class GateResult:
    """Single gate evaluation result."""

    label: GateLabel
    passed: bool
    reason: str


@dataclass
class FilterResult:
    """Combined five-gate decision."""

    trade_approved: bool
    failed_gates: List[GateLabel]
    gate_results: List[GateResult]
    adj_composite: float


class FiveGateFilter:
    """Apply five gate checks and keep thread-safe pass-rate stats."""

    def __init__(self) -> None:
        self._pass_counts: Dict[str, int] = {f"g{i}": 0 for i in range(1, 6)}
        self._total_counts: Dict[str, int] = {f"g{i}": 0 for i in range(1, 6)}
        self._stats_lock = threading.Lock()

    def apply(
        self,
        composite_score: float,
        raw_score: float,
        confidence: float,
        euphemism_count: int,
        sue_score: Optional[float],
        momentum_score: Optional[float],
        market_data: Optional[MarketData],
        gemini_result: GeminiAnalysisResult,
        regime: MarketRegime,
        adj_composite: float,
    ) -> FilterResult:
        settings = get_settings()
        gate_results: List[GateResult] = []
        failed: List[GateLabel] = []

        g1 = self._gate1(
            composite_score,
            confidence,
            raw_score,
            euphemism_count,
            settings.composite_threshold,
            settings.confidence_threshold,
            settings.raw_score_threshold,
            settings.max_euphemism_count,
        )
        gate_results.append(g1)
        if not g1.passed:
            failed.append(GateLabel.G1)

        g2 = self._gate2(composite_score, sue_score)
        gate_results.append(g2)
        if not g2.passed:
            failed.append(GateLabel.G2)

        g3 = self._gate3(composite_score, market_data, momentum_score)
        gate_results.append(g3)
        if not g3.passed:
            failed.append(GateLabel.G3)

        g4 = self._gate4(market_data, gemini_result.catalyst_type)
        gate_results.append(g4)
        if not g4.passed:
            failed.append(GateLabel.G4)

        g5 = self._gate5(regime, market_data)
        gate_results.append(g5)
        if not g5.passed:
            failed.append(GateLabel.G5)

        self._update_stats_sync(gate_results)

        return FilterResult(
            trade_approved=len(failed) == 0,
            failed_gates=failed,
            gate_results=gate_results,
            adj_composite=adj_composite,
        )

    def get_pass_rates(self) -> Dict[str, Optional[float]]:
        result = {}
        with self._stats_lock:
            for label in ["g1", "g2", "g3", "g4", "g5"]:
                total = self._total_counts.get(label, 0)
                result[label] = round(self._pass_counts[label] / total, 4) if total else None
        return result

    @staticmethod
    def _gate1(
        composite: float,
        confidence: float,
        raw: float,
        euphemism: int,
        comp_thresh: float,
        conf_thresh: float,
        raw_thresh: float,
        max_euph: int,
    ) -> GateResult:
        conditions = [
            (abs(composite) >= comp_thresh, f"|composite|({abs(composite):.3f}) < {comp_thresh}"),
            (confidence >= conf_thresh, f"confidence({confidence:.3f}) < {conf_thresh}"),
            (abs(raw) >= raw_thresh, f"|raw_score|({abs(raw):.3f}) < {raw_thresh}"),
            (euphemism <= max_euph, f"euphemism({euphemism}) > {max_euph}"),
        ]
        failed_conditions = [message for ok, message in conditions if not ok]
        return GateResult(
            label=GateLabel.G1,
            passed=len(failed_conditions) == 0,
            reason="pass" if not failed_conditions else " | ".join(failed_conditions),
        )

    @staticmethod
    def _gate2(composite: float, sue_score: Optional[float]) -> GateResult:
        if sue_score is None or abs(sue_score) < 1.0:
            return GateResult(label=GateLabel.G2, passed=True, reason="sue_not_binding")

        composite_dir = np.sign(composite)
        sue_dir = np.sign(sue_score)
        if composite_dir == 0 or sue_dir == 0:
            return GateResult(label=GateLabel.G2, passed=True, reason="neutral_direction")

        passed = composite_dir == sue_dir
        return GateResult(
            label=GateLabel.G2,
            passed=passed,
            reason="direction_match"
            if passed
            else f"direction_mismatch(composite={composite:.2f},sue={sue_score:.2f})",
        )

    @staticmethod
    def _gate3(
        composite: float,
        market_data: Optional[MarketData],
        momentum_score: Optional[float],
    ) -> GateResult:
        if market_data is None:
            return GateResult(label=GateLabel.G3, passed=True, reason="market_data_missing")

        is_long = composite >= 0.0
        failures = []

        macd = market_data.macd_signal
        if macd is not None:
            if is_long and macd < 0:
                failures.append(f"macd({macd:.3f}) conflicts with long signal")
            elif not is_long and macd > 0:
                failures.append(f"macd({macd:.3f}) conflicts with short signal")

        rsi = market_data.rsi_14
        if rsi is not None:
            if is_long and rsi >= 75:
                failures.append(f"rsi({rsi:.1f}) overbought for long entry")
            elif not is_long and rsi <= 25:
                failures.append(f"rsi({rsi:.1f}) oversold for short entry")

        return GateResult(
            label=GateLabel.G3,
            passed=len(failures) < 2,
            reason="pass" if len(failures) < 2 else " | ".join(failures),
        )

    @staticmethod
    def _gate4(market_data: Optional[MarketData], catalyst_type: str) -> GateResult:
        if market_data is None:
            return GateResult(label=GateLabel.G4, passed=True, reason="market_data_missing")

        spread_bps = market_data.bid_ask_spread_bps
        if spread_bps is not None and spread_bps > 35:
            return GateResult(
                label=GateLabel.G4,
                passed=False,
                reason=f"bid_ask_spread({spread_bps:.1f}bps) > 35bps",
            )

        liquidity = market_data.liquidity_score
        if liquidity is not None and liquidity < 0.25:
            return GateResult(
                label=GateLabel.G4,
                passed=False,
                reason=f"liquidity_score({liquidity:.2f}) < 0.25",
            )

        volume_ratio = market_data.volume_ratio
        if volume_ratio is None:
            return GateResult(
                label=GateLabel.G4,
                passed=True,
                reason="volume_ratio_missing_execution_checks_passed",
            )

        threshold = CATALYST_VOLUME_THRESHOLDS.get(catalyst_type.upper(), 1.80)
        passed = volume_ratio >= threshold
        return GateResult(
            label=GateLabel.G4,
            passed=passed,
            reason=(
                f"volume_ratio({volume_ratio:.2f}x) >= {threshold}x"
                if passed
                else f"volume_ratio({volume_ratio:.2f}x) < {threshold}x"
            ),
        )

    @staticmethod
    def _gate5(regime: MarketRegime, market_data: Optional[MarketData]) -> GateResult:
        if regime == MarketRegime.EXTREME_FEAR:
            vix = market_data.vix if market_data else None
            return GateResult(
                label=GateLabel.G5,
                passed=False,
                reason=f"extreme_fear(vix={vix})",
            )

        settings = get_settings()
        if market_data and market_data.vix is not None and market_data.vix >= settings.max_vix:
            return GateResult(
                label=GateLabel.G5,
                passed=False,
                reason=f"vix({market_data.vix:.1f}) >= {settings.max_vix}",
            )

        return GateResult(label=GateLabel.G5, passed=True, reason="pass")

    def _update_stats_sync(self, gate_results: List[GateResult]) -> None:
        with self._stats_lock:
            for gate_result in gate_results:
                label = gate_result.label.value
                self._total_counts[label] = self._total_counts.get(label, 0) + 1
                if gate_result.passed:
                    self._pass_counts[label] = self._pass_counts.get(label, 0) + 1
