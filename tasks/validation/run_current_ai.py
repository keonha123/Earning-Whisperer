"""Isolated current-checkout AI HTTP runtime for integration verification."""
import argparse
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--port", type=int, default=19000)
    args = parser.parse_args()
    from dotenv import dotenv_values
    private = dotenv_values(args.env_file)
    for name in ("GEMINI_API_KEY", "GEMINI_PRIMARY_MODEL", "GEMINI_MODEL_FAST", "GEMINI_REVIEW_MODEL"):
        if private.get(name):
            os.environ[name] = private[name]
    with tempfile.TemporaryDirectory(prefix="ew-current-http-") as tmp:
        os.environ.update({
            "VECTOR_STORE_BACKEND": "memory", "EMBEDDING_PROVIDER": "hash",
            "EXTERNAL_EMBEDDING_PROVIDER": "hash", "EMBEDDING_DIMENSION": "256",
            "EXTERNAL_EMBEDDING_DIMENSION": "256", "QDRANT_URL": "", "QDRANT_PATH": tmp + "/vectors",
            "EVIDENCE_POSTGRES_ENABLED": "false", "EVIDENCE_AUTO_BOOTSTRAP": "false",
            "PHASE1_PROVIDER": "heuristic", "PHASE1_WARMUP_ON_STARTUP": "false",
            "LEGACY_REDIS_PUBLISH_ENABLED": "false", "REDIS_ENRICHED_PUBLISH_ENABLED": "false",
            "REDIS_PROFILE_PUBLISH_ENABLED": "false", "LIVE_SESSION_REDIS_PUBLISH_ENABLED": "false",
            "EVIDENCE_SYNC_ENABLED": "false", "RUNTIME_CONTROLS_MODE": "required",
            "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:15439/unused",
            "COMPANY_INTELLIGENCE_STORE_PATH": tmp + "/companies.json",
            "LIVE_SESSION_STORE_PATH": tmp + "/sessions", "REDIS_RETRY_SPOOL_PATH": tmp + "/retry.jsonl",
        })
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ai-engine"))
        import uvicorn
        uvicorn.run("main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
