"""Offline research and validation backtest service for v9 strategy tracks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

try:
    from config import Settings, get_settings
    from core.alpha_formula_engine import AlphaFormula
    from core.five_gate_filter import FiveGateFilter
    from core.market_feature_utils import (
        compute_atr_series,
        compute_bollinger,
        compute_breakout_pct_series,
        compute_relative_strength_vs_benchmark,
        compute_rsi_series,
        compute_rolling_beta,
        compute_stochastic,
        compute_volume_zscore_series,
        compute_weekly_ichimoku_series,
        compute_weekly_ichimoku_snapshot,
        percentage_points,
        rolling_annualized_volatility,
        safe_float,
    )
    from core.quant_risk_math import beta_posterior_mean, fractional_kelly_fraction, wilson_lower_bound
    from core.strategy_track_rules import (
        nasdaq100_aggressive_sector_blocked,
        nasdaq100_aggressive_strategy_allowed,
        nasdaq100_conservative_gap_extended,
        nasdaq100_conservative_high_vol_news_blocked,
        nasdaq100_conservative_quality_reversal_allowed,
        nasdaq100_conservative_sector_allowed,
        sp500_aggressive_sector_blocked,
        sp500_aggressive_strategy_allowed,
        sp500_conservative_gap_composite_floor,
        sp500_conservative_gap_sector_blocked,
    )
    from core.universe_profiles import (
        RiskStyleName,
        UniverseName,
        compose_universe_profile,
        get_allowed_strategies,
        resolve_universe_profile,
    )
    from models.request_models import MarketData, SectionType
    from models.signal_models import GeminiAnalysisResult, StrategyName
    from repositories.event_store_repository import EventStoreRepository
    from strategies.orchestrator import choose_strategy
except ImportError:  # pragma: no cover
    from ..config import Settings, get_settings
    from ..core.alpha_formula_engine import AlphaFormula
    from ..core.five_gate_filter import FiveGateFilter
    from ..core.market_feature_utils import (
        compute_atr_series,
        compute_bollinger,
        compute_breakout_pct_series,
        compute_relative_strength_vs_benchmark,
        compute_rsi_series,
        compute_rolling_beta,
        compute_stochastic,
        compute_volume_zscore_series,
        compute_weekly_ichimoku_series,
        compute_weekly_ichimoku_snapshot,
        percentage_points,
        rolling_annualized_volatility,
        safe_float,
    )
    from ..core.quant_risk_math import beta_posterior_mean, fractional_kelly_fraction, wilson_lower_bound
    from ..core.strategy_track_rules import (
        nasdaq100_aggressive_sector_blocked,
        nasdaq100_aggressive_strategy_allowed,
        nasdaq100_conservative_gap_extended,
        nasdaq100_conservative_high_vol_news_blocked,
        nasdaq100_conservative_quality_reversal_allowed,
        nasdaq100_conservative_sector_allowed,
        sp500_aggressive_sector_blocked,
        sp500_aggressive_strategy_allowed,
        sp500_conservative_gap_composite_floor,
        sp500_conservative_gap_sector_blocked,
    )
    from ..core.universe_profiles import (
        RiskStyleName,
        UniverseName,
        compose_universe_profile,
        get_allowed_strategies,
        resolve_universe_profile,
    )
    from ..models.request_models import MarketData, SectionType
    from ..models.signal_models import GeminiAnalysisResult, StrategyName
    from ..repositories.event_store_repository import EventStoreRepository
    from ..strategies.orchestrator import choose_strategy


SimulationMode = str
HistoryProvider = Callable[[str, str], pd.DataFrame | None]
BatchHistoryProvider = Callable[[list[str], str], dict[str, pd.DataFrame | None]]
MetadataProvider = Callable[[str], dict[str, Any]]


NASDAQ100_CONSERVATIVE_LOSS_STREAK_LIMIT = 2
NASDAQ100_CONSERVATIVE_LOSS_COOLDOWN_TRADES = 1
NASDAQ100_CONSERVATIVE_DRAWDOWN_COOLDOWN_TRIGGER_PCT = -8.0
NASDAQ100_CONSERVATIVE_DRAWDOWN_COOLDOWN_DAYS = 30


@dataclass(slots=True)
class BacktestTrade:
    ticker: str
    signal_at: str
    entry_at: str
    exit_at: str
    universe_profile: str
    risk_style: str
    strategy: str
    regime: str
    simulation_mode: str
    direction: str
    hold_days: int
    gross_return_pct: float
    net_return_pct: float
    mfe_pct: float
    mae_pct: float
    position_scale: float
    benchmark_return_pct: float
    entry_price: float
    exit_price: float
    blocked_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gross_return_pct"] = round(self.gross_return_pct, 4)
        payload["net_return_pct"] = round(self.net_return_pct, 4)
        payload["mfe_pct"] = round(self.mfe_pct, 4)
        payload["mae_pct"] = round(self.mae_pct, 4)
        payload["position_scale"] = round(self.position_scale, 4)
        payload["benchmark_return_pct"] = round(self.benchmark_return_pct, 4)
        payload["entry_price"] = round(self.entry_price, 4)
        payload["exit_price"] = round(self.exit_price, 4)
        return payload


@dataclass(slots=True)
class BacktestMetrics:
    trade_count: int
    win_rate_pct: float
    avg_trade_return_pct: float
    median_trade_return_pct: float
    expectancy_pct: float
    profit_factor: float
    total_return_pct: float
    annualized_return_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    time_under_water_days: float
    avg_hold_days: float
    avg_mfe_pct: float
    avg_mae_pct: float
    turnover: float
    exposure_pct: float
    benchmark_return_pct: float
    approved_signal_count: int
    rejected_signal_count: int
    wilson_win_rate_lower_pct: float = 0.0
    bayesian_win_rate_mean_pct: float = 0.0
    fractional_kelly_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {key: round(value, 4) if isinstance(value, float) else value for key, value in asdict(self).items()}


@dataclass(slots=True)
class TrackResult:
    simulation_mode: str
    universe_profile: str
    risk_style: str
    tickers: list[str]
    metrics: BacktestMetrics
    trades: list[BacktestTrade]
    breakdowns: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_mode": self.simulation_mode,
            "universe_profile": self.universe_profile,
            "risk_style": self.risk_style,
            "tickers": self.tickers,
            "metrics": self.metrics.to_dict(),
            "trade_count": self.metrics.trade_count,
            "trades": [trade.to_dict() for trade in self.trades],
            "breakdowns": self.breakdowns,
            "notes": self.notes,
        }


class ResearchBacktestService:
    """Runs proxy and replay backtests against the current v9 strategy stack."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repository: EventStoreRepository | None = None,
        history_provider: HistoryProvider | None = None,
        batch_history_provider: BatchHistoryProvider | None = None,
        metadata_provider: MetadataProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository
        self.history_provider = history_provider or self._download_history
        self.batch_history_provider = batch_history_provider or (self._download_history_batch if history_provider is None else None)
        self.metadata_provider = metadata_provider or self._load_ticker_metadata
        self._metadata_cache: dict[str, dict[str, Any]] = {}
        self._yfinance_cache_ready = False

    def load_tickers_from_file(self, path: str | Path) -> list[str]:
        content = Path(path).read_text(encoding="utf-8")
        return [line.strip().upper() for line in content.splitlines() if line.strip()]

    def run(
        self,
        *,
        tickers: list[str],
        period: str,
        start_date: str | None = None,
        end_date: str | None = None,
        min_history: int,
        universe_profile: str = "auto",
        risk_style: str = RiskStyleName.CONSERVATIVE.value,
        mode: SimulationMode = "proxy",
        output_json: str | Path | None = None,
        output_markdown: str | Path | None = None,
    ) -> dict[str, Any]:
        normalized_mode = str(mode or "proxy").strip().lower()
        normalized_risk = RiskStyleName(str(risk_style).strip().upper())
        normalized_tickers = sorted({ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()})
        generated_at = datetime.now(UTC).isoformat()

        results: dict[str, Any] = {"proxy": None, "replay": None}
        notes: list[str] = []

        if normalized_mode in {"proxy", "hybrid"}:
            results["proxy"] = self._run_proxy_track(
                tickers=normalized_tickers,
                period=period,
                start_date=start_date,
                end_date=end_date,
                min_history=min_history,
                universe_profile=universe_profile,
                risk_style=normalized_risk,
            ).to_dict()
        if normalized_mode in {"replay", "hybrid"}:
            replay_track = self._run_replay_track(
                tickers=normalized_tickers,
                period=period,
                start_date=start_date,
                end_date=end_date,
                universe_profile=universe_profile,
                risk_style=normalized_risk,
            )
            results["replay"] = replay_track.to_dict()
            if normalized_mode == "hybrid" and replay_track.metrics.trade_count == 0 and results["proxy"] is not None:
                notes.append("Hybrid mode fell back to proxy track because replay samples were unavailable.")

        effective = self._resolve_effective_result(results, normalized_mode)
        comparison = self._compare_available_tracks(results)
        report = {
            "generated_at": generated_at,
            "simulation_mode": normalized_mode,
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "data_window_label": self._data_window_label(period=period, start_date=start_date, end_date=end_date),
            "min_history": min_history,
            "tickers": normalized_tickers,
            "tickers_count": len(normalized_tickers),
            "requested_universe_profile": universe_profile,
            "risk_style": normalized_risk.value,
            "results": results,
            "effective_result": effective,
            "comparison": comparison,
            "notes": notes,
            "promotion_evaluation": self._evaluate_promotion(effective),
        }
        if output_json:
            path = Path(output_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        if output_markdown:
            path = Path(output_markdown)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.render_markdown_report(report), encoding="utf-8")
        return report

    def run_acceptance_matrix(
        self,
        *,
        nasdaq_tickers: list[str],
        sp500_tickers: list[str],
        period: str,
        start_date: str | None = None,
        end_date: str | None = None,
        min_history: int,
        mode: SimulationMode = "proxy",
        output_json: str | Path | None = None,
        output_markdown: str | Path | None = None,
    ) -> dict[str, Any]:
        scenarios = {
            "nasdaq100_conservative": self.run(
                tickers=nasdaq_tickers,
                period=period,
                start_date=start_date,
                end_date=end_date,
                min_history=min_history,
                universe_profile=UniverseName.NASDAQ100.value,
                risk_style=RiskStyleName.CONSERVATIVE.value,
                mode=mode,
            ),
            "nasdaq100_aggressive": self.run(
                tickers=nasdaq_tickers,
                period=period,
                start_date=start_date,
                end_date=end_date,
                min_history=min_history,
                universe_profile=UniverseName.NASDAQ100.value,
                risk_style=RiskStyleName.AGGRESSIVE.value,
                mode=mode,
            ),
            "sp500_conservative": self.run(
                tickers=sp500_tickers,
                period=period,
                start_date=start_date,
                end_date=end_date,
                min_history=min_history,
                universe_profile=UniverseName.SP500.value,
                risk_style=RiskStyleName.CONSERVATIVE.value,
                mode=mode,
            ),
            "sp500_aggressive": self.run(
                tickers=sp500_tickers,
                period=period,
                start_date=start_date,
                end_date=end_date,
                min_history=min_history,
                universe_profile=UniverseName.SP500.value,
                risk_style=RiskStyleName.AGGRESSIVE.value,
                mode=mode,
            ),
        }
        summaries = {name: self._extract_effective_metrics(payload) for name, payload in scenarios.items()}
        conservative_summaries = {
            name: summary
            for name, summary in summaries.items()
            if str(summary.get("risk_style") or "").upper() == RiskStyleName.CONSERVATIVE.value
        }
        prod_candidates = {
            name: summary
            for name, summary in conservative_summaries.items()
            if summary["promotion_evaluation"]["eligible_for_prod"]
        }
        selected_prod_candidate = self._select_best_candidate(prod_candidates or conservative_summaries)
        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "simulation_mode": str(mode).lower(),
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "data_window_label": self._data_window_label(period=period, start_date=start_date, end_date=end_date),
            "min_history": min_history,
            "scenarios": scenarios,
            "summaries": summaries,
            "pair_diffs": {
                "nasdaq100_aggressive_vs_conservative": self._diff_summaries(
                    baseline=summaries["nasdaq100_conservative"],
                    candidate=summaries["nasdaq100_aggressive"],
                ),
                "sp500_aggressive_vs_conservative": self._diff_summaries(
                    baseline=summaries["sp500_conservative"],
                    candidate=summaries["sp500_aggressive"],
                ),
            },
            "selected_prod_candidate": selected_prod_candidate,
            "research_only_tracks": [name for name, summary in summaries.items() if summary["risk_style"] == RiskStyleName.AGGRESSIVE.value],
            "calibration_proposal_candidates": [
                {
                    "scenario": name,
                    "universe_profile": summary.get("universe_profile"),
                    "next_action": "generate_patch_proposal_only",
                }
                for name, summary in conservative_summaries.items()
                if summary["promotion_evaluation"]["eligible_for_prod"]
            ],
        }
        if output_json:
            path = Path(output_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        if output_markdown:
            path = Path(output_markdown)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.render_acceptance_markdown(report), encoding="utf-8")
        return report

    def render_markdown_report(self, payload: Mapping[str, Any]) -> str:
        effective = payload.get("effective_result") or {}
        metrics = ((effective.get("metrics") or {}) if isinstance(effective, Mapping) else {}) or {}
        lines = [
            "# EarningWhisperer v9.4 Backtest Report",
            "",
            f"- Generated at: `{payload.get('generated_at')}`",
            f"- Simulation mode: `{payload.get('simulation_mode')}`",
            f"- Data window: `{payload.get('data_window_label') or payload.get('period')}`",
            f"- Universe profile: `{effective.get('universe_profile', 'UNKNOWN')}`",
            f"- Risk style: `{effective.get('risk_style', 'UNKNOWN')}`",
            f"- Tickers: `{payload.get('tickers_count', 0)}`",
            f"- Trade count: `{metrics.get('trade_count', 0)}`",
            f"- Win rate (%): `{metrics.get('win_rate_pct', 0)}`",
            f"- Wilson win lower (%): `{metrics.get('wilson_win_rate_lower_pct', 0)}`",
            f"- Bayesian win mean (%): `{metrics.get('bayesian_win_rate_mean_pct', 0)}`",
            f"- Fractional Kelly (%): `{metrics.get('fractional_kelly_pct', 0)}`",
            f"- Avg trade return (%): `{metrics.get('avg_trade_return_pct', 0)}`",
            f"- Profit factor: `{metrics.get('profit_factor', 0)}`",
            f"- Sharpe: `{metrics.get('sharpe_ratio', 0)}`",
            f"- Max drawdown (%): `{metrics.get('max_drawdown_pct', 0)}`",
            "",
            "## Promotion Evaluation",
            f"- Eligible for prod: `{payload.get('promotion_evaluation', {}).get('eligible_for_prod', False)}`",
            f"- Recommended state: `{payload.get('promotion_evaluation', {}).get('recommended_state', 'hold')}`",
            "",
            "## Notes",
        ]
        notes = list(payload.get("notes") or [])
        if isinstance(effective, Mapping):
            notes.extend(str(note) for note in effective.get("notes", []) or [])
        for note in notes or ["None"]:
            lines.append(f"- {note}")
        return "\n".join(lines)

    def render_acceptance_markdown(self, payload: Mapping[str, Any]) -> str:
        lines = [
            "# EarningWhisperer v9.4 Acceptance Matrix",
            "",
            f"- Generated at: `{payload.get('generated_at')}`",
            f"- Simulation mode: `{payload.get('simulation_mode')}`",
            f"- Data window: `{payload.get('data_window_label') or payload.get('period')}`",
            f"- Selected prod candidate: `{payload.get('selected_prod_candidate')}`",
            "",
            "| Scenario | Trades | Win Rate % | Wilson Lower % | Kelly % | Avg Return % | Total Return % | Benchmark % | Profit Factor | Sharpe | MDD % | State | Eligible |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for name, summary in (payload.get("summaries") or {}).items():
            metrics = summary.get("metrics", {})
            promotion = summary.get("promotion_evaluation", {})
            lines.append(
                f"| {name} | {metrics.get('trade_count', 0)} | {metrics.get('win_rate_pct', 0)} | "
                f"{metrics.get('wilson_win_rate_lower_pct', 0)} | {metrics.get('fractional_kelly_pct', 0)} | "
                f"{metrics.get('avg_trade_return_pct', 0)} | {metrics.get('total_return_pct', 0)} | "
                f"{metrics.get('benchmark_return_pct', 0)} | {metrics.get('profit_factor', 0)} | "
                f"{metrics.get('sharpe_ratio', 0)} | {metrics.get('max_drawdown_pct', 0)} | "
                f"{promotion.get('recommended_state', 'hold')} | "
                f"{promotion.get('eligible_for_prod', False)} |"
            )
        return "\n".join(lines)

    def _run_proxy_track(
        self,
        *,
        tickers: list[str],
        period: str,
        start_date: str | None,
        end_date: str | None,
        min_history: int,
        universe_profile: str,
        risk_style: RiskStyleName,
    ) -> TrackResult:
        vix_history = self._fetch_history("^VIX", period=period, start_date=start_date, end_date=end_date)
        histories = self._load_histories(tickers=tickers, period=period, start_date=start_date, end_date=end_date)
        benchmark_histories = self._load_histories(tickers=["SPY", "QQQ"], period=period, start_date=start_date, end_date=end_date)
        spy_history = benchmark_histories.get("SPY")
        qqq_history = benchmark_histories.get("QQQ")
        trades: list[BacktestTrade] = []
        benchmark_returns: list[float] = []
        notes: list[str] = []
        approved_count = 0
        rejected_count = 0

        for ticker in tickers:
            history = histories.get(ticker)
            if history is None or len(history) < min_history + 5:
                notes.append(f"{ticker}: insufficient history for proxy backtest")
                continue
            metadata = self._metadata_cache.get(ticker) or self.metadata_provider(ticker)
            self._metadata_cache[ticker] = metadata
            enriched = self._enrich_history(
                ticker=ticker,
                history=history,
                vix_history=vix_history,
                metadata=metadata,
                spy_history=spy_history,
                qqq_history=qqq_history,
            )
            if len(enriched) < min_history + 5:
                notes.append(f"{ticker}: enriched history too short for proxy backtest")
                continue
            benchmark_returns.append(self._benchmark_return_pct(enriched, min_history))
            next_available_idx = min_history
            for idx in range(min_history, len(enriched) - 1):
                if idx < next_available_idx:
                    continue
                row = enriched.iloc[idx]
                profile = self._resolve_profile(ticker=ticker, requested=universe_profile, risk_style=risk_style)
                market_data = self._to_market_data(ticker=ticker, row=row, metadata=metadata)
                raw_score = self._price_action_raw_score(row)
                if not self._is_event_bar(market_data=market_data, profile=profile, raw_score=raw_score):
                    continue
                analysis = self._proxy_analysis_result(raw_score=raw_score, row=row)
                decision = choose_strategy(
                    market_data,
                    gemini_result=analysis,
                    section_type=SectionType.OTHER,
                    universe_profile=profile.name.value,
                    risk_style=risk_style.value,
                )
                regime = self._classify_regime(market_data)
                approved, blocked_reasons, composite_strength = self._approve_trade(
                    profile_name=profile.name,
                    risk_style=risk_style,
                    strategy=decision.strategy,
                    strategy_score=decision.score,
                    market_data=market_data,
                    raw_score=raw_score,
                    confidence=analysis.confidence,
                    risk_flags=decision.risk_flags,
                    regime=regime,
                )
                if not approved:
                    rejected_count += 1
                    continue
                trade = self._simulate_proxy_trade(
                    ticker=ticker,
                    frame=enriched,
                    signal_index=idx,
                    strategy=decision.strategy,
                    hold_days=decision.hold_days,
                    direction=analysis.direction,
                    universe_profile=profile.name.value,
                    risk_style=risk_style.value,
                    regime=regime,
                    blocked_reasons=blocked_reasons,
                    composite_strength=composite_strength,
                )
                if trade is None:
                    rejected_count += 1
                    continue
                approved_count += 1
                trades.append(trade)
                exit_index = self._index_for_timestamp(enriched, trade.exit_at)
                next_available_idx = max(next_available_idx, exit_index + 1)

        profile_name = self._normalize_universe_name(universe_profile, tickers)
        trades, governor_rejected_count = self._apply_track_risk_governor(
            trades,
            profile_name=profile_name,
            risk_style=risk_style,
        )
        if governor_rejected_count:
            rejected_count += governor_rejected_count
            approved_count = len(trades)
            notes.append(
                "Nasdaq100 conservative risk governor skipped "
                f"{governor_rejected_count} trades after loss-streak/drawdown triggers"
            )

        metrics = self._compute_metrics(trades, approved_count=approved_count, rejected_count=rejected_count, benchmark_return_pct=self._mean(benchmark_returns))
        return TrackResult(
            simulation_mode="price_proxy",
            universe_profile=profile_name.value,
            risk_style=risk_style.value,
            tickers=tickers,
            metrics=metrics,
            trades=sorted(trades, key=lambda item: item.signal_at),
            breakdowns=self._build_breakdowns(trades),
            notes=notes,
        )

    def _apply_track_risk_governor(
        self,
        trades: list[BacktestTrade],
        *,
        profile_name: UniverseName,
        risk_style: RiskStyleName,
    ) -> tuple[list[BacktestTrade], int]:
        if profile_name != UniverseName.NASDAQ100 or risk_style != RiskStyleName.CONSERVATIVE:
            return trades, 0
        if not trades:
            return trades, 0

        kept: list[BacktestTrade] = []
        skipped_count = 0
        ordered = sorted(trades, key=lambda item: item.signal_at or item.entry_at)
        equity = 1.0
        peak_equity = 1.0
        consecutive_losses = 0
        cooldown_until_index = -1
        cooldown_until_date: pd.Timestamp | None = None

        for idx, trade in enumerate(ordered):
            signal_ts = pd.Timestamp(trade.signal_at or trade.entry_at)
            trade_cooldown_active = idx < cooldown_until_index
            date_cooldown_active = cooldown_until_date is not None and signal_ts < cooldown_until_date
            if trade_cooldown_active or date_cooldown_active:
                skipped_count += 1
                continue

            kept.append(trade)
            equity *= 1.0 + (float(trade.net_return_pct) / 100.0)
            peak_equity = max(peak_equity, equity)
            drawdown_pct = ((equity / peak_equity) - 1.0) * 100.0 if peak_equity > 0 else 0.0

            if float(trade.net_return_pct) <= 0.0:
                consecutive_losses += 1
            else:
                consecutive_losses = 0

            if consecutive_losses >= NASDAQ100_CONSERVATIVE_LOSS_STREAK_LIMIT:
                cooldown_until_index = idx + 1 + NASDAQ100_CONSERVATIVE_LOSS_COOLDOWN_TRADES
                consecutive_losses = 0

            if drawdown_pct <= NASDAQ100_CONSERVATIVE_DRAWDOWN_COOLDOWN_TRIGGER_PCT:
                cooldown_until_date = signal_ts + pd.Timedelta(days=NASDAQ100_CONSERVATIVE_DRAWDOWN_COOLDOWN_DAYS)
                peak_equity = equity
                consecutive_losses = 0

        return kept, skipped_count

    def _fetch_history(
        self,
        ticker: str,
        *,
        period: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame | None:
        if start_date or end_date:
            return self._download_history(ticker, period, start_date=start_date, end_date=end_date)
        return self.history_provider(ticker, period)

    def _load_histories(
        self,
        *,
        tickers: list[str],
        period: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, pd.DataFrame | None]:
        if (start_date or end_date) and self.batch_history_provider is None:
            return {
                ticker: self._download_history(ticker, period, start_date=start_date, end_date=end_date)
                for ticker in tickers
            }
        if start_date or end_date:
            return self._download_history_batch(tickers, period, start_date=start_date, end_date=end_date)
        if self.batch_history_provider is not None:
            return {ticker: payload for ticker, payload in self.batch_history_provider(tickers, period).items()}
        return {ticker: self.history_provider(ticker, period) for ticker in tickers}

    def _run_replay_track(
        self,
        *,
        tickers: list[str],
        period: str,
        start_date: str | None,
        end_date: str | None,
        universe_profile: str,
        risk_style: RiskStyleName,
    ) -> TrackResult:
        trades: list[BacktestTrade] = []
        notes: list[str] = []
        approved_count = 0
        rejected_count = 0
        profile_name = self._normalize_universe_name(universe_profile, tickers)
        if self.repository is None:
            notes.append("Replay mode skipped because no repository was configured.")
            return TrackResult(
                simulation_mode="event_replay",
                universe_profile=profile_name.value,
                risk_style=risk_style.value,
                tickers=tickers,
                metrics=self._compute_metrics([], approved_count=0, rejected_count=0, benchmark_return_pct=0.0),
                trades=[],
                breakdowns=self._build_breakdowns([]),
                notes=notes,
            )

        allowed = get_allowed_strategies(compose_universe_profile(profile_name.value, risk_style.value))
        replay_rows: list[dict[str, Any]] = []
        for strategy in allowed:
            replay_rows.extend(
                self.repository.get_closed_replay_samples(
                    strategy_code=strategy.value,
                    lookback_days=self._period_to_lookback_days(period, start_date=start_date, end_date=end_date),
                )
            )

        filtered_rows = [row for row in replay_rows if str(row.get("ticker") or "").upper() in tickers]
        if start_date or end_date:
            filtered_rows = [
                row
                for row in filtered_rows
                if self._row_in_date_range(row.get("event_time"), start_date=start_date, end_date=end_date)
            ]
        if not filtered_rows:
            notes.append("No replay samples matched the requested ticker universe.")
        for row in filtered_rows:
            direction = "BULLISH" if float(row.get("magnitude") or 0.0) >= 0 else "BEARISH"
            net_return_pct = float(row.get("realized_pnl_pct") or 0.0) - self._round_trip_cost_pct()
            trade = BacktestTrade(
                ticker=str(row.get("ticker") or "UNKNOWN").upper(),
                signal_at=str(row.get("event_time") or ""),
                entry_at=str(row.get("event_time") or ""),
                exit_at=str(row.get("event_time") or ""),
                universe_profile=profile_name.value,
                risk_style=risk_style.value,
                strategy=str(row.get("strategy_code") or StrategyName.SENTIMENT_ONLY.value),
                regime=str(row.get("regime") or "normal"),
                simulation_mode="event_replay",
                direction=direction,
                hold_days=int(row.get("hold_days") or 1),
                gross_return_pct=float(row.get("realized_pnl_pct") or 0.0),
                net_return_pct=net_return_pct,
                mfe_pct=float(row.get("mfe_pct") or 0.0),
                mae_pct=float(row.get("mae_pct") or 0.0),
                position_scale=1.0,
                benchmark_return_pct=0.0,
                entry_price=0.0,
                exit_price=0.0,
                blocked_reasons=[],
                metadata={
                    "run_id": row.get("run_id"),
                    "market_cap_bucket": row.get("market_cap_bucket"),
                    "sector_code": row.get("sector_code"),
                    "event_quality": row.get("event_quality"),
                },
            )
            trades.append(trade)
            if net_return_pct > 0:
                approved_count += 1
            else:
                rejected_count += 1

        metrics = self._compute_metrics(trades, approved_count=approved_count, rejected_count=rejected_count, benchmark_return_pct=0.0)
        return TrackResult(
            simulation_mode="event_replay",
            universe_profile=profile_name.value,
            risk_style=risk_style.value,
            tickers=tickers,
            metrics=metrics,
            trades=sorted(trades, key=lambda item: item.signal_at),
            breakdowns=self._build_breakdowns(trades),
            notes=notes,
        )

    def _resolve_effective_result(self, results: Mapping[str, Any], mode: str) -> dict[str, Any]:
        if mode == "proxy":
            return results.get("proxy") or {}
        if mode == "replay":
            return results.get("replay") or {}
        replay = results.get("replay") or {}
        if replay and int((replay.get("metrics") or {}).get("trade_count", 0)) > 0:
            return replay
        return results.get("proxy") or {}

    def _compare_available_tracks(self, results: Mapping[str, Any]) -> dict[str, Any]:
        proxy = results.get("proxy") or {}
        replay = results.get("replay") or {}
        proxy_metrics = proxy.get("metrics") or {}
        replay_metrics = replay.get("metrics") or {}
        if not proxy_metrics or not replay_metrics:
            return {}
        return {
            "trade_count_delta": int(replay_metrics.get("trade_count", 0)) - int(proxy_metrics.get("trade_count", 0)),
            "win_rate_pct_delta": round(float(replay_metrics.get("win_rate_pct", 0.0)) - float(proxy_metrics.get("win_rate_pct", 0.0)), 4),
            "avg_trade_return_pct_delta": round(float(replay_metrics.get("avg_trade_return_pct", 0.0)) - float(proxy_metrics.get("avg_trade_return_pct", 0.0)), 4),
            "sharpe_ratio_delta": round(float(replay_metrics.get("sharpe_ratio", 0.0)) - float(proxy_metrics.get("sharpe_ratio", 0.0)), 4),
            "max_drawdown_pct_delta": round(float(replay_metrics.get("max_drawdown_pct", 0.0)) - float(proxy_metrics.get("max_drawdown_pct", 0.0)), 4),
        }

    def _extract_effective_metrics(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        effective = payload.get("effective_result") or {}
        return {
            "simulation_mode": payload.get("simulation_mode"),
            "risk_style": effective.get("risk_style"),
            "universe_profile": effective.get("universe_profile"),
            "metrics": effective.get("metrics") or {},
            "promotion_evaluation": payload.get("promotion_evaluation") or {},
        }

    def _select_best_candidate(self, summaries: Mapping[str, Mapping[str, Any]]) -> str:
        if not summaries:
            return "none"
        best_name = ""
        best_score = -math.inf
        for name, summary in summaries.items():
            metrics = summary.get("metrics") or {}
            evaluation = summary.get("promotion_evaluation") or {}
            score = (
                float(metrics.get("expectancy_pct", 0.0)) * 100.0
                + float(metrics.get("sharpe_ratio", 0.0)) * 12.0
                + float(metrics.get("profit_factor", 0.0)) * 8.0
                + float(metrics.get("win_rate_pct", 0.0))
                + (20.0 if evaluation.get("eligible_for_prod") else 0.0)
                - abs(float(metrics.get("max_drawdown_pct", 0.0))) * 1.5
            )
            if score > best_score:
                best_score = score
                best_name = name
        return best_name

    @staticmethod
    def _diff_summaries(*, baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
        base_metrics = baseline.get("metrics") or {}
        candidate_metrics = candidate.get("metrics") or {}
        return {
            "trade_count_delta": int(candidate_metrics.get("trade_count", 0)) - int(base_metrics.get("trade_count", 0)),
            "win_rate_pct_delta": round(float(candidate_metrics.get("win_rate_pct", 0.0)) - float(base_metrics.get("win_rate_pct", 0.0)), 4),
            "avg_trade_return_pct_delta": round(float(candidate_metrics.get("avg_trade_return_pct", 0.0)) - float(base_metrics.get("avg_trade_return_pct", 0.0)), 4),
            "expectancy_pct_delta": round(float(candidate_metrics.get("expectancy_pct", 0.0)) - float(base_metrics.get("expectancy_pct", 0.0)), 4),
            "profit_factor_delta": round(float(candidate_metrics.get("profit_factor", 0.0)) - float(base_metrics.get("profit_factor", 0.0)), 4),
            "sharpe_ratio_delta": round(float(candidate_metrics.get("sharpe_ratio", 0.0)) - float(base_metrics.get("sharpe_ratio", 0.0)), 4),
            "max_drawdown_pct_delta": round(float(candidate_metrics.get("max_drawdown_pct", 0.0)) - float(base_metrics.get("max_drawdown_pct", 0.0)), 4),
        }

    def _resolve_profile(self, *, ticker: str, requested: str, risk_style: RiskStyleName):
        if str(requested).strip().lower() == "auto":
            base = resolve_universe_profile(ticker)
            return compose_universe_profile(base.name.value, risk_style.value)
        return compose_universe_profile(str(requested).strip().upper(), risk_style.value)

    @staticmethod
    def _normalize_universe_name(universe_profile: str, tickers: list[str]) -> UniverseName:
        text = str(universe_profile or "").strip().upper()
        if text == UniverseName.NASDAQ100.value:
            return UniverseName.NASDAQ100
        if text == UniverseName.SP500.value:
            return UniverseName.SP500
        if text == "AUTO":
            return UniverseName.DEFAULT
        if tickers and len(tickers) <= 110 and UniverseName.NASDAQ100.value in text:
            return UniverseName.NASDAQ100
        return UniverseName.DEFAULT

    def _approve_trade(
        self,
        *,
        profile_name: UniverseName,
        risk_style: RiskStyleName,
        strategy: StrategyName,
        strategy_score: float,
        market_data: MarketData,
        raw_score: float,
        confidence: float,
        risk_flags: list[str],
        regime: str,
    ) -> tuple[bool, list[str], float]:
        profile = compose_universe_profile(profile_name.value, risk_style.value)
        allowed = set(get_allowed_strategies(profile))
        blocked: list[str] = []

        if strategy not in allowed:
            blocked.append("strategy_not_enabled_for_track")
        if strategy == StrategyName.SENTIMENT_ONLY and not profile.strategy.allow_sentiment_only:
            blocked.append("sentiment_only_disabled")

        formula = profile.adjust_formula(
            AlphaFormula(
                w_sentiment=self.settings.w_sentiment,
                w_sue=self.settings.w_sue,
                w_momentum=self.settings.w_momentum,
                w_volume=self.settings.w_volume,
            )
        ).normalized()
        surprise_strength = self._clamp(abs(float(market_data.surprise_pct or 0.0)) / 15.0)
        momentum_strength = self._clamp(abs(self._percentage_points(market_data.relative_strength_20d)) / 15.0)
        volume_strength = self._clamp((float(market_data.volume_ratio or 1.0) - 1.0) / 2.0)
        composite_strength = (
            formula.w_sentiment * abs(raw_score)
            + formula.w_sue * surprise_strength
            + formula.w_momentum * momentum_strength
            + formula.w_volume * volume_strength
        )
        gate = FiveGateFilter(
            composite_threshold=self.settings.composite_threshold + profile.gate.composite_threshold_delta,
            confidence_threshold=self.settings.confidence_threshold + profile.gate.confidence_threshold_delta,
            raw_score_threshold=self.settings.raw_score_threshold + profile.gate.raw_score_threshold_delta,
        )
        gate_result = gate.evaluate(
            composite_score=composite_strength,
            confidence=confidence,
            raw_score=abs(raw_score),
        )
        if not gate_result.passed:
            blocked.extend(f"gate_{name}" for name in gate_result.failed_gates)

        if profile_name == UniverseName.SP500 and risk_style == RiskStyleName.CONSERVATIVE and strategy == StrategyName.GAP_AND_GO:
            if sp500_conservative_gap_sector_blocked(market_data.sector_code):
                blocked.append("sp500_gap_sector_blocked")
            required_composite = sp500_conservative_gap_composite_floor(market_data.sector_code)
            if composite_strength < required_composite:
                blocked.append("sp500_gap_composite_floor")

        if profile_name == UniverseName.NASDAQ100 and risk_style == RiskStyleName.CONSERVATIVE:
            continuation_strategies = {
                StrategyName.PEAD,
                StrategyName.NEWS_BREAKOUT,
                StrategyName.MOMENTUM_CARRY,
                StrategyName.GAP_AND_GO,
                StrategyName.WHISPER_PLAY,
                StrategyName.SHORT_SQUEEZE,
            }
            if strategy in continuation_strategies:
                if not nasdaq100_conservative_sector_allowed(market_data.sector_code):
                    blocked.append("nasdaq_conservative_non_core_sector")
                if nasdaq100_conservative_high_vol_news_blocked(strategy.value, regime):
                    blocked.append("nasdaq_conservative_high_vol_news_breakout")
                if "overextended_rsi" in risk_flags or "stacked_overbought" in risk_flags:
                    blocked.append("nasdaq_conservative_overextended")
                if (
                    (
                        strategy in {StrategyName.PEAD, StrategyName.MOMENTUM_CARRY, StrategyName.GAP_AND_GO, StrategyName.WHISPER_PLAY}
                        or (strategy == StrategyName.NEWS_BREAKOUT and float(market_data.gap_pct or 0.0) > 0.0)
                    )
                    and nasdaq100_conservative_gap_extended(market_data.gap_pct)
                ):
                    blocked.append("nasdaq_gap_extended")
            if strategy == StrategyName.REVERSAL_CATALYST:
                if not nasdaq100_conservative_quality_reversal_allowed(
                    sector_code=market_data.sector_code,
                    market_cap_bucket=market_data.market_cap_bucket,
                    regime=regime,
                ):
                    blocked.append("nasdaq_conservative_quality_reversal_scope")

        if profile_name == UniverseName.NASDAQ100 and risk_style == RiskStyleName.AGGRESSIVE:
            if not nasdaq100_aggressive_strategy_allowed(strategy.value):
                blocked.append("nasdaq_aggressive_strategy_blocked")
            elif nasdaq100_aggressive_sector_blocked(market_data.sector_code):
                blocked.append("nasdaq_aggressive_sector_blocked")

        if profile_name == UniverseName.SP500 and risk_style == RiskStyleName.AGGRESSIVE:
            if not sp500_aggressive_strategy_allowed(strategy.value):
                blocked.append("sp500_aggressive_strategy_blocked")
            elif sp500_aggressive_sector_blocked(market_data.sector_code):
                blocked.append("sp500_aggressive_sector_blocked")

        if risk_style == RiskStyleName.CONSERVATIVE:
            if self._estimated_execution_cost_pct(market_data) > float(self.settings.conservative_execution_cost_limit_pct):
                blocked.append("execution_cost_above_conservative_limit")
            if "thin_confirmation" in risk_flags:
                blocked.append("thin_confirmation")
            if "stale_catalyst" in risk_flags:
                blocked.append("stale_catalyst")
            if "continuation_gate_failed" in risk_flags:
                blocked.append("continuation_gate_failed")
            if "trend_up_confirmation_gap" in risk_flags:
                blocked.append("trend_up_confirmation_gap")
            for flag in ("below_ma200", "weekly_cloud_bearish", "benchmark_underperformance", "weak_fundamentals", "zero_dte_flow_opposition"):
                if flag in risk_flags:
                    blocked.append(flag)
        if risk_style == RiskStyleName.AGGRESSIVE:
            for flag in (
                "thin_confirmation",
                "gap_overshot_implied_move",
                "overshoot_without_transcript_confirmation",
                "zero_dte_flow_opposition",
            ):
                if flag in risk_flags:
                    blocked.append(flag)
        for flag in ("sp500_pead_quality_gate_failed", "trend_up_confirmation_gap"):
            if flag in risk_flags:
                blocked.append(flag)

        max_vix = profile.gate.max_vix
        if max_vix is not None and float(market_data.vix or 0.0) > float(max_vix):
            blocked.append("vix_above_track_limit")
        if regime in set(profile.gate.blocked_regimes):
            blocked.append("regime_blocked_for_track")
        if float(market_data.volume_ratio or 0.0) < self.settings.min_volume_ratio:
            blocked.append("volume_below_engine_floor")
        if float(market_data.liquidity_score or 0.0) < max(0.30, profile.strategy.news_liquidity_min - 0.05):
            blocked.append("liquidity_too_low")
        if strategy_score < 0.36:
            blocked.append("weak_strategy_score")

        return (len(blocked) == 0, sorted(set(blocked)), round(composite_strength, 4))

    def _simulate_proxy_trade(
        self,
        *,
        ticker: str,
        frame: pd.DataFrame,
        signal_index: int,
        strategy: StrategyName,
        hold_days: int,
        direction: str,
        universe_profile: str,
        risk_style: str,
        regime: str,
        blocked_reasons: list[str],
        composite_strength: float,
    ) -> BacktestTrade | None:
        if signal_index + 1 >= len(frame):
            return None
        entry_index = signal_index + 1
        entry_row = frame.iloc[entry_index]
        entry_price = float(entry_row["Open"])
        if entry_price <= 0:
            return None
        stop_pct, take_pct = self._exit_bands(strategy=strategy, frame=frame, entry_index=entry_index)
        last_index = min(len(frame) - 1, entry_index + max(1, hold_days) - 1)
        sign = -1.0 if direction == "BEARISH" else 1.0
        exit_index = last_index
        exit_price = float(frame.iloc[last_index]["Close"])
        exit_reason = "hold_days_close"
        mfe_pct = 0.0
        mae_pct = 0.0

        for idx in range(entry_index, last_index + 1):
            row = frame.iloc[idx]
            high = float(row["High"])
            low = float(row["Low"])
            favorable = (((high / entry_price) - 1.0) * 100.0) if sign > 0 else (((entry_price / max(low, 0.0001)) - 1.0) * 100.0)
            adverse = (((low / entry_price) - 1.0) * 100.0) if sign > 0 else (((entry_price / max(high, 0.0001)) - 1.0) * 100.0)
            mfe_pct = max(mfe_pct, favorable)
            mae_pct = min(mae_pct, adverse)

            if sign > 0:
                if low <= entry_price * (1.0 - stop_pct / 100.0):
                    exit_index = idx
                    exit_price = entry_price * (1.0 - stop_pct / 100.0)
                    exit_reason = "stop_loss"
                    break
                if high >= entry_price * (1.0 + take_pct / 100.0):
                    exit_index = idx
                    exit_price = entry_price * (1.0 + take_pct / 100.0)
                    exit_reason = "take_profit"
                    break
            else:
                if high >= entry_price * (1.0 + stop_pct / 100.0):
                    exit_index = idx
                    exit_price = entry_price * (1.0 + stop_pct / 100.0)
                    exit_reason = "stop_loss"
                    break
                if low <= entry_price * (1.0 - take_pct / 100.0):
                    exit_index = idx
                    exit_price = entry_price * (1.0 - take_pct / 100.0)
                    exit_reason = "take_profit"
                    break

        gross_return_pct = (((exit_price / entry_price) - 1.0) * 100.0) * sign
        net_return_pct = gross_return_pct - self._round_trip_cost_pct()
        signal_at = pd.Timestamp(frame.index[signal_index]).isoformat()
        entry_at = pd.Timestamp(frame.index[entry_index]).isoformat()
        exit_at = pd.Timestamp(frame.index[exit_index]).isoformat()
        benchmark_return_pct = float(frame.iloc[exit_index]["benchmark_window_return_pct"]) if "benchmark_window_return_pct" in frame.columns else 0.0

        return BacktestTrade(
            ticker=ticker,
            signal_at=signal_at,
            entry_at=entry_at,
            exit_at=exit_at,
            universe_profile=universe_profile,
            risk_style=risk_style,
            strategy=strategy.value,
            regime=regime,
            simulation_mode="price_proxy",
            direction=direction,
            hold_days=max(1, (exit_index - entry_index) + 1),
            gross_return_pct=gross_return_pct,
            net_return_pct=net_return_pct,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            position_scale=1.0 if risk_style == RiskStyleName.CONSERVATIVE.value else 1.15,
            benchmark_return_pct=benchmark_return_pct,
            entry_price=entry_price,
            exit_price=exit_price,
            blocked_reasons=blocked_reasons,
            metadata={
                "exit_reason": exit_reason,
                "composite_strength": composite_strength,
                "market_cap_bucket": frame.iloc[signal_index].get("market_cap_bucket", "unknown"),
                "sector_code": frame.iloc[signal_index].get("sector_code", "unknown"),
            },
        )

    def _build_breakdowns(self, trades: list[BacktestTrade]) -> dict[str, Any]:
        return {
            "by_universe": self._group_metrics(trades, key=lambda item: item.universe_profile),
            "by_risk_style": self._group_metrics(trades, key=lambda item: item.risk_style),
            "by_strategy": self._group_metrics(trades, key=lambda item: item.strategy),
            "by_regime": self._group_metrics(trades, key=lambda item: item.regime),
            "by_sector": self._group_metrics(trades, key=lambda item: str(item.metadata.get("sector_code") or "unknown")),
            "by_market_cap": self._group_metrics(trades, key=lambda item: str(item.metadata.get("market_cap_bucket") or "unknown")),
        }

    def _group_metrics(self, trades: list[BacktestTrade], *, key: Callable[[BacktestTrade], str]) -> dict[str, Any]:
        grouped: dict[str, list[BacktestTrade]] = {}
        for trade in trades:
            grouped.setdefault(key(trade), []).append(trade)
        return {
            name: self._compute_metrics(group, approved_count=len(group), rejected_count=0, benchmark_return_pct=self._mean([item.benchmark_return_pct for item in group])).to_dict()
            for name, group in sorted(grouped.items())
        }

    def _compute_metrics(
        self,
        trades: list[BacktestTrade],
        *,
        approved_count: int,
        rejected_count: int,
        benchmark_return_pct: float,
    ) -> BacktestMetrics:
        if not trades:
            return BacktestMetrics(
                trade_count=0,
                win_rate_pct=0.0,
                avg_trade_return_pct=0.0,
                median_trade_return_pct=0.0,
                expectancy_pct=0.0,
                profit_factor=0.0,
                total_return_pct=0.0,
                annualized_return_pct=0.0,
                annualized_volatility_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                max_drawdown_pct=0.0,
                time_under_water_days=0.0,
                avg_hold_days=0.0,
                avg_mfe_pct=0.0,
                avg_mae_pct=0.0,
                turnover=0.0,
                exposure_pct=0.0,
                benchmark_return_pct=benchmark_return_pct,
                approved_signal_count=approved_count,
                rejected_signal_count=rejected_count,
                wilson_win_rate_lower_pct=0.0,
                bayesian_win_rate_mean_pct=0.0,
                fractional_kelly_pct=0.0,
            )

        ordered = sorted(trades, key=lambda item: item.exit_at or item.signal_at)
        returns_pct = np.array([trade.net_return_pct for trade in ordered], dtype=float)
        returns = returns_pct / 100.0
        wins = returns_pct[returns_pct > 0]
        losses = returns_pct[returns_pct <= 0]
        trade_count = len(ordered)
        win_rate_pct = float((len(wins) / trade_count) * 100.0)
        avg_trade_return_pct = float(np.mean(returns_pct))
        median_trade_return_pct = float(median(returns_pct.tolist()))
        avg_win = float(np.mean(wins)) if len(wins) else 0.0
        avg_loss = float(np.mean(losses)) if len(losses) else 0.0
        expectancy_pct = float((len(wins) / trade_count) * avg_win + (len(losses) / trade_count) * avg_loss)
        bayesian_win_rate_mean = beta_posterior_mean(len(wins), len(losses))
        fractional_kelly = fractional_kelly_fraction(
            win_probability=bayesian_win_rate_mean,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            max_fraction=float(self.settings.kelly_max_position),
        )
        gross_profit = float(np.sum(wins)) if len(wins) else 0.0
        gross_loss = abs(float(np.sum(losses))) if len(losses) else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        equity_curve = self._equity_curve(ordered)
        total_return_pct = float((equity_curve[-1] - 1.0) * 100.0)
        max_drawdown_pct, time_under_water_days = self._calc_mdd(ordered, equity_curve)

        first_ts = pd.Timestamp(ordered[0].entry_at)
        last_ts = pd.Timestamp(ordered[-1].exit_at)
        period_days = max(1.0, float((last_ts - first_ts).days or 1))
        avg_hold_days = float(np.mean([trade.hold_days for trade in ordered]))
        annual_events = 252.0 / max(avg_hold_days, 1.0)
        annualized_return_pct = float((((equity_curve[-1]) ** (365.0 / period_days)) - 1.0) * 100.0) if equity_curve[-1] > 0 else -100.0
        annualized_volatility_pct = float(np.std(returns, ddof=0) * math.sqrt(max(annual_events, 1.0)) * 100.0)
        sharpe_ratio = self._safe_ratio(np.mean(returns), np.std(returns, ddof=0)) * math.sqrt(max(annual_events, 1.0))
        downside = returns[returns < 0]
        sortino_ratio = self._safe_ratio(np.mean(returns), np.std(downside, ddof=0) if len(downside) else 0.0) * math.sqrt(max(annual_events, 1.0))
        turnover = float(trade_count / max(period_days / 365.0, 1.0 / 365.0))
        exposure_pct = self._calc_exposure_pct(ordered, first_ts, last_ts)

        return BacktestMetrics(
            trade_count=trade_count,
            win_rate_pct=win_rate_pct,
            avg_trade_return_pct=avg_trade_return_pct,
            median_trade_return_pct=median_trade_return_pct,
            expectancy_pct=expectancy_pct,
            profit_factor=profit_factor,
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return_pct,
            annualized_volatility_pct=annualized_volatility_pct,
            sharpe_ratio=float(sharpe_ratio),
            sortino_ratio=float(sortino_ratio),
            max_drawdown_pct=float(max_drawdown_pct),
            time_under_water_days=float(time_under_water_days),
            avg_hold_days=avg_hold_days,
            avg_mfe_pct=float(np.mean([trade.mfe_pct for trade in ordered])),
            avg_mae_pct=float(np.mean([trade.mae_pct for trade in ordered])),
            turnover=turnover,
            exposure_pct=exposure_pct,
            benchmark_return_pct=benchmark_return_pct,
            approved_signal_count=approved_count,
            rejected_signal_count=rejected_count,
            wilson_win_rate_lower_pct=float(wilson_lower_bound(len(wins), trade_count) * 100.0),
            bayesian_win_rate_mean_pct=float(bayesian_win_rate_mean * 100.0),
            fractional_kelly_pct=float(fractional_kelly * 100.0),
        )

    @staticmethod
    def _equity_curve(trades: list[BacktestTrade]) -> np.ndarray:
        ordered = sorted(trades, key=lambda item: item.exit_at or item.signal_at)
        equity = [1.0]
        for trade in ordered:
            equity.append(equity[-1] * (1.0 + trade.net_return_pct / 100.0))
        return np.array(equity[1:], dtype=float)

    @staticmethod
    def _calc_mdd(trades: list[BacktestTrade], equity_curve: np.ndarray) -> tuple[float, float]:
        ordered = sorted(trades, key=lambda item: item.exit_at or item.signal_at)
        if not ordered or equity_curve.size == 0:
            return 0.0, 0.0
        running_peak = 1.0
        max_drawdown = 0.0
        peak_time: pd.Timestamp | None = pd.Timestamp(ordered[0].entry_at or ordered[0].signal_at)
        underwater_start: pd.Timestamp | None = None
        underwater_days = 0.0
        for idx, equity in enumerate(equity_curve):
            ts = pd.Timestamp(ordered[idx].exit_at or ordered[idx].signal_at)
            if equity >= running_peak:
                if underwater_start is not None and peak_time is not None:
                    underwater_days += max(0.0, float((ts - underwater_start).days))
                    underwater_start = None
                running_peak = float(equity)
                peak_time = ts
                continue
            if running_peak <= 0:
                continue
            drawdown = (equity / running_peak) - 1.0
            max_drawdown = min(max_drawdown, float(drawdown))
            if underwater_start is None:
                underwater_start = peak_time or ts
        if underwater_start is not None:
            underwater_days += max(0.0, float((pd.Timestamp(ordered[-1].exit_at or ordered[-1].signal_at) - underwater_start).days))
        return max_drawdown * 100.0, underwater_days

    @staticmethod
    def _calc_exposure_pct(trades: list[BacktestTrade], first_ts: pd.Timestamp, last_ts: pd.Timestamp) -> float:
        if not trades:
            return 0.0
        active_days: set[pd.Timestamp] = set()
        for trade in trades:
            start = pd.Timestamp(trade.entry_at).normalize()
            end = pd.Timestamp(trade.exit_at).normalize()
            for ts in pd.date_range(start, end, freq="D"):
                active_days.add(ts.normalize())
        total_days = max(1, len(pd.date_range(first_ts.normalize(), last_ts.normalize(), freq="D")))
        return float((len(active_days) / total_days) * 100.0)

    def _evaluate_promotion(self, effective: Mapping[str, Any]) -> dict[str, Any]:
        metrics = effective.get("metrics") or {}
        risk_style = str(effective.get("risk_style") or RiskStyleName.CONSERVATIVE.value).upper()
        conservative = {
            "trade_count": 40,
            "win_rate_pct": 53.0,
            "wilson_win_rate_lower_pct": 45.0,
            "expectancy_pct": 0.0,
            "profit_factor": 1.15,
            "sharpe_ratio": 1.0,
            "max_drawdown_pct": -12.0,
        }
        aggressive = {
            "trade_count": 50,
            "win_rate_pct": 50.0,
            "wilson_win_rate_lower_pct": 42.0,
            "expectancy_pct": 0.0,
            "profit_factor": 1.05,
            "sharpe_ratio": 0.75,
            "max_drawdown_pct": -18.0,
        }
        thresholds = aggressive if risk_style == RiskStyleName.AGGRESSIVE.value else conservative
        checks = {
            "trade_count": int(metrics.get("trade_count", 0)) >= thresholds["trade_count"],
            "win_rate_pct": float(metrics.get("win_rate_pct", 0.0)) >= thresholds["win_rate_pct"],
            "wilson_win_rate_lower_pct": float(metrics.get("wilson_win_rate_lower_pct", 0.0)) >= thresholds["wilson_win_rate_lower_pct"],
            "expectancy_pct": float(metrics.get("expectancy_pct", 0.0)) > thresholds["expectancy_pct"],
            "profit_factor": float(metrics.get("profit_factor", 0.0)) >= thresholds["profit_factor"],
            "sharpe_ratio": float(metrics.get("sharpe_ratio", 0.0)) >= thresholds["sharpe_ratio"],
            "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0)) >= thresholds["max_drawdown_pct"],
        }
        eligible = all(checks.values()) and risk_style != RiskStyleName.AGGRESSIVE.value
        return {
            "checks": checks,
            "thresholds": thresholds,
            "eligible_for_prod": eligible,
            "recommended_state": "prod_candidate" if eligible else ("research_canary_only" if risk_style == RiskStyleName.AGGRESSIVE.value else "hold_candidate"),
        }

    def _enrich_history(
        self,
        *,
        ticker: str,
        history: pd.DataFrame,
        vix_history: pd.DataFrame | None,
        metadata: Mapping[str, Any],
        spy_history: pd.DataFrame | None = None,
        qqq_history: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        frame = history.copy()
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame = frame.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()
        close = frame["Close"].astype(float)
        open_px = frame["Open"].astype(float)
        high = frame["High"].astype(float)
        low = frame["Low"].astype(float)
        volume = frame["Volume"].astype(float)
        prev_close = close.shift(1)
        returns = close.pct_change().fillna(0.0)
        gap_pct = ((open_px / prev_close) - 1.0).replace([np.inf, -np.inf], 0.0) * 100.0
        day_change_pct = ((close / prev_close) - 1.0).replace([np.inf, -np.inf], 0.0) * 100.0

        rsi = compute_rsi_series(close, period=14)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_signal = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
        ma20 = close.rolling(20, min_periods=20).mean()
        ma50 = close.rolling(50, min_periods=20).mean()
        ma200 = close.rolling(200, min_periods=60).mean()
        _, _, bb_position, bb_bandwidth = compute_bollinger(close, period=20, num_std=2.0)
        volume_ratio = (volume / volume.rolling(20, min_periods=10).mean().replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
        volume_z = compute_volume_zscore_series(volume, lookback=20)
        relative_strength_20d = ((close / close.shift(20)) - 1.0).replace([np.inf, -np.inf], 0.0)
        realized_vol_10d = rolling_annualized_volatility(returns, 10, min_periods=5)
        atr_14 = compute_atr_series(high, low, close, 14)
        atr_pct_14 = (atr_14 / close.replace(0.0, np.nan) * 100.0).replace([np.inf, -np.inf], 0.0)
        breakout_20d_pct = compute_breakout_pct_series(close, lookback=20).replace([np.inf, -np.inf], 0.0)
        high_52w = close.shift(1).rolling(252, min_periods=20).max()
        low_52w = close.shift(1).rolling(252, min_periods=20).min()
        drift_3d = ((close / close.shift(3)) - 1.0).replace([np.inf, -np.inf], 0.0) * 100.0
        realized_vol_rank = realized_vol_10d.rolling(126, min_periods=20).apply(lambda s: pd.Series(s).rank(pct=True).iloc[-1] if len(s) else 0.5)
        implied_move_pct = np.maximum(
            abs(atr_pct_14.fillna(0.0)) * 1.25,
            realized_vol_10d.fillna(0.0) * math.sqrt(5.0 / 252.0) * 100.0,
        )
        dollar_volume = (close * volume).rolling(20, min_periods=10).mean().clip(lower=1.0).fillna(1.0)
        liquidity_score = np.log10(dollar_volume).replace([np.inf, -np.inf], 0.0)
        liquidity_score = ((liquidity_score - 5.0) / 3.0).clip(0.0, 1.0)
        sector_momentum = relative_strength_20d.rolling(5, min_periods=3).mean().fillna(0.0) * 100.0
        benchmark_window_return_pct = ((close.shift(-5) / close) - 1.0).replace([np.inf, -np.inf], 0.0) * 100.0
        stochastic_k, stochastic_d = compute_stochastic(high, low, close, period=14, signal_period=3)

        spy_relative_strength_20d = pd.Series(index=frame.index, dtype=float)
        qqq_relative_strength_20d = pd.Series(index=frame.index, dtype=float)
        beta_spy_60d = pd.Series(index=frame.index, dtype=float)
        beta_qqq_60d = pd.Series(index=frame.index, dtype=float)
        if spy_history is not None and not spy_history.empty:
            spy_close = spy_history["Close"].astype(float)
            spy_relative_strength_20d = compute_relative_strength_vs_benchmark(close, spy_close, 20)
            beta_spy_60d = compute_rolling_beta(returns, spy_close.pct_change().fillna(0.0), 60)
        if qqq_history is not None and not qqq_history.empty:
            qqq_close = qqq_history["Close"].astype(float)
            qqq_relative_strength_20d = compute_relative_strength_vs_benchmark(close, qqq_close, 20)
            beta_qqq_60d = compute_rolling_beta(returns, qqq_close.pct_change().fillna(0.0), 60)

        ichimoku_weekly = compute_weekly_ichimoku_series(frame)
        if not ichimoku_weekly.empty:
            ichimoku_daily = ichimoku_weekly.reindex(frame.index, method="ffill")
        else:
            ichimoku_daily = pd.DataFrame(index=frame.index, columns=["tenkan", "kijun", "span_a", "span_b", "score", "bias"])

        if vix_history is not None and not vix_history.empty:
            vix_close = vix_history["Close"].astype(float)
            frame["vix"] = vix_close.reindex(frame.index).ffill().fillna(18.0)
        else:
            frame["vix"] = 18.0

        market_cap = float(metadata.get("market_cap") or metadata.get("marketCap") or 0.0)
        market_cap_bucket = self._market_cap_bucket(market_cap)
        sector_code = str(metadata.get("sector") or metadata.get("sector_code") or "unknown").upper().replace(" ", "_")
        revenue_growth_yoy = percentage_points(metadata.get("revenueGrowth"))
        earnings_growth_yoy = percentage_points(metadata.get("earningsGrowth"))
        gross_margin = percentage_points(metadata.get("grossMargins"))
        operating_margin = percentage_points(metadata.get("operatingMargins"))
        debt_to_equity = safe_float(metadata.get("debtToEquity"))
        current_ratio = safe_float(metadata.get("currentRatio"))
        total_revenue = safe_float(metadata.get("totalRevenue"))
        free_cash_flow = safe_float(metadata.get("freeCashflow"))
        fcf_margin = ((free_cash_flow / total_revenue) * 100.0) if free_cash_flow is not None and total_revenue else None

        frame["ticker"] = ticker
        frame["prev_close"] = prev_close
        frame["gap_pct"] = gap_pct
        frame["day_change_pct"] = day_change_pct
        frame["day1_return_pct"] = ((close / open_px) - 1.0).fillna(0.0) * 100.0
        frame["post_earnings_drift_pct"] = drift_3d
        frame["volume_ratio"] = volume_ratio
        frame["premarket_volume_ratio"] = volume_ratio
        frame["rsi_14"] = rsi
        frame["macd_signal"] = macd_signal
        frame["bb_position"] = bb_position
        frame["bb_bandwidth"] = bb_bandwidth
        frame["realized_vol_10d"] = realized_vol_10d
        frame["atr_14"] = atr_14
        frame["atr_pct_14"] = atr_pct_14
        frame["breakout_20d_pct"] = breakout_20d_pct
        frame["high_52w"] = high_52w
        frame["low_52w"] = low_52w
        frame["ma20"] = ma20
        frame["ma50"] = ma50
        frame["ma200"] = ma200
        frame["ma_stack_bullish"] = ((close > ma20) & (ma20 > ma50) & (ma50 > ma200)).fillna(False)
        frame["stochastic_k"] = stochastic_k
        frame["stochastic_d"] = stochastic_d
        frame["ichimoku_weekly_tenkan"] = pd.to_numeric(ichimoku_daily.get("tenkan"), errors="coerce")
        frame["ichimoku_weekly_kijun"] = pd.to_numeric(ichimoku_daily.get("kijun"), errors="coerce")
        frame["ichimoku_weekly_span_a"] = pd.to_numeric(ichimoku_daily.get("span_a"), errors="coerce")
        frame["ichimoku_weekly_span_b"] = pd.to_numeric(ichimoku_daily.get("span_b"), errors="coerce")
        frame["ichimoku_weekly_cloud_score"] = pd.to_numeric(ichimoku_daily.get("score"), errors="coerce")
        frame["ichimoku_weekly_cloud_bias"] = ichimoku_daily.get("bias")
        frame["volume_zscore_20d"] = volume_z
        frame["relative_strength_20d"] = relative_strength_20d
        frame["spy_relative_strength_20d"] = spy_relative_strength_20d
        frame["qqq_relative_strength_20d"] = qqq_relative_strength_20d
        frame["beta_spy_60d"] = beta_spy_60d
        frame["beta_qqq_60d"] = beta_qqq_60d
        frame["liquidity_score"] = liquidity_score
        frame["surprise_proxy_pct"] = ((gap_pct * 1.5) + day_change_pct * 0.4).clip(-25.0, 25.0)
        frame["analyst_revision_delta_pct"] = (relative_strength_20d * 100.0).clip(-12.0, 12.0)
        frame["iv_rank"] = (realized_vol_rank.fillna(0.5) * 100.0).clip(0.0, 100.0)
        frame["current_iv"] = (realized_vol_10d * 1.05).clip(lower=0.0)
        frame["implied_move_pct"] = implied_move_pct
        frame["nearest_option_expiry_days"] = None
        frame["zero_dte_available"] = False
        frame["zero_dte_put_call_volume_ratio"] = 1.0
        frame["zero_dte_atm_straddle_pct"] = implied_move_pct
        frame["zero_dte_gamma_pressure"] = np.clip((volume_ratio.fillna(1.0) - 1.0) / 3.0, -1.0, 1.0)
        frame["revenue_growth_yoy"] = revenue_growth_yoy
        frame["earnings_growth_yoy"] = earnings_growth_yoy
        frame["gross_margin"] = gross_margin
        frame["operating_margin"] = operating_margin
        frame["fcf_margin"] = fcf_margin
        frame["debt_to_equity"] = debt_to_equity
        frame["current_ratio"] = current_ratio
        frame["sector_momentum"] = sector_momentum
        frame["hours_since_news"] = np.where((abs(gap_pct) >= 1.5) | (volume_ratio.fillna(0.0) >= 1.8), 6.0, 48.0)
        frame["short_interest_pct_float"] = float(metadata.get("shortPercentOfFloat") or metadata.get("short_interest_pct_float") or 4.0)
        frame["float_rotation"] = (volume / max(float(metadata.get("floatShares") or 1_000_000_000.0), 1.0)).clip(lower=0.0)
        frame["market_cap"] = market_cap
        frame["market_cap_bucket"] = market_cap_bucket
        frame["sector_code"] = sector_code
        frame["has_options"] = bool(metadata.get("has_options", True))
        frame["benchmark_window_return_pct"] = benchmark_window_return_pct
        frame["bb_position"] = frame["bb_position"].fillna(0.5)
        frame["bb_bandwidth"] = frame["bb_bandwidth"].fillna(0.10)
        frame["stochastic_k"] = frame["stochastic_k"].fillna(50.0)
        frame["stochastic_d"] = frame["stochastic_d"].fillna(50.0)
        frame["ma20"] = frame["ma20"].fillna(close)
        frame["ma50"] = frame["ma50"].fillna(frame["ma20"])
        frame["ma200"] = frame["ma200"].fillna(frame["ma50"])
        frame["ma_stack_bullish"] = frame["ma_stack_bullish"].fillna(False)
        frame["spy_relative_strength_20d"] = frame["spy_relative_strength_20d"].fillna(0.0)
        frame["qqq_relative_strength_20d"] = frame["qqq_relative_strength_20d"].fillna(0.0)
        frame["beta_spy_60d"] = frame["beta_spy_60d"].fillna(1.0)
        frame["beta_qqq_60d"] = frame["beta_qqq_60d"].fillna(1.0)
        frame["ichimoku_weekly_cloud_bias"] = frame["ichimoku_weekly_cloud_bias"].fillna("neutral")
        for column, default in (
            ("ichimoku_weekly_cloud_score", 0.0),
            ("revenue_growth_yoy", 0.0),
            ("earnings_growth_yoy", 0.0),
            ("gross_margin", 0.0),
            ("operating_margin", 0.0),
            ("fcf_margin", 0.0),
            ("debt_to_equity", 0.0),
            ("current_ratio", 1.0),
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(default)
        return frame.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "prev_close",
                "gap_pct",
                "day_change_pct",
                "volume_ratio",
                "rsi_14",
                "macd_signal",
                "relative_strength_20d",
                "atr_14",
                "atr_pct_14",
                "current_iv",
            ]
        ).copy()

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
        prev_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return true_range.rolling(window, min_periods=max(3, window // 2)).mean()

    def _to_market_data(self, *, ticker: str, row: pd.Series, metadata: Mapping[str, Any]) -> MarketData:
        return MarketData(
            ticker=ticker,
            current_price=float(row["Close"]),
            prev_close=float(row.get("prev_close") or row["Close"]),
            price_change_pct=float(row.get("day_change_pct") or 0.0),
            volume_ratio=max(float(row.get("volume_ratio") or 1.0), 0.0),
            premarket_volume_ratio=max(float(row.get("premarket_volume_ratio") or 1.0), 0.0),
            vix=max(float(row.get("vix") or 18.0), 0.0),
            gap_pct=float(row.get("gap_pct") or 0.0),
            day1_return_pct=float(row.get("day1_return_pct") or 0.0),
            post_earnings_drift_pct=float(row.get("post_earnings_drift_pct") or 0.0),
            iv_rank=float(row.get("iv_rank") or 50.0),
            implied_move_pct=float(row.get("implied_move_pct") or 0.0),
            bid_ask_spread_bps=max(float(self.settings.slippage_bps_default), 1.0),
            short_interest_pct=float(row.get("short_interest_pct_float") or 0.0),
            float_rotation=float(row.get("float_rotation") or 0.0),
            rv20=float(row.get("realized_vol_10d") or 0.0),
            beta_20d=1.0,
            relative_strength_20d=self._percentage_points(row.get("relative_strength_20d")),
            sector_momentum=float(row.get("sector_momentum") or 0.0),
            earnings_surprise_pct=float(row.get("surprise_proxy_pct") or 0.0),
            next_earnings_days=None,
            rsi_14=float(row.get("rsi_14") or 50.0),
            macd_signal=float(row.get("macd_signal") or 0.0),
            liquidity_score=float(row.get("liquidity_score") or 0.5),
            put_call_ratio=1.0,
            current_iv=float(row.get("current_iv") or 0.25),
            days_to_cover=max(float(metadata.get("daysToCover") or 1.0), 0.0),
            analyst_revision_delta_pct=float(row.get("analyst_revision_delta_pct") or 0.0),
            hours_since_news=float(row.get("hours_since_news") or 48.0),
            realized_vol_10d=max(float(row.get("realized_vol_10d") or 0.0), 0.0),
            atr_pct_14=float(row.get("atr_pct_14") or 0.0),
            atr_14=max(float(row.get("atr_14") or 0.01), 0.01),
            breakout_20d_pct=float(row.get("breakout_20d_pct") or 0.0),
            high_52w=float(row.get("high_52w") or row["Close"]),
            low_52w=float(row.get("low_52w") or row["Close"]),
            ma20=float(row.get("ma20") or row["Close"]),
            ma50=float(row.get("ma50") or row["Close"]),
            ma200=float(row.get("ma200") or row["Close"]),
            ma_stack_bullish=bool(row.get("ma_stack_bullish")) if row.get("ma_stack_bullish") is not None else None,
            bb_position=float(row.get("bb_position") or 0.5),
            bb_bandwidth=float(row.get("bb_bandwidth") or 0.0),
            stochastic_k=float(row.get("stochastic_k") or 50.0),
            stochastic_d=float(row.get("stochastic_d") or 50.0),
            ichimoku_weekly_tenkan=safe_float(row.get("ichimoku_weekly_tenkan")),
            ichimoku_weekly_kijun=safe_float(row.get("ichimoku_weekly_kijun")),
            ichimoku_weekly_span_a=safe_float(row.get("ichimoku_weekly_span_a")),
            ichimoku_weekly_span_b=safe_float(row.get("ichimoku_weekly_span_b")),
            ichimoku_weekly_cloud_bias=(str(row.get("ichimoku_weekly_cloud_bias")) if row.get("ichimoku_weekly_cloud_bias") is not None else None),
            ichimoku_weekly_cloud_score=safe_float(row.get("ichimoku_weekly_cloud_score")),
            volume_zscore_20d=float(row.get("volume_zscore_20d") or 0.0),
            spy_relative_strength_20d=safe_float(row.get("spy_relative_strength_20d")),
            qqq_relative_strength_20d=safe_float(row.get("qqq_relative_strength_20d")),
            beta_spy_60d=safe_float(row.get("beta_spy_60d")),
            beta_qqq_60d=safe_float(row.get("beta_qqq_60d")),
            nearest_option_expiry_days=(int(row.get("nearest_option_expiry_days")) if row.get("nearest_option_expiry_days") is not None else None),
            zero_dte_available=bool(row.get("zero_dte_available")) if row.get("zero_dte_available") is not None else None,
            zero_dte_put_call_volume_ratio=safe_float(row.get("zero_dte_put_call_volume_ratio")),
            zero_dte_atm_straddle_pct=safe_float(row.get("zero_dte_atm_straddle_pct")),
            zero_dte_gamma_pressure=safe_float(row.get("zero_dte_gamma_pressure")),
            revenue_growth_yoy=safe_float(row.get("revenue_growth_yoy")),
            earnings_growth_yoy=safe_float(row.get("earnings_growth_yoy")),
            gross_margin=safe_float(row.get("gross_margin")),
            operating_margin=safe_float(row.get("operating_margin")),
            fcf_margin=safe_float(row.get("fcf_margin")),
            debt_to_equity=safe_float(row.get("debt_to_equity")),
            current_ratio=safe_float(row.get("current_ratio")),
            market_cap=float(row.get("market_cap") or 0.0),
            market_cap_bucket=str(row.get("market_cap_bucket") or "unknown"),
            sector_code=str(row.get("sector_code") or "unknown"),
            has_options=bool(row.get("has_options")) if row.get("has_options") is not None else True,
        )

    @staticmethod
    def _price_action_raw_score(row: pd.Series) -> float:
        gap = float(row.get("gap_pct") or 0.0) / 100.0
        day_change = float(row.get("day_change_pct") or 0.0) / 100.0
        rs20 = float(row.get("relative_strength_20d") or 0.0)
        volume_ratio = float(row.get("volume_ratio") or 1.0)
        macd = float(row.get("macd_signal") or 0.0)
        score = (
            np.clip(day_change / 0.06, -1.0, 1.0) * 0.30
            + np.clip(gap / 0.06, -1.0, 1.0) * 0.20
            + np.clip(rs20 / 0.15, -1.0, 1.0) * 0.20
            + np.clip((volume_ratio - 1.0) / 2.5, -1.0, 1.0) * 0.20
            + np.clip(macd * 10.0, -1.0, 1.0) * 0.10
        )
        return float(np.clip(score, -1.0, 1.0))

    @staticmethod
    def _proxy_analysis_result(*, raw_score: float, row: pd.Series) -> GeminiAnalysisResult:
        if raw_score > 0.05:
            direction = "BULLISH"
        elif raw_score < -0.05:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"
        magnitude = float(np.clip(abs(raw_score), 0.05, 1.0))
        confidence = float(np.clip(0.45 + magnitude * 0.35 + min(float(row.get("volume_ratio") or 1.0), 3.0) * 0.05, 0.35, 0.92))
        catalyst_type = "PRODUCT_NEWS"
        if abs(float(row.get("gap_pct") or 0.0)) >= 3.0:
            catalyst_type = "EARNINGS_BEAT" if raw_score >= 0 else "GUIDANCE_DOWN"
        elif float(row.get("volume_ratio") or 1.0) >= 2.0 and raw_score >= 0.35:
            catalyst_type = "GUIDANCE_UP"
        return GeminiAnalysisResult(
            direction=direction,
            magnitude=round(magnitude, 4),
            confidence=round(confidence, 4),
            rationale="Deterministic proxy analysis derived from price, gap, and volume response.",
            catalyst_type=catalyst_type,
            euphemism_count=0,
            negative_word_ratio=max(0.0, min(1.0, -raw_score)),
            cot_reasoning="Proxy event inference from OHLCV and volatility features.",
            route_profile="proxy",
            model_route="price_proxy",
        )

    def _is_event_bar(self, *, market_data: MarketData, profile: Any, raw_score: float) -> bool:
        gap_candidate = (
            abs(float(market_data.gap_pct or 0.0)) >= profile.strategy.gap_min_pct
            and abs(raw_score) >= profile.strategy.gap_raw_min
            and float(market_data.volume_ratio or 0.0) >= profile.strategy.gap_liquidity_min
        )
        news_candidate = (
            float(market_data.volume_ratio or 0.0) >= profile.strategy.news_volume_min
            and abs(raw_score) >= profile.strategy.news_raw_min
            and abs(float(market_data.day_change_pct or 0.0)) >= profile.strategy.news_price_change_min
        )
        surprise_candidate = abs(float(market_data.surprise_pct or 0.0)) >= 6.0
        breakout_candidate = float(market_data.breakout_20d_pct or 0.0) >= 0.03
        return bool(gap_candidate or news_candidate or surprise_candidate or breakout_candidate)

    def _exit_bands(self, *, strategy: StrategyName, frame: pd.DataFrame, entry_index: int) -> tuple[float, float]:
        atr_pct = float(frame.iloc[entry_index].get("atr_pct_14") or 0.0)
        base_stop = max(atr_pct * 0.9, 1.8)
        if strategy in {StrategyName.PEAD, StrategyName.MOMENTUM_CARRY, StrategyName.NEWS_BREAKOUT}:
            return base_stop, max(base_stop * 1.7, 3.2)
        if strategy in {StrategyName.GAP_AND_GO, StrategyName.WHISPER_PLAY}:
            return max(base_stop, 2.2), max(base_stop * 1.5, 3.0)
        if strategy in {StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST}:
            return max(base_stop * 0.9, 1.6), max(base_stop * 1.2, 2.4)
        if strategy == StrategyName.SHORT_SQUEEZE:
            return max(base_stop * 1.2, 3.0), max(base_stop * 2.0, 6.0)
        if strategy == StrategyName.IV_CRUSH_DECAY:
            return max(base_stop * 0.8, 1.5), max(base_stop * 1.1, 2.0)
        return base_stop, max(base_stop * 1.4, 2.6)

    def _round_trip_cost_pct(self) -> float:
        return float(self.settings.backtest_round_trip_cost_pct) + float(self.settings.slippage_bps_default) / 100.0

    def _estimated_execution_cost_pct(self, market_data: MarketData) -> float:
        spread_bps = market_data.bid_ask_spread_bps
        if spread_bps is None:
            spread_bps = self.settings.slippage_bps_default
        return (
            float(self.settings.backtest_round_trip_cost_pct)
            + float(spread_bps or 0.0) / 100.0
            + float(self.settings.execution_latency_bps_default) / 100.0
        )

    @staticmethod
    def _mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return float(sum(values) / len(values))

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float:
        if denominator is None or abs(denominator) < 1e-12:
            return 0.0
        return float(numerator / denominator)

    @staticmethod
    def _classify_regime(market_data: MarketData) -> str:
        if float(market_data.vix or 0.0) >= 25.0:
            return "high_vol"
        if ResearchBacktestService._percentage_points(market_data.relative_strength_20d) < -5.0:
            return "risk_off"
        if ResearchBacktestService._percentage_points(market_data.relative_strength_20d) > 8.0:
            return "trend_up"
        return "normal"

    @staticmethod
    def _market_cap_bucket(market_cap: float) -> str:
        if market_cap >= 200_000_000_000:
            return "mega"
        if market_cap >= 10_000_000_000:
            return "large"
        if market_cap >= 2_000_000_000:
            return "mid"
        if market_cap >= 300_000_000:
            return "small"
        return "micro"

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, float(value)))

    @staticmethod
    def _percentage_points(value: float | None) -> float:
        try:
            numeric = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return numeric * 100.0 if abs(numeric) <= 1.0 else numeric

    @staticmethod
    def _benchmark_return_pct(frame: pd.DataFrame, min_history: int) -> float:
        if len(frame) <= min_history:
            return 0.0
        start = float(frame["Close"].iloc[min_history])
        end = float(frame["Close"].iloc[-1])
        if start <= 0:
            return 0.0
        return ((end / start) - 1.0) * 100.0

    @staticmethod
    def _index_for_timestamp(frame: pd.DataFrame, ts_text: str) -> int:
        ts = pd.Timestamp(ts_text)
        matches = np.where(frame.index == ts)[0]
        return int(matches[0]) if len(matches) else max(0, len(frame) - 1)

    @staticmethod
    def _period_to_lookback_days(period: str, *, start_date: str | None = None, end_date: str | None = None) -> int:
        if start_date and end_date:
            try:
                start_ts = pd.Timestamp(start_date).normalize()
                end_ts = pd.Timestamp(end_date).normalize()
                if end_ts >= start_ts:
                    return max(1, int((end_ts - start_ts).days) + 1)
            except Exception:
                pass
        mapping = {
            "3mo": 95,
            "6mo": 190,
            "9mo": 285,
            "1y": 365,
            "2y": 730,
            "5y": 1826,
            "6y": 2191,
        }
        return mapping.get(str(period).strip().lower(), 365)

    @staticmethod
    def _row_in_date_range(event_time: Any, *, start_date: str | None = None, end_date: str | None = None) -> bool:
        try:
            event_ts = pd.Timestamp(event_time)
        except Exception:
            return False
        if start_date:
            try:
                if event_ts < pd.Timestamp(start_date):
                    return False
            except Exception:
                return False
        if end_date:
            try:
                if event_ts > pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1):
                    return False
            except Exception:
                return False
        return True

    @staticmethod
    def _data_window_label(*, period: str, start_date: str | None = None, end_date: str | None = None) -> str:
        if start_date or end_date:
            return f"{start_date or 'open'}_to_{end_date or 'open'}"
        return str(period)

    def _download_history(
        self,
        ticker: str,
        period: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame | None:
        try:
            import yfinance as yf
        except Exception:
            return None
        self._configure_yfinance_cache(yf)
        try:
            download_kwargs: dict[str, Any] = {
                "tickers": ticker,
                "interval": "1d",
                "auto_adjust": False,
                "progress": False,
                "threads": False,
            }
            if start_date or end_date:
                if start_date:
                    download_kwargs["start"] = start_date
                if end_date:
                    download_kwargs["end"] = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                download_kwargs["period"] = period
            frame = yf.download(**download_kwargs)
        except Exception:
            return None
        if frame is None or frame.empty:
            return None
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        return frame.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

    def _download_history_batch(
        self,
        tickers: list[str],
        period: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, pd.DataFrame | None]:
        try:
            import yfinance as yf
        except Exception:
            return {ticker: None for ticker in tickers}
        self._configure_yfinance_cache(yf)
        results: dict[str, pd.DataFrame | None] = {ticker: None for ticker in tickers}
        for chunk_start in range(0, len(tickers), 40):
            chunk = tickers[chunk_start : chunk_start + 40]
            try:
                download_kwargs: dict[str, Any] = {
                    "tickers": chunk,
                    "interval": "1d",
                    "auto_adjust": False,
                    "progress": False,
                    # yfinance worker threads can keep the CLI alive after artifacts
                    # are written on some Windows/Python 3.13 environments.
                    "threads": False,
                    "group_by": "ticker",
                }
                if start_date or end_date:
                    if start_date:
                        download_kwargs["start"] = start_date
                    if end_date:
                        download_kwargs["end"] = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    download_kwargs["period"] = period
                frame = yf.download(**download_kwargs)
            except Exception:
                frame = None
            if frame is None or frame.empty:
                for ticker in chunk:
                    results[ticker] = self._download_history(ticker, period, start_date=start_date, end_date=end_date)
                continue
            if isinstance(frame.columns, pd.MultiIndex):
                level0 = list(dict.fromkeys(frame.columns.get_level_values(0)))
                level1 = list(dict.fromkeys(frame.columns.get_level_values(1)))
                if any(ticker in level0 for ticker in chunk):
                    for ticker in chunk:
                        try:
                            subframe = frame[ticker].dropna(subset=["Open", "High", "Low", "Close", "Volume"])
                        except Exception:
                            subframe = None
                        results[ticker] = (
                            subframe
                            if subframe is not None and not subframe.empty
                            else self._download_history(ticker, period, start_date=start_date, end_date=end_date)
                        )
                elif any(ticker in level1 for ticker in chunk):
                    for ticker in chunk:
                        try:
                            subframe = frame.xs(ticker, axis=1, level=1).dropna(subset=["Open", "High", "Low", "Close", "Volume"])
                        except Exception:
                            subframe = None
                        results[ticker] = (
                            subframe
                            if subframe is not None and not subframe.empty
                            else self._download_history(ticker, period, start_date=start_date, end_date=end_date)
                        )
                else:
                    for ticker in chunk:
                        results[ticker] = self._download_history(ticker, period, start_date=start_date, end_date=end_date)
            else:
                only = chunk[0] if len(chunk) == 1 else None
                if only is not None:
                    results[only] = frame.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
                else:
                    for ticker in chunk:
                        results[ticker] = self._download_history(ticker, period, start_date=start_date, end_date=end_date)
        return results

    def _load_ticker_metadata(self, ticker: str) -> dict[str, Any]:
        cached = self._metadata_cache.get(ticker)
        if cached is not None:
            return cached
        try:
            import yfinance as yf
        except Exception:
            payload = {"sector": "unknown", "market_cap": 0.0}
            self._metadata_cache[ticker] = payload
            return payload
        self._configure_yfinance_cache(yf)
        try:
            ticker_obj = yf.Ticker(ticker)
            fast_info = ticker_obj.fast_info
            try:
                info = ticker_obj.info or {}
            except Exception:
                info = {}
            payload = {
                "sector": str(info.get("sector") or "unknown"),
                "market_cap": float(getattr(fast_info, "market_cap", 0.0) or info.get("marketCap") or 0.0),
                "revenueGrowth": info.get("revenueGrowth"),
                "earningsGrowth": info.get("earningsGrowth"),
                "grossMargins": info.get("grossMargins"),
                "operatingMargins": info.get("operatingMargins"),
                "debtToEquity": info.get("debtToEquity"),
                "currentRatio": info.get("currentRatio"),
                "totalRevenue": info.get("totalRevenue"),
                "freeCashflow": info.get("freeCashflow"),
                "has_options": bool(info.get("quoteType") == "EQUITY"),
            }
        except Exception:
            payload = {"sector": "unknown", "market_cap": 0.0}
        self._metadata_cache[ticker] = payload
        return payload

    def _configure_yfinance_cache(self, yf: Any) -> None:
        if self._yfinance_cache_ready:
            return
        cache_dir = Path(__file__).resolve().parents[1] / "data" / "yfinance_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "GIT_HTTP_PROXY",
            "GIT_HTTPS_PROXY",
            "git_http_proxy",
            "git_https_proxy",
        ):
            os.environ.pop(key, None)
        try:
            yf.set_tz_cache_location(str(cache_dir))
        except Exception:
            pass
        self._yfinance_cache_ready = True


__all__ = ["BacktestMetrics", "BacktestTrade", "ResearchBacktestService", "TrackResult"]
