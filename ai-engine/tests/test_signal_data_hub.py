from __future__ import annotations

from core.signal_data_hub import SignalDataHub


def test_signal_data_hub_records_feature_bundle_and_source_health() -> None:
    hub = SignalDataHub()

    receipt = hub.record_feature_bundle(
        ticker="NVDA",
        feature_bundle={
            "canonical_present": True,
            "coverage_pct": 71.43,
            "source_health_summary": {
                "total_sources": 2,
                "stale_count": 1,
                "sources": [
                    {"source": "benzinga_transcripts", "status": "HEALTHY", "freshness_seconds": 45.0, "stale": False},
                    {"source": "x_posts", "status": "DEGRADED", "freshness_seconds": 5400.0, "stale": True},
                ],
            },
        },
    )

    assert receipt["feature_bundle_topic"] == "feature_bundle:nvda"
    assert receipt["source_health_topics"] == ["source_health:benzinga_transcripts", "source_health:x_posts"]

    snapshot = hub.snapshot()
    assert snapshot["total_topics"] == 3
    assert snapshot["fresh_topics"] == 3
    assert snapshot["by_domain"]["feature_bundle"]["topics"] == 1
    assert snapshot["by_domain"]["source_health"]["topics"] == 2
    assert snapshot["by_source"]["canonical_bundle"]["writes"] == 1
    assert snapshot["by_source"]["benzinga_transcripts"]["writes"] == 1


def test_signal_data_hub_ttl_and_stale_handling() -> None:
    hub = SignalDataHub()
    hub.set("market_context:spy", {"price": 500.0}, source="market", ttl_seconds=0.0)

    assert hub.get("market_context:spy", allow_stale=False) is None
    stale_record = hub.get("market_context:spy", allow_stale=True)

    assert stale_record is not None
    assert stale_record.value == {"price": 500.0}

    snapshot = hub.snapshot()
    assert snapshot["stale_topics"] == 1
    assert snapshot["cache_misses"] == 1
    assert snapshot["stale_hits"] == 1
    assert snapshot["stale_topic_rate"] == 1.0


def test_signal_data_hub_get_or_produce_reuses_fresh_cache() -> None:
    hub = SignalDataHub()
    calls = 0

    def producer() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = hub.get_or_produce("feature_bundle:msft", producer, source="unit", ttl_seconds=60.0)
    second = hub.get_or_produce("feature_bundle:msft", producer, source="unit", ttl_seconds=60.0)

    assert first is not None
    assert second is not None
    assert first.value == {"value": 1}
    assert second.value == {"value": 1}
    assert calls == 1

    snapshot = hub.snapshot()
    assert snapshot["producer_calls"] == 1
    assert snapshot["cache_hits"] == 1
    assert snapshot["cache_hit_rate"] == 0.5


def test_signal_data_hub_coalesces_inflight_producers() -> None:
    hub = SignalDataHub()
    nested_result = []

    def producer() -> str:
        nested_result.append(hub.get_or_produce("feature_bundle:meta", lambda: "nested", source="unit"))
        return "outer"

    record = hub.get_or_produce("feature_bundle:meta", producer, source="unit", ttl_seconds=60.0)

    assert record is not None
    assert record.value == "outer"
    assert nested_result == [None]
    assert hub.snapshot()["coalesced_hits"] == 1
