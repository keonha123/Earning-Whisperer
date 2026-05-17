"""Probability and sizing helpers adapted from core quant interview/math concepts."""

from __future__ import annotations

import math


def wilson_lower_bound(successes: int, trials: int, *, z: float = 1.96) -> float:
    """Return the Wilson lower confidence bound for a Bernoulli success rate."""
    if trials <= 0:
        return 0.0
    n = float(trials)
    phat = max(0.0, min(1.0, float(successes) / n))
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = phat + z2 / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    return max(0.0, min(1.0, (center - margin) / denominator))


def beta_posterior_mean(successes: int, failures: int, *, alpha: float = 1.0, beta: float = 1.0) -> float:
    """Return the beta-binomial posterior mean with a configurable prior."""
    numerator = max(0.0, float(successes)) + max(0.0, float(alpha))
    denominator = numerator + max(0.0, float(failures)) + max(0.0, float(beta))
    if denominator <= 0.0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def fractional_kelly_fraction(
    *,
    win_probability: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    fraction: float = 0.25,
    max_fraction: float = 0.12,
) -> float:
    """Return a bounded fractional Kelly size from win probability and payoff ratio."""
    p = max(0.0, min(1.0, float(win_probability)))
    q = 1.0 - p
    win = max(0.0, float(avg_win_pct))
    loss = abs(min(0.0, float(avg_loss_pct)))
    if win <= 0.0 or loss <= 0.0:
        return 0.0
    payoff_ratio = win / loss
    raw_kelly = p - (q / payoff_ratio)
    sized = max(0.0, raw_kelly) * max(0.0, float(fraction))
    return max(0.0, min(float(max_fraction), sized))


def execution_edge_after_cost(
    *,
    gross_edge_pct: float,
    round_trip_cost_pct: float,
    spread_bps: float,
    latency_bps: float = 0.0,
    uncertainty_buffer_pct: float = 0.0,
) -> float:
    """Return expected edge after market-making style spread, latency, and uncertainty costs."""
    all_in_cost = (
        float(round_trip_cost_pct)
        + float(spread_bps) / 100.0
        + float(latency_bps) / 100.0
        + max(0.0, float(uncertainty_buffer_pct))
    )
    return float(gross_edge_pct) - all_in_cost


__all__ = [
    "beta_posterior_mean",
    "execution_edge_after_cost",
    "fractional_kelly_fraction",
    "wilson_lower_bound",
]
