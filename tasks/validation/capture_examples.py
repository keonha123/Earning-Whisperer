"""Capture synthetic, real-engine examples without publishing signals or orders."""
from pathlib import Path
import argparse
import json
import logging
import os
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-engine"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from dotenv import dotenv_values
    private = dotenv_values(args.env_file)
    for key in ("GEMINI_API_KEY", "GEMINI_PRIMARY_MODEL", "GEMINI_MODEL_FAST", "GEMINI_REVIEW_MODEL"):
        if private.get(key):
            os.environ[key] = private[key]
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="ew-examples-") as tmp:
        os.environ.update({
            "VECTOR_STORE_BACKEND": "memory", "QDRANT_URL": "", "QDRANT_PATH": tmp + "/vectors",
            "EVIDENCE_POSTGRES_ENABLED": "false", "EVIDENCE_AUTO_BOOTSTRAP": "false",
            "PHASE1_PROVIDER": "heuristic", "PHASE1_WARMUP_ON_STARTUP": "false",
            "LEGACY_REDIS_PUBLISH_ENABLED": "false", "REDIS_ENRICHED_PUBLISH_ENABLED": "false",
            "REDIS_PROFILE_PUBLISH_ENABLED": "false", "LIVE_SESSION_REDIS_PUBLISH_ENABLED": "false",
            "EVIDENCE_SYNC_ENABLED": "false", "RUNTIME_CONTROLS_MODE": "required",
            "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:15439/unused",
            "COMPANY_INTELLIGENCE_STORE_PATH": tmp + "/companies.json",
            "LIVE_SESSION_STORE_PATH": tmp + "/sessions", "REDIS_RETRY_SPOOL_PATH": tmp + "/retry.jsonl",
        })
        from fastapi.testclient import TestClient
        from main import create_app
        fixture = "Revenue increased 20% because customer demand improved. Operating margin increased to 20%."
        now = int(time.time())
        evidence = {"document_id": "synthetic-release", "ticker": "SMOKE", "source_type": "EARNINGS_RELEASE",
                    "source": "Synthetic verification fixture", "title": "Synthetic earnings release",
                    "published_at": "2026-09-30", "content": fixture, "reliability_score": 0.95}
        result = {"fixture": "SYNTHETIC_NOT_INVESTMENT_ADVICE", "broker_execution": "not_called",
                  "runtime_controls": "required; isolated unavailable DB intentionally blocks execution",
                  "limitations": ["In-memory evidence and heuristic phase1", "No market or broker calls", "Provider variability remains"],
                  "checks": {}}
        def capture(client, name, method, route, payload=None):
            started = time.monotonic()
            try:
                response = client.request(method, route, json=payload)
                body = response.json()
                result["checks"][name] = {"status_code": response.status_code, "elapsed_seconds": round(time.monotonic()-started, 3), "response": body}
                return body
            except Exception as exc:
                result["checks"][name] = {"error_type": type(exc).__name__, "elapsed_seconds": round(time.monotonic()-started, 3)}
                return {}
        with TestClient(create_app()) as client:
            capture(client, "liveness", "GET", "/health/live")
            capture(client, "report", "POST", "/v1/engine/earnings/intelligence", {
                "ticker": "SMOKE", "event_text": fixture, "external_documents": [{"doc_id": "synthetic-release", "ticker": "SMOKE",
                "text": fixture, "source_type": "earnings_release", "published_at": now-60, "title": "Synthetic earnings release"}],
                "market_data": {"ticker": "SMOKE", "current_price": 100, "volume_ratio": 2, "gap_pct": 2}})
            capture(client, "legacy_analysis", "POST", "/api/v1/analyze", {
                "ticker": "SMOKE", "text_chunk": fixture, "timestamp": now, "sequence": 0, "is_final": True,
                "market_data": {"ticker": "SMOKE", "current_price": 100, "volume_ratio": 2, "gap_pct": 2},
                "route_profile": "economy"})
            state = capture(client, "session_start", "POST", "/v1/engine/live-sessions", {
                "ticker": "SMOKE", "call_title": "Synthetic verification", "expected_fact_count": 2,
                "execution_mode": "MANUAL", "publish_final_signal": False,
                "market_data": {"ticker": "SMOKE", "current_price": 100, "volume_ratio": 2}})
            if state.get("session_id"):
                capture(client, "final_signal", "POST", "/v1/engine/live-sessions/"+state["session_id"]+"/chunks", {
                    "text": fixture, "sequence": 0, "is_final": True, "route_profile": "economy", "evidence_documents": [evidence]})
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({name: {k:v for k,v in check.items() if k != "response"} for name,check in result["checks"].items()}))

if __name__ == "__main__":
    main()
