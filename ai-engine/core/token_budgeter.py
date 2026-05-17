"""Prompt budget resolution and aggregate LLM token telemetry."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

try:
    from config import Settings, get_settings
except ImportError:  # pragma: no cover
    from ..config import Settings, get_settings


DEFAULT_PROMPT_BUDGETS = {
    "economy": 384,
    "standard": 640,
    "review": 960,
}


@dataclass(slots=True)
class TokenUsageEvent:
    route_profile: str
    model: str
    prompt_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    cached: bool = False
    coalesced: bool = False
    approved_signal: bool = False
    budget_tokens: int = 0


class TokenBudgeter:
    """Tracks prompt budgets and aggregate token/cost telemetry by route profile."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._events: list[TokenUsageEvent] = []

    def prompt_budget(self, route_profile: str | None) -> int:
        profile = str(route_profile or "economy").strip().lower()
        if profile == "review":
            return int(self.settings.analysis_prompt_budget_review)
        if profile == "standard":
            return int(self.settings.analysis_prompt_budget_standard)
        if profile == "economy":
            return int(self.settings.analysis_prompt_budget_economy)
        return int(DEFAULT_PROMPT_BUDGETS.get(profile, self.settings.analysis_prompt_budget_standard))

    def estimate_cost_usd(self, *, route_profile: str | None, prompt_tokens: int, output_tokens: int) -> float:
        profile = str(route_profile or "economy").strip().lower()
        if profile == "review":
            input_rate = float(self.settings.llm_cost_review_input_per_million)
            output_rate = float(self.settings.llm_cost_review_output_per_million)
        else:
            input_rate = float(self.settings.llm_cost_primary_input_per_million)
            output_rate = float(self.settings.llm_cost_primary_output_per_million)
        return round(((prompt_tokens / 1_000_000.0) * input_rate) + ((output_tokens / 1_000_000.0) * output_rate), 8)

    def record(self, event: TokenUsageEvent) -> None:
        self._events.append(event)

    def snapshot(self) -> dict[str, Any]:
        request_count = len(self._events)
        prompt_tokens = sum(item.prompt_tokens for item in self._events)
        output_tokens = sum(item.output_tokens for item in self._events)
        total_cost = sum(item.estimated_cost_usd for item in self._events)
        cached = sum(1 for item in self._events if item.cached)
        coalesced = sum(1 for item in self._events if item.coalesced)
        approved = sum(1 for item in self._events if item.approved_signal)
        budget_exceeded = sum(1 for item in self._events if item.budget_tokens > 0 and item.prompt_tokens > item.budget_tokens)

        route_counts: dict[str, int] = {}
        route_tokens: dict[str, dict[str, float]] = {}
        for item in self._events:
            route_counts[item.route_profile] = route_counts.get(item.route_profile, 0) + 1
            bucket = route_tokens.setdefault(
                item.route_profile,
                {
                    "request_count": 0,
                    "prompt_tokens": 0.0,
                    "output_tokens": 0.0,
                    "estimated_cost_usd": 0.0,
                    "budget_tokens": float(item.budget_tokens or 0),
                },
            )
            bucket["request_count"] += 1
            bucket["prompt_tokens"] += float(item.prompt_tokens)
            bucket["output_tokens"] += float(item.output_tokens)
            bucket["estimated_cost_usd"] += float(item.estimated_cost_usd)
            if item.budget_tokens:
                bucket["budget_tokens"] = float(item.budget_tokens)

        route_stats = {
            route: {
                "request_count": int(payload["request_count"]),
                "avg_prompt_tokens": round(payload["prompt_tokens"] / max(payload["request_count"], 1), 4),
                "avg_output_tokens": round(payload["output_tokens"] / max(payload["request_count"], 1), 4),
                "estimated_cost_usd": round(payload["estimated_cost_usd"], 6),
                "budget_tokens": int(payload["budget_tokens"]),
            }
            for route, payload in route_tokens.items()
        }
        return {
            "request_count": request_count,
            "avg_prompt_tokens": round(prompt_tokens / max(request_count, 1), 4),
            "avg_output_tokens": round(output_tokens / max(request_count, 1), 4),
            "cache_hit_rate": round(cached / max(request_count, 1), 6),
            "coalesced_request_rate": round(coalesced / max(request_count, 1), 6),
            "estimated_total_cost_usd": round(total_cost, 6),
            "approved_signal_count": approved,
            "cost_per_approved_signal": round(total_cost / max(approved, 1), 6),
            "budget_exceeded_count": budget_exceeded,
            "prompt_budgets": {
                "economy": self.prompt_budget("economy"),
                "standard": self.prompt_budget("standard"),
                "review": self.prompt_budget("review"),
            },
            "route_stats": route_stats,
            "route_counts": route_counts,
        }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    compact = " ".join(str(text).split())
    if not compact:
        return 0
    word_tokens = len(compact.split())
    char_tokens = math.ceil(len(compact) / 4)
    return max(word_tokens, char_tokens)


__all__ = ["DEFAULT_PROMPT_BUDGETS", "TokenBudgeter", "TokenUsageEvent", "estimate_tokens"]
