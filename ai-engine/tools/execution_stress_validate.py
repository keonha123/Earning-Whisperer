"""Validate a backtest artifact under broker execution cost and slippage stress."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping


def _bootstrap() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root.parent))


_bootstrap()

try:
    from ai_engine.services.research_backtest_service import BacktestTrade, ResearchBacktestService  # type: ignore  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - direct package checkout fallback
    from services.research_backtest_service import BacktestTrade, ResearchBacktestService  # noqa: E402


@dataclass(slots=True)
class ExecutionStressScenario:
    name: str
    round_trip_cost_pct: float
    slippage_bps: float
    latency_adverse_bps: float

    @property
    def total_cost_pct(self) -> float:
        return float(self.round_trip_cost_pct) + (float(self.slippage_bps) / 100.0) + (float(self.latency_adverse_bps) / 100.0)


DEFAULT_SCENARIOS = (
    ExecutionStressScenario("base_recomputed", 0.30, 8.0, 0.0),
    ExecutionStressScenario("broker_normal", 0.35, 15.0, 5.0),
    ExecutionStressScenario("earnings_gap_stress", 0.50, 30.0, 10.0),
    ExecutionStressScenario("extreme_spread_stress", 0.75, 50.0, 15.0),
)


def _trade_from_payload(payload: Mapping[str, Any], *, net_return_pct: float | None = None) -> BacktestTrade:
    return BacktestTrade(
        ticker=str(payload.get("ticker") or "UNKNOWN"),
        signal_at=str(payload.get("signal_at") or ""),
        entry_at=str(payload.get("entry_at") or payload.get("signal_at") or ""),
        exit_at=str(payload.get("exit_at") or payload.get("entry_at") or payload.get("signal_at") or ""),
        universe_profile=str(payload.get("universe_profile") or "UNKNOWN"),
        risk_style=str(payload.get("risk_style") or "UNKNOWN"),
        strategy=str(payload.get("strategy") or "UNKNOWN"),
        regime=str(payload.get("regime") or "unknown"),
        simulation_mode=str(payload.get("simulation_mode") or "price_proxy"),
        direction=str(payload.get("direction") or "BULLISH"),
        hold_days=int(payload.get("hold_days") or 1),
        gross_return_pct=float(payload.get("gross_return_pct") or 0.0),
        net_return_pct=float(payload.get("net_return_pct") if net_return_pct is None else net_return_pct),
        mfe_pct=float(payload.get("mfe_pct") or 0.0),
        mae_pct=float(payload.get("mae_pct") or 0.0),
        position_scale=float(payload.get("position_scale") or 1.0),
        benchmark_return_pct=float(payload.get("benchmark_return_pct") or 0.0),
        entry_price=float(payload.get("entry_price") or 0.0),
        exit_price=float(payload.get("exit_price") or 0.0),
        blocked_reasons=list(payload.get("blocked_reasons") or []),
        metadata=dict(payload.get("metadata") or {}),
    )


def _load_effective_trades(path: str | Path) -> tuple[dict[str, Any], list[BacktestTrade]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    effective = payload.get("effective_result") or {}
    trades = [_trade_from_payload(item) for item in effective.get("trades") or []]
    return payload, trades


def _evaluate_checks(metrics: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "trade_count": int(metrics.get("trade_count", 0)) >= 40,
        "win_rate_pct": float(metrics.get("win_rate_pct", 0.0)) >= 50.0,
        "avg_trade_return_pct": float(metrics.get("avg_trade_return_pct", 0.0)) > 0.0,
        "profit_factor": float(metrics.get("profit_factor", 0.0)) >= 1.05,
        "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0)) >= -15.0,
    }


def run_execution_stress(
    *,
    input_json: str | Path,
    scenarios: tuple[ExecutionStressScenario, ...] = DEFAULT_SCENARIOS,
) -> dict[str, Any]:
    source_payload, source_trades = _load_effective_trades(input_json)
    service = ResearchBacktestService()
    source_effective = source_payload.get("effective_result") or {}
    reports: list[dict[str, Any]] = []

    for scenario in scenarios:
        stressed_trades = []
        for trade in source_trades:
            gross_return_pct = float(trade.gross_return_pct)
            net_return_pct = gross_return_pct - scenario.total_cost_pct
            stressed = _trade_from_payload(asdict(trade), net_return_pct=net_return_pct)
            stressed.metadata["execution_stress"] = asdict(scenario) | {"total_cost_pct": round(scenario.total_cost_pct, 4)}
            stressed_trades.append(stressed)

        metrics = service._compute_metrics(
            stressed_trades,
            approved_count=len(stressed_trades),
            rejected_count=0,
            benchmark_return_pct=float((source_effective.get("metrics") or {}).get("benchmark_return_pct") or 0.0),
        ).to_dict()
        checks = _evaluate_checks(metrics)
        reports.append(
            {
                "scenario": scenario.name,
                "cost_model": asdict(scenario) | {"total_cost_pct": round(scenario.total_cost_pct, 4)},
                "metrics": metrics,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    return {
        "source_file": str(input_json),
        "source_simulation_mode": source_effective.get("simulation_mode"),
        "source_universe_profile": source_effective.get("universe_profile"),
        "source_risk_style": source_effective.get("risk_style"),
        "trade_count": len(source_trades),
        "scenarios": reports,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Execution Stress Validation",
        "",
        f"- Source file: `{payload.get('source_file')}`",
        f"- Source mode: `{payload.get('source_simulation_mode')}`",
        f"- Universe profile: `{payload.get('source_universe_profile')}`",
        f"- Risk style: `{payload.get('source_risk_style')}`",
        f"- Source trade count: `{payload.get('trade_count')}`",
        "",
        "| Scenario | Total Cost % | Trades | Win % | Avg % | PF | Sharpe | MDD % | Passed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for report in payload.get("scenarios") or []:
        metrics = report.get("metrics") or {}
        cost_model = report.get("cost_model") or {}
        lines.append(
            f"| {report.get('scenario')} | {cost_model.get('total_cost_pct')} | "
            f"{metrics.get('trade_count')} | {metrics.get('win_rate_pct')} | "
            f"{metrics.get('avg_trade_return_pct')} | {metrics.get('profit_factor')} | "
            f"{metrics.get('sharpe_ratio')} | {metrics.get('max_drawdown_pct')} | {report.get('passed')} |"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run execution cost/slippage stress validation on a backtest artifact.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = run_execution_stress(input_json=args.input_json)
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(render_markdown(payload), encoding="utf-8")
    if not args.quiet:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
