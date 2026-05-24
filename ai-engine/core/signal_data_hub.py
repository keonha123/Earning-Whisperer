"""In-process signal data hub for feature freshness, cache reuse, and source observability.

The hub intentionally reimplements a small producer/connector-style runtime boundary
inside the Python AI engine. It does not import or copy external terminal code; it
standardizes already-ingested feature bundles and source-health snapshots so analysis,
stats, and future adapters can share one deterministic data contract.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import RLock
from time import time
from typing import Any, Callable


@dataclass(frozen=True)
class SignalDataHubPolicy:
    """Freshness policy for a topic or topic prefix."""

    ttl_seconds: float = 300.0
    allow_stale: bool = True
    source: str = "runtime"


@dataclass
class SignalDataHubRecord:
    """Stored value plus freshness metadata."""

    topic: str
    value: Any
    source: str
    created_at: float
    expires_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_stale(self, now: float | None = None) -> bool:
        return (time() if now is None else now) >= self.expires_at

    def age_seconds(self, now: float | None = None) -> float:
        return max(0.0, (time() if now is None else now) - self.created_at)

    def to_summary(self, *, include_value: bool = False, now: float | None = None) -> dict[str, Any]:
        current_time = time() if now is None else now
        payload = {
            "topic": self.topic,
            "source": self.source,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "age_seconds": round(self.age_seconds(current_time), 4),
            "ttl_remaining_seconds": round(max(0.0, self.expires_at - current_time), 4),
            "stale": self.is_stale(current_time),
            "metadata": dict(self.metadata),
        }
        if include_value:
            payload["value"] = self.value
        return payload


class SignalDataHub:
    """Small deterministic topic hub for analysis-time feature sharing."""

    DEFAULT_POLICIES: dict[str, SignalDataHubPolicy] = {
        "feature_bundle:": SignalDataHubPolicy(ttl_seconds=120.0, allow_stale=True, source="feature_bundle"),
        "source_health:": SignalDataHubPolicy(ttl_seconds=300.0, allow_stale=True, source="source_health"),
        "market_context:": SignalDataHubPolicy(ttl_seconds=60.0, allow_stale=True, source="market_context"),
    }

    def __init__(self, policies: dict[str, SignalDataHubPolicy] | None = None) -> None:
        self._lock = RLock()
        self._cache: dict[str, SignalDataHubRecord] = {}
        self._inflight: set[str] = set()
        self._policies = dict(self.DEFAULT_POLICIES)
        if policies:
            self._policies.update(policies)
        self._stats: dict[str, int] = defaultdict(int)
        self._source_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    @staticmethod
    def normalize_component(value: Any) -> str:
        text = str(value or "unknown").strip().lower()
        normalized = []
        for char in text:
            normalized.append(char if char.isalnum() else "_")
        return "_".join(part for part in "".join(normalized).split("_") if part) or "unknown"

    @classmethod
    def make_topic(cls, domain: str, key: Any, *parts: Any) -> str:
        components = [cls.normalize_component(domain), cls.normalize_component(key)]
        components.extend(cls.normalize_component(part) for part in parts if part is not None)
        return ":".join(components)

    def configure_policy(self, prefix: str, policy: SignalDataHubPolicy) -> None:
        with self._lock:
            self._policies[str(prefix)] = policy

    def _policy_for(
        self,
        topic: str,
        *,
        ttl_seconds: float | None = None,
        allow_stale: bool | None = None,
        source: str | None = None,
    ) -> SignalDataHubPolicy:
        matched = SignalDataHubPolicy()
        for prefix, policy in sorted(self._policies.items(), key=lambda item: len(item[0]), reverse=True):
            if topic.startswith(prefix):
                matched = policy
                break
        return SignalDataHubPolicy(
            ttl_seconds=float(ttl_seconds if ttl_seconds is not None else matched.ttl_seconds),
            allow_stale=bool(allow_stale if allow_stale is not None else matched.allow_stale),
            source=str(source or matched.source),
        )

    @staticmethod
    def _domain_for(topic: str) -> str:
        return topic.split(":", 1)[0] if ":" in topic else "unknown"

    def _count_source(self, source: str, metric: str) -> None:
        self._source_stats[source][metric] += 1

    def set(
        self,
        topic: str,
        value: Any,
        *,
        source: str | None = None,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SignalDataHubRecord:
        normalized_topic = str(topic)
        policy = self._policy_for(normalized_topic, ttl_seconds=ttl_seconds, source=source)
        now = time()
        record = SignalDataHubRecord(
            topic=normalized_topic,
            value=value,
            source=policy.source,
            created_at=now,
            expires_at=now + max(0.0, policy.ttl_seconds),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._cache[normalized_topic] = record
            self._stats["writes"] += 1
            self._count_source(policy.source, "writes")
        return record

    def get(self, topic: str, *, allow_stale: bool | None = None) -> SignalDataHubRecord | None:
        normalized_topic = str(topic)
        with self._lock:
            record = self._cache.get(normalized_topic)
            if record is None:
                self._stats["cache_misses"] += 1
                return None
            policy = self._policy_for(normalized_topic, allow_stale=allow_stale)
            if record.is_stale() and not policy.allow_stale:
                self._stats["cache_misses"] += 1
                self._count_source(record.source, "misses")
                return None
            if record.is_stale():
                self._stats["stale_hits"] += 1
                self._count_source(record.source, "stale_hits")
            else:
                self._stats["cache_hits"] += 1
                self._count_source(record.source, "hits")
            return record

    def get_or_produce(
        self,
        topic: str,
        producer: Callable[[], Any],
        *,
        source: str | None = None,
        ttl_seconds: float | None = None,
        allow_stale: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SignalDataHubRecord | None:
        cached = self.get(topic, allow_stale=allow_stale)
        if cached is not None and not cached.is_stale():
            return cached

        normalized_topic = str(topic)
        with self._lock:
            if normalized_topic in self._inflight:
                self._stats["coalesced_hits"] += 1
                if cached is not None:
                    return cached
                return None
            self._inflight.add(normalized_topic)
            self._stats["producer_calls"] += 1
        try:
            value = producer()
        except Exception:
            with self._lock:
                self._stats["producer_errors"] += 1
            raise
        finally:
            with self._lock:
                self._inflight.discard(normalized_topic)
        return self.set(normalized_topic, value, source=source, ttl_seconds=ttl_seconds, metadata=metadata)

    def record_feature_bundle(
        self,
        *,
        ticker: str,
        feature_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        summary = feature_bundle.get("source_health_summary") if isinstance(feature_bundle, dict) else {}
        source_items = summary.get("sources", []) if isinstance(summary, dict) else []
        feature_topic = self.make_topic("feature_bundle", ticker)
        metadata = {
            "ticker": str(ticker).upper(),
            "canonical_present": bool(feature_bundle.get("canonical_present")) if isinstance(feature_bundle, dict) else False,
            "coverage_pct": feature_bundle.get("coverage_pct") if isinstance(feature_bundle, dict) else 0.0,
            "source_count": int(summary.get("total_sources", 0)) if isinstance(summary, dict) else 0,
            "stale_source_count": int(summary.get("stale_count", 0)) if isinstance(summary, dict) else 0,
        }
        self.set(
            feature_topic,
            feature_bundle,
            source="canonical_bundle" if metadata["canonical_present"] else "runtime_feature_bundle",
            ttl_seconds=120.0,
            metadata=metadata,
        )

        source_topics: list[str] = []
        for item in source_items:
            source_name = str(item.get("source") or "unknown")
            source_topic = self.make_topic("source_health", source_name)
            source_topics.append(source_topic)
            self.set(
                source_topic,
                dict(item),
                source=source_name,
                ttl_seconds=300.0,
                metadata={
                    "ticker": str(ticker).upper(),
                    "status": item.get("status"),
                    "stale": bool(item.get("stale")),
                    "freshness_seconds": item.get("freshness_seconds"),
                },
            )

        return {
            "feature_bundle_topic": feature_topic,
            "source_health_topics": source_topics,
            "source_count": metadata["source_count"],
            "stale_source_count": metadata["stale_source_count"],
        }

    def snapshot(self) -> dict[str, Any]:
        now = time()
        with self._lock:
            records = list(self._cache.values())
            inflight_count = len(self._inflight)
            stats = dict(self._stats)
            source_stats = {source: dict(values) for source, values in self._source_stats.items()}

        by_domain: dict[str, dict[str, int]] = defaultdict(lambda: {"topics": 0, "fresh": 0, "stale": 0})
        fresh_topics = 0
        stale_topics = 0
        for record in records:
            stale = record.is_stale(now)
            domain = self._domain_for(record.topic)
            by_domain[domain]["topics"] += 1
            if stale:
                stale_topics += 1
                by_domain[domain]["stale"] += 1
            else:
                fresh_topics += 1
                by_domain[domain]["fresh"] += 1

        cache_hits = int(stats.get("cache_hits", 0))
        stale_hits = int(stats.get("stale_hits", 0))
        cache_misses = int(stats.get("cache_misses", 0))
        total_cache_requests = max(1, cache_hits + stale_hits + cache_misses)
        coalesced_hits = int(stats.get("coalesced_hits", 0))
        producer_calls = int(stats.get("producer_calls", 0))
        total_topics = len(records)

        return {
            "total_topics": total_topics,
            "fresh_topics": fresh_topics,
            "stale_topics": stale_topics,
            "inflight_topics": inflight_count,
            "writes": int(stats.get("writes", 0)),
            "cache_hits": cache_hits,
            "stale_hits": stale_hits,
            "cache_misses": cache_misses,
            "producer_calls": producer_calls,
            "producer_errors": int(stats.get("producer_errors", 0)),
            "coalesced_hits": coalesced_hits,
            "cache_hit_rate": round((cache_hits + stale_hits) / total_cache_requests, 4),
            "stale_topic_rate": round(stale_topics / max(1, total_topics), 4),
            "coalesced_hit_rate": round(coalesced_hits / max(1, producer_calls + coalesced_hits), 4),
            "by_domain": {domain: dict(values) for domain, values in sorted(by_domain.items())},
            "by_source": {source: dict(values) for source, values in sorted(source_stats.items())},
        }


__all__ = ["SignalDataHub", "SignalDataHubPolicy", "SignalDataHubRecord"]
