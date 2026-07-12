from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

try:
    from models.evidence_models import EvidenceDocument, EvidenceSourceType
    from models.ingestion_models import EarningsTranscriptIngestItem, EarningsTranscriptIngestResponse
except ImportError:  # pragma: no cover
    from ..models.evidence_models import EvidenceDocument, EvidenceSourceType
    from ..models.ingestion_models import EarningsTranscriptIngestItem, EarningsTranscriptIngestResponse


class TranscriptIngestionService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def ingest(self, items: Iterable[EarningsTranscriptIngestItem]) -> EarningsTranscriptIngestResponse:
        documents: list[EvidenceDocument] = []
        warnings: list[str] = []
        skipped = 0
        document_ids: list[str] = []
        for item in items:
            content = " ".join(str(item.content or "").split())
            if not content:
                skipped += 1
                warnings.append(f"empty_content:{item.ticker}:{item.provider_id}")
                continue
            document_id = f"{item.provider}:{item.ticker}:{item.provider_id}"
            document_ids.append(document_id)
            metadata = {
                **dict(item.metadata or {}),
                "provider": item.provider,
                "provider_id": item.provider_id,
                "fiscal_quarter": item.fiscal_quarter,
                "speaker_turn_count": len(item.speaker_turns),
                "speaker_turns": [turn.model_dump(mode="json") for turn in item.speaker_turns[:80]],
            }
            documents.append(
                EvidenceDocument(
                    document_id=document_id,
                    ticker=item.ticker,
                    source_type=EvidenceSourceType.EARNINGS_CALL,
                    source=item.provider,
                    title=item.title,
                    published_at=_published_at(item.published_at),
                    content=content,
                    reliability_score=0.88,
                    metadata=metadata,
                )
            )
        accepted = 0
        if documents:
            accepted = self.repository.add_documents(documents)
        return EarningsTranscriptIngestResponse(
            status="ok" if accepted or skipped else "skipped",
            accepted_count=accepted,
            skipped_count=skipped,
            document_ids=document_ids,
            warnings=warnings,
        )


def _published_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    return None


__all__ = ["TranscriptIngestionService"]
