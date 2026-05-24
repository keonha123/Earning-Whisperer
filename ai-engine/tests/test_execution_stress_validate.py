from __future__ import annotations

import json

from tools.execution_stress_validate import ExecutionStressScenario, render_markdown, run_execution_stress


def _trade(ticker: str, gross_return_pct: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "signal_at": "2025-01-02T00:00:00",
        "entry_at": "2025-01-03T00:00:00",
        "exit_at": "2025-01-06T00:00:00",
        "universe_profile": "NASDAQ100",
        "risk_style": "CONSERVATIVE",
        "strategy": "PEAD",
        "regime": "normal",
        "simulation_mode": "price_proxy",
        "direction": "BULLISH",
        "hold_days": 2,
        "gross_return_pct": gross_return_pct,
        "net_return_pct": gross_return_pct - 0.38,
        "mfe_pct": max(gross_return_pct, 0.0),
        "mae_pct": min(gross_return_pct, 0.0),
        "position_scale": 1.0,
        "benchmark_return_pct": 0.0,
        "entry_price": 100.0,
        "exit_price": 100.0 + gross_return_pct,
        "metadata": {"sector_code": "TECHNOLOGY"},
    }


def test_execution_stress_recomputes_net_returns_from_gross(tmp_path) -> None:
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {
                "effective_result": {
                    "simulation_mode": "price_proxy",
                    "universe_profile": "NASDAQ100",
                    "risk_style": "CONSERVATIVE",
                    "metrics": {"benchmark_return_pct": 0.0},
                    "trades": [_trade("AAA", 2.0), _trade("BBB", 1.5), _trade("CCC", -0.5)],
                }
            }
        ),
        encoding="utf-8",
    )

    payload = run_execution_stress(
        input_json=path,
        scenarios=(ExecutionStressScenario("test", 0.30, 10.0, 10.0),),
    )

    metrics = payload["scenarios"][0]["metrics"]
    assert payload["trade_count"] == 3
    assert payload["scenarios"][0]["cost_model"]["total_cost_pct"] == 0.5
    assert metrics["avg_trade_return_pct"] == 0.5
    assert payload["scenarios"][0]["checks"]["avg_trade_return_pct"] is True


def test_execution_stress_markdown_contains_pass_column() -> None:
    markdown = render_markdown(
        {
            "source_file": "source.json",
            "source_simulation_mode": "price_proxy",
            "source_universe_profile": "NASDAQ100",
            "source_risk_style": "CONSERVATIVE",
            "trade_count": 1,
            "scenarios": [
                {
                    "scenario": "base",
                    "cost_model": {"total_cost_pct": 0.38},
                    "metrics": {
                        "trade_count": 1,
                        "win_rate_pct": 100.0,
                        "avg_trade_return_pct": 1.0,
                        "profit_factor": 999.0,
                        "sharpe_ratio": 0.0,
                        "max_drawdown_pct": 0.0,
                    },
                    "passed": False,
                }
            ],
        }
    )

    assert "Passed" in markdown
    assert "| base |" in markdown
