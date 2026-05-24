"""Canonical bundle normalization and source-health telemetry for the AI engine."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

try:
    from models.canonical_models import CanonicalEventBundle, CanonicalSourceHealth, SourceHealthStatus
    from models.request_models import MarketData
except ImportError:  # pragma: no cover
    from ..models.canonical_models import CanonicalEventBundle, CanonicalSourceHealth, SourceHealthStatus
    from ..models.request_models import MarketData


def _clip(text: str | None, limit: int = 180) -> str | None:
    if not text:
        return None
    normalized = " ".join(str(text).split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3] + "..."


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CanonicalBundleService:
    def build_feature_bundle(
        self,
        *,
        ticker: str,
        market_data: MarketData,
        current_chunk: str,
        canonical_bundle: CanonicalEventBundle | None = None,
        source_health: list[CanonicalSourceHealth] | None = None,
    ) -> dict[str, Any]:
        bundle = canonical_bundle or CanonicalEventBundle()
        effective_source_health = list(source_health or bundle.source_health or [])
        source_health_summary = self.summarize_source_health(effective_source_health)

        coverage = {
            "company": bundle.company is not None,
            "earnings_event": bundle.earnings_event is not None,
            "transcript": bundle.transcript is not None,
            "guidance": bundle.guidance is not None,
            "market_overlay": bundle.market_overlay is not None,
            "analyst_overlay": bundle.analyst_overlay is not None,
            "source_health": bool(effective_source_health),
        }
        coverage_pct = round((sum(1 for value in coverage.values() if value) / max(1, len(coverage))) * 100.0, 2)

        transcript = bundle.transcript
        guidance = bundle.guidance
        market_overlay = bundle.market_overlay
        analyst_overlay = bundle.analyst_overlay
        company = bundle.company
        earnings_event = bundle.earnings_event

        prompt_parts: list[str] = []
        highlights_ko: list[str] = []

        if guidance and guidance.direction:
            prompt_parts.append(f"GUIDANCE={guidance.direction}")
            highlights_ko.append(f"가이던스 방향: {guidance.direction}")
        if guidance and guidance.margin_delta_pct is not None:
            prompt_parts.append(f"MARGIN_DELTA={guidance.margin_delta_pct:.2f}")
        if transcript and transcript.qna_sentiment_delta is not None:
            prompt_parts.append(f"QNA_SENTIMENT_DELTA={transcript.qna_sentiment_delta:.2f}")
            highlights_ko.append(f"Q&A 감성 변화: {transcript.qna_sentiment_delta:.2f}")
        if transcript and transcript.prepared_vs_qa_gap is not None:
            prompt_parts.append(f"PREPARED_QA_GAP={transcript.prepared_vs_qa_gap:.2f}")
        if market_overlay and market_overlay.short_interest_pct is not None:
            prompt_parts.append(f"SHORT_INTEREST={market_overlay.short_interest_pct:.2f}")
        if analyst_overlay and analyst_overlay.revision_delta_pct is not None:
            prompt_parts.append(f"ANALYST_REVISION={analyst_overlay.revision_delta_pct:.2f}")
        if market_data.market_cap_bucket or (company and company.market_cap_bucket):
            prompt_parts.append(f"CAP_BUCKET={market_data.market_cap_bucket or company.market_cap_bucket}")
        if source_health_summary["degraded_sources"]:
            prompt_parts.append("DEGRADED_SOURCES=" + ",".join(source_health_summary["degraded_sources"][:3]))
        if source_health_summary["stale_sources"]:
            prompt_parts.append("STALE_SOURCES=" + ",".join(source_health_summary["stale_sources"][:3]))

        if not prompt_parts and current_chunk:
            prompt_parts.append(f"CHUNK_LEN={len(current_chunk.strip().split())}")

        return {
            "canonical_present": canonical_bundle is not None,
            "coverage": coverage,
            "coverage_pct": coverage_pct,
            "company": (company.model_dump(mode="json") if company else {}),
            "earnings_event": (earnings_event.model_dump(mode="json") if earnings_event else {}),
            "transcript": {
                "prepared_summary": _clip(transcript.prepared_summary) if transcript else None,
                "qa_summary": _clip(transcript.qa_summary) if transcript else None,
                "prepared_vs_qa_gap": _safe_float(transcript.prepared_vs_qa_gap) if transcript else None,
                "qna_sentiment_delta": _safe_float(transcript.qna_sentiment_delta) if transcript else None,
                "key_quotes": list((transcript.key_quotes if transcript else [])[:3]),
            },
            "guidance": {
                "direction": guidance.direction if guidance else None,
                "summary": _clip(guidance.summary) if guidance else None,
                "revenue_growth_pct": _safe_float(guidance.revenue_growth_pct) if guidance else None,
                "margin_delta_pct": _safe_float(guidance.margin_delta_pct) if guidance else None,
                "capex_delta_pct": _safe_float(guidance.capex_delta_pct) if guidance else None,
            },
            "market_overlay": (market_overlay.model_dump(mode="json") if market_overlay else {}),
            "analyst_overlay": (analyst_overlay.model_dump(mode="json") if analyst_overlay else {}),
            "source_health_summary": source_health_summary,
            "prompt_context": " | ".join(prompt_parts[:8]),
            "highlights_ko": highlights_ko[:6],
        }

    @staticmethod
    def summarize_source_health(source_health: list[CanonicalSourceHealth]) -> dict[str, Any]:
        healthy = degraded = down = unknown = stale = 0
        freshness_total = 0.0
        freshness_count = 0
        degraded_sources: list[str] = []
        stale_sources: list[str] = []
        sources: list[dict[str, Any]] = []

        for item in source_health:
            raw_status = item.status.value if isinstance(item.status, SourceHealthStatus) else str(item.status)
            status = SourceHealthStatus(raw_status)
            freshness = _safe_float(item.freshness_seconds)
            is_stale = freshness is not None and freshness > 3600.0
            if status == SourceHealthStatus.HEALTHY:
                healthy += 1
            elif status == SourceHealthStatus.DEGRADED:
                degraded += 1
                degraded_sources.append(item.source)
            elif status == SourceHealthStatus.DOWN:
                down += 1
                degraded_sources.append(item.source)
            else:
                unknown += 1
            if is_stale:
                stale += 1
                stale_sources.append(item.source)
            if freshness is not None:
                freshness_total += freshness
                freshness_count += 1
            sources.append(
                {
                    "source": item.source,
                    "status": status.value,
                    "freshness_seconds": freshness,
                    "latency_ms": _safe_float(item.latency_ms),
                    "error_rate_pct": _safe_float(item.error_rate_pct),
                    "stale": is_stale,
                }
            )

        total = len(source_health)
        return {
            "total_sources": total,
            "healthy_count": healthy,
            "degraded_count": degraded,
            "down_count": down,
            "unknown_count": unknown,
            "stale_count": stale,
            "coverage_pct": round((healthy / total) * 100.0, 2) if total else 0.0,
            "avg_freshness_seconds": round(freshness_total / freshness_count, 2) if freshness_count else None,
            "degraded_sources": sorted(set(degraded_sources)),
            "stale_sources": sorted(set(stale_sources)),
            "sources": sources,
        }


class SourceHealthTelemetry:
    def __init__(self) -> None:
        self.total_requests = 0
        self.requests_with_canonical = 0
        self.requests_with_source_health = 0
        self.requests_with_stale_sources = 0
        self._by_source: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "seen": 0,
                "healthy": 0,
                "degraded": 0,
                "down": 0,
                "unknown": 0,
                "stale": 0,
                "freshness_total": 0.0,
                "freshness_count": 0,
            }
        )

    def record(self, feature_bundle: dict[str, Any]) -> None:
        self.total_requests += 1
        if feature_bundle.get("canonical_present"):
            self.requests_with_canonical += 1
        source_summary = feature_bundle.get("source_health_summary") if isinstance(feature_bundle, dict) else {}
        if source_summary and source_summary.get("total_sources"):
            self.requests_with_source_health += 1
        if source_summary and source_summary.get("stale_count", 0):
            self.requests_with_stale_sources += 1
        for item in source_summary.get("sources", []) if isinstance(source_summary, dict) else []:
            source = str(item.get("source") or "unknown")
            bucket = self._by_source[source]
            bucket["seen"] += 1
            status = str(item.get("status") or "UNKNOWN")
            if status == "HEALTHY":
                bucket["healthy"] += 1
            elif status == "DEGRADED":
                bucket["degraded"] += 1
            elif status == "DOWN":
                bucket["down"] += 1
            else:
                bucket["unknown"] += 1
            if item.get("stale"):
                bucket["stale"] += 1
            freshness = _safe_float(item.get("freshness_seconds"))
            if freshness is not None:
                bucket["freshness_total"] += freshness
                bucket["freshness_count"] += 1

    def snapshot(self) -> dict[str, Any]:
        sources: dict[str, Any] = {}
        for source, bucket in sorted(self._by_source.items()):
            seen = max(1, int(bucket["seen"]))
            sources[source] = {
                "seen": int(bucket["seen"]),
                "healthy_rate": round(bucket["healthy"] / seen, 4),
                "degraded_rate": round(bucket["degraded"] / seen, 4),
                "down_rate": round(bucket["down"] / seen, 4),
                "stale_rate": round(bucket["stale"] / seen, 4),
                "avg_freshness_seconds": round(bucket["freshness_total"] / bucket["freshness_count"], 2)
                if bucket["freshness_count"]
                else None,
            }
        total_requests = max(1, self.total_requests)
        return {
            "total_requests": self.total_requests,
            "canonical_bundle_rate": round(self.requests_with_canonical / total_requests, 4),
            "source_health_rate": round(self.requests_with_source_health / total_requests, 4),
            "stale_source_rate": round(self.requests_with_stale_sources / total_requests, 4),
            "sources": sources,
        }


__all__ = ["CanonicalBundleService", "SourceHealthTelemetry"]
