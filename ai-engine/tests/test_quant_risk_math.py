from __future__ import annotations

import pytest

from core.quant_risk_math import (
    beta_posterior_mean,
    execution_edge_after_cost,
    fractional_kelly_fraction,
    wilson_lower_bound,
)


def test_wilson_lower_bound_penalizes_small_samples() -> None:
    assert wilson_lower_bound(8, 10) < 0.80
    assert wilson_lower_bound(80, 100) > wilson_lower_bound(8, 10)


def test_beta_posterior_mean_uses_prior_smoothing() -> None:
    assert beta_posterior_mean(0, 0) == pytest.approx(0.5)
    assert beta_posterior_mean(8, 2) == pytest.approx(0.75)


def test_fractional_kelly_is_bounded_and_zero_for_bad_edge() -> None:
    assert fractional_kelly_fraction(win_probability=0.60, avg_win_pct=2.0, avg_loss_pct=-1.0, max_fraction=0.12) > 0.0
    assert fractional_kelly_fraction(win_probability=0.40, avg_win_pct=1.0, avg_loss_pct=-2.0, max_fraction=0.12) == 0.0
    assert fractional_kelly_fraction(win_probability=0.90, avg_win_pct=5.0, avg_loss_pct=-1.0, max_fraction=0.03) <= 0.03


def test_execution_edge_after_cost_subtracts_spread_latency_and_uncertainty() -> None:
    edge = execution_edge_after_cost(
        gross_edge_pct=1.2,
        round_trip_cost_pct=0.30,
        spread_bps=20.0,
        latency_bps=5.0,
        uncertainty_buffer_pct=0.10,
    )

    assert edge == pytest.approx(0.55)
