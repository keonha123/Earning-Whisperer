"""Rebuild transcripts from original source JSON into a NEW local Qdrant collection.

Preview is the default. This command never edits an existing collection or connects
to QDRANT_URL. Real embeddings require an explicitly selected provider and its key.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Settings
from models.ingestion_models import EarningsTranscriptIngestItem
from repositories.qdrant_evidence_repository import QdrantEvidenceRepository, _document_chunk_entries
from services.transcript_ingestion_service import TranscriptIngestionService


def load_items(path: Path, *, ticker=None, published_at=None, fiscal_quarter=None):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and "turns" in payload:
        if not ticker or not published_at or not fiscal_quarter:
            raise ValueError("FactSet JSON requires --ticker, --published-at and --fiscal-quarter")
        timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("--published-at requires a timezone")
        turns = payload["turns"]
        payload = [{"provider": "factset", "provider_id": path.stem, "ticker": ticker,
            "title": f"{ticker} {fiscal_quarter} earnings call", "published_at": timestamp,
            "fiscal_quarter": fiscal_quarter, "speaker_turns": turns,
            "content": " ".join(str(turn.get("text", "")) for turn in turns),
            "metadata": {"source_url": payload.get("source", {}).get("url")}}]
    elif isinstance(payload, dict):
        payload = payload.get("items", [payload])
    items = [EarningsTranscriptIngestItem.model_validate(item) for item in payload]
    identities = {(item.provider, item.ticker, item.provider_id) for item in items}
    if not items or len(identities) != len(items):
        raise ValueError("Input must contain unique, non-empty transcript documents")
    return items


class _Capture:
    def add_documents(self, documents):
        self.documents = documents
        return len(documents)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--path", type=Path, required=True, help="Local Qdrant directory; no server URL")
    parser.add_argument("--collection", required=True, help="Must not already exist")
    parser.add_argument("--provider", choices=["hash", "gemini", "openai"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--ticker")
    parser.add_argument("--published-at")
    parser.add_argument("--fiscal-quarter")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.dimension < 32:
        parser.error("dimension must be >= 32")
    items = load_items(args.input, ticker=args.ticker, published_at=args.published_at, fiscal_quarter=args.fiscal_quarter)
    settings = Settings(QDRANT_URL="", QDRANT_PATH=str(args.path.resolve()),
        EMBEDDING_PROVIDER=args.provider, EMBEDDING_MODEL=args.model,
        EMBEDDING_DIMENSION=args.dimension, EMBEDDING_VERSION=args.version)
    capture = _Capture()
    TranscriptIngestionService(capture).ingest(items)
    chunk_count = sum(len(_document_chunk_entries(doc, max_chars=settings.transcript_chunk_size_chars,
        overlap_chars=settings.transcript_chunk_overlap_chars)) for doc in capture.documents)
    summary = {"mode": "apply" if args.apply else "preview", "documents": len(items),
        "speaker_turns": sum(len(item.speaker_turns) for item in items), "chunks": chunk_count,
        "provider": args.provider, "model": args.model, "dimension": args.dimension,
        "embedding_version": args.version, "destination": str(args.path.resolve()), "collection": args.collection}
    if args.apply:
        from qdrant_client import QdrantClient
        client = QdrantClient(path=str(args.path.resolve()))
        try:
            if client.collection_exists(args.collection):
                raise ValueError("Destination collection exists; choose a NEW collection (no data was modified)")
            repository = QdrantEvidenceRepository.from_settings(settings=settings, client=client,
                collection_name=args.collection, store_name="transcript", embedding_scope="transcript")
            result = TranscriptIngestionService(repository).ingest(items)
            stored_count = client.count(collection_name=args.collection).count
            if result.accepted_count != len(items) or stored_count != chunk_count:
                raise RuntimeError("Reindex verification failed; do not activate destination collection")
            summary.update(verified_chunks=stored_count, accepted_documents=result.accepted_count)
        finally:
            client.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
