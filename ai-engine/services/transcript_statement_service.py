"""직전 콜 적재 후 핵심 문장 추출 · 저장.

트랜스크립트 적재 엔드포인트가 기존 적재(`TranscriptIngestionService`)를 마친 뒤 이어서
부른다. 여기서 실패해도 기존 적재 결과는 그대로 두고 경고만 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Iterable

try:
    from models.ingestion_models import EarningsTranscriptIngestItem, TranscriptSpeakerTurn
    from models.transcript_statement_models import KeyStatement
    from services.transcript_statement_extraction_service import TranscriptStatementExtractionService
except ImportError:  # pragma: no cover
    from ..models.ingestion_models import EarningsTranscriptIngestItem, TranscriptSpeakerTurn
    from ..models.transcript_statement_models import KeyStatement
    from .transcript_statement_extraction_service import TranscriptStatementExtractionService


logger = logging.getLogger(__name__)


@dataclass
class StatementIngestResult:
    #: document_id → 저장한 문장 수
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class TranscriptStatementService:
    def __init__(self, *, extractor: TranscriptStatementExtractionService, repository) -> None:
        self.extractor = extractor
        self.repository = repository

    async def ingest(self, items: Iterable[EarningsTranscriptIngestItem]) -> StatementIngestResult:
        result = StatementIngestResult()
        for item in items:
            # TranscriptIngestionService 와 같은 규칙. 둘이 다르면 대조가 문장을 찾지 못한다.
            document_id = f"{item.provider}:{item.ticker}:{item.provider_id}"
            if not " ".join(str(item.content or "").split()):
                # TranscriptIngestionService 가 건너뛰는 항목이다. 여기서 저장하면 짝이 없는 문장이 남는다.
                continue
            turns = _turns(item)
            if not turns:
                continue
            try:
                extracted = await self.extractor.extract(
                    document_id=document_id,
                    ticker=item.ticker,
                    turns=turns,
                    published_at_epoch=_epoch(item.published_at),
                    fiscal_quarter=item.fiscal_quarter,
                )
            except Exception:
                logger.exception("핵심 문장 추출 실패 - document_id=%s", document_id)
                result.warnings.append(f"key_statement_extraction_failed:{document_id}")
                continue
            result.warnings.extend(f"{warning}:{document_id}" for warning in extracted.warnings)
            batch_failed = any(warning.startswith("key_statement_batch_") for warning in extracted.warnings)
            try:
                if (batch_failed or not extracted.statements) and self.repository.list(document_id):
                    # 일부 배치가 실패했거나 한 문장도 못 건졌다. 이대로 바꾸면 이전에 온전히 들어가
                    # 있던 문장을 잃는다. 이전 문장이 없을 때만 일부라도 저장한다.
                    reason = "batch_failed" if batch_failed else "empty"
                    result.warnings.append(f"key_statements_kept_previous:{reason}:{document_id}")
                    continue
                result.counts[document_id] = self.repository.replace(document_id, extracted.statements)
            except Exception:
                logger.exception("핵심 문장 조회 · 저장 실패 - document_id=%s", document_id)
                result.warnings.append(f"key_statement_store_failed:{document_id}")
                continue
            if extracted.rejected_count:
                result.warnings.append(f"key_statements_not_in_transcript:{document_id}:{extracted.rejected_count}")
            logger.info(
                "핵심 문장 저장 - document_id=%s statements=%s rejected=%s",
                document_id,
                result.counts[document_id],
                extracted.rejected_count,
            )
        return result

    def list(self, document_id: str) -> list[KeyStatement]:
        return self.repository.list(document_id)


def _turns(item: EarningsTranscriptIngestItem) -> list[TranscriptSpeakerTurn]:
    if item.speaker_turns:
        return list(item.speaker_turns)
    content = " ".join(str(item.content or "").split())
    return [TranscriptSpeakerTurn(speaker="", text=content)] if content else []


def _epoch(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int((value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    return None


__all__ = ["StatementIngestResult", "TranscriptStatementService"]
