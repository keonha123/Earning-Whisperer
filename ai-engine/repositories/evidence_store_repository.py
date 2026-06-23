from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from models.evidence_models import (
        EvidenceBackend,
        EvidenceCitation,
        EvidenceDocument,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        EvidenceSourceType,
    )
    from db.postgres_executor import SQLExecutor
except ImportError:  # pragma: no cover
    from ..models.evidence_models import (
        EvidenceBackend,
        EvidenceCitation,
        EvidenceDocument,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        EvidenceSourceType,
    )
    from ..db.postgres_executor import SQLExecutor


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "we",
    "with",
}

_SOURCE_PRIORS = {
    EvidenceSourceType.FILING: 0.94,
    EvidenceSourceType.EARNINGS_RELEASE: 0.91,
    EvidenceSourceType.EARNINGS_CALL: 0.88,
    EvidenceSourceType.PRESENTATION: 0.84,
    EvidenceSourceType.MARKET_DATA: 0.82,
    EvidenceSourceType.HISTORICAL_GUIDANCE: 0.80,
    EvidenceSourceType.SUPPLY_CHAIN: 0.74,
    EvidenceSourceType.ANALYST_NOTE: 0.72,
    EvidenceSourceType.NEWS: 0.70,
    EvidenceSourceType.OTHER: 0.58,
}


def _clip(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _tokenize(text: str) -> set[str]:
    tokens = set()
    for raw in re.findall(r"[a-z0-9][a-z0-9._%-]{1,}", (text or "").lower()):
        token = raw.strip("._%-")
        if token and token not in _STOPWORDS:
            tokens.add(token)
    return tokens


def _published_at_key(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return None


def _published_at_text(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _document_id(document: EvidenceDocument) -> str:
    if document.document_id:
        return document.document_id
    seed = "|".join(
        [
            str(document.ticker or ""),
            str(document.source_type.value),
            str(document.source),
            str(document.title or ""),
            str(document.published_at or ""),
            document.content[:400],
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _best_snippet(content: str, query_tokens: set[str], limit: int = 320) -> str:
    normalized = " ".join((content or "").split())
    if not normalized:
        return ""
    candidates = [item.strip() for item in re.split(r"(?<=[.!?])\s+", normalized) if item.strip()]
    if not candidates:
        return _clip(normalized, limit)
    best = max(candidates, key=lambda item: len(_tokenize(item) & query_tokens))
    if len(_tokenize(best) & query_tokens) == 0:
        best = normalized
    return _clip(best, limit)


class EvidenceStoreRepository:
    """pgvector-ready repository contract with deterministic local sparse retrieval.

    The production backend can persist embeddings in pgvector. The local fallback keeps
    tests and offline runs deterministic without pulling FAISS/Qdrant dependencies.
    """

    def __init__(
        self,
        *,
        backend: EvidenceBackend = EvidenceBackend.LOCAL_SPARSE,
        documents: Iterable[EvidenceDocument] | None = None,
        executor: SQLExecutor | None = None,
        schema_path: str | Path | None = None,
    ) -> None:
        self.backend = backend
        self.executor = executor
        self.schema_path = Path(schema_path) if schema_path else None
        self._documents: dict[str, EvidenceDocument] = {}
        self._last_persistence_warning = ""
        self.add_documents(list(documents or []))

    def bootstrap_schema(self) -> bool:
        if self.executor is None or self.schema_path is None:
            return False
        self.executor.execute_script(self.schema_path.read_text(encoding="utf-8"))
        return True

    def add_documents(self, documents: Iterable[EvidenceDocument]) -> int:
        added = 0
        accepted: list[EvidenceDocument] = []
        for document in documents:
            if not document.content.strip():
                continue
            doc_id = _document_id(document)
            payload = document.model_copy(update={"document_id": doc_id})
            self._documents[doc_id] = payload
            accepted.append(payload)
            added += 1
        self._persist_documents(accepted)
        return added

    def search(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        scoped_documents = list(self._documents.values())
        seen = {item.document_id for item in scoped_documents}
        for document in self._load_persistent_documents(request):
            doc_id = _document_id(document)
            if doc_id not in seen:
                scoped_documents.append(document.model_copy(update={"document_id": doc_id}))
                seen.add(doc_id)
        if request.documents:
            for document in request.documents:
                doc_id = _document_id(document)
                if doc_id not in seen and document.content.strip():
                    scoped_documents.append(document.model_copy(update={"document_id": doc_id}))
                    seen.add(doc_id)

        source_filter = set(request.source_types or [])
        query_tokens = _tokenize(f"{request.ticker} {request.query}")
        ticker = (request.ticker or "").upper()
        scored: list[tuple[float, EvidenceDocument]] = []
        for document in scoped_documents:
            if source_filter and document.source_type not in source_filter:
                continue
            score = self._score_document(document, query_tokens=query_tokens, ticker=ticker)
            if score > 0:
                scored.append((score, document))

        scored.sort(key=lambda item: item[0], reverse=True)
        citations = [
            self._to_citation(document, score=score, query_tokens=query_tokens)
            for score, document in scored[: request.top_k]
        ]
        coverage = self._coverage_score(citations)
        confidence_adjustment = self._confidence_adjustment(coverage, citations)
        warnings: list[str] = []
        if not citations:
            warnings.append("no_retrieved_evidence")
        elif coverage < 0.35:
            warnings.append("weak_retrieved_evidence")
        if self._last_persistence_warning:
            warnings.append(self._last_persistence_warning)

        return EvidenceRetrievalResult(
            ticker=ticker or request.ticker,
            query=request.query,
            backend=self.backend,
            evidence=citations,
            coverage_score=coverage,
            confidence_adjustment=confidence_adjustment,
            evidence_context=self.build_prompt_context(citations),
            missing_evidence=not citations,
            warnings=warnings,
        )

    def _persist_documents(self, documents: list[EvidenceDocument]) -> None:
        if self.executor is None or not documents:
            return
        statements = []
        for document in documents:
            statements.append(
                (
                    """
                    insert into ai_evidence_documents
                        (document_id, ticker, source_type, source_name, title, published_at,
                         source_url, content, reliability_score, metadata_json, updated_at)
                    values
                        (%(document_id)s, %(ticker)s, %(source_type)s, %(source_name)s, %(title)s,
                         %(published_at)s, %(source_url)s, %(content)s, %(reliability_score)s,
                         %(metadata_json)s::jsonb, now())
                    on conflict (document_id) do update set
                        ticker = excluded.ticker,
                        source_type = excluded.source_type,
                        source_name = excluded.source_name,
                        title = excluded.title,
                        published_at = excluded.published_at,
                        source_url = excluded.source_url,
                        content = excluded.content,
                        reliability_score = excluded.reliability_score,
                        metadata_json = excluded.metadata_json,
                        updated_at = now()
                    """,
                    {
                        "document_id": document.document_id,
                        "ticker": (document.ticker or "").upper() or None,
                        "source_type": document.source_type.value,
                        "source_name": document.source,
                        "title": document.title,
                        "published_at": document.published_at,
                        "source_url": document.source_url,
                        "content": document.content,
                        "reliability_score": document.reliability_score,
                        "metadata_json": json.dumps(document.metadata, ensure_ascii=False),
                    },
                )
            )
        try:
            self.executor.execute_transaction(statements)
            self._last_persistence_warning = ""
        except Exception as exc:
            self._last_persistence_warning = f"postgres_evidence_fallback:{type(exc).__name__}"

    def _load_persistent_documents(self, request: EvidenceRetrievalRequest) -> list[EvidenceDocument]:
        if self.executor is None:
            return []
        source_types = [item.value for item in request.source_types]
        try:
            rows = self.executor.fetch_all(
                """
                select document_id, ticker, source_type, source_name, title, published_at,
                       source_url, content, reliability_score, metadata_json,
                       ts_rank_cd(
                           to_tsvector('english', coalesce(title, '') || ' ' || content),
                           plainto_tsquery('english', %(query)s)
                       ) as rank
                from ai_evidence_documents
                where (%(ticker)s = '' or ticker = %(ticker)s)
                  and (cardinality(%(source_types)s::text[]) = 0 or source_type = any(%(source_types)s::text[]))
                  and to_tsvector('english', coalesce(title, '') || ' ' || content)
                      @@ plainto_tsquery('english', %(query)s)
                order by rank desc, published_at desc nulls last
                limit %(limit)s
                """,
                {
                    "ticker": request.ticker.upper(),
                    "query": request.query,
                    "source_types": source_types,
                    "limit": max(request.top_k * 4, 20),
                },
            )
            self._last_persistence_warning = ""
        except Exception as exc:
            self._last_persistence_warning = f"postgres_evidence_fallback:{type(exc).__name__}"
            return []
        documents: list[EvidenceDocument] = []
        for row in rows:
            metadata = row.get("metadata_json") or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            try:
                source_type = EvidenceSourceType(str(row.get("source_type") or EvidenceSourceType.OTHER.value))
            except ValueError:
                source_type = EvidenceSourceType.OTHER
            documents.append(
                EvidenceDocument(
                    document_id=str(row.get("document_id") or ""),
                    ticker=row.get("ticker"),
                    source_type=source_type,
                    source=str(row.get("source_name") or "postgres"),
                    title=row.get("title"),
                    published_at=row.get("published_at"),
                    source_url=row.get("source_url"),
                    content=str(row.get("content") or ""),
                    reliability_score=float(row.get("reliability_score") or 0.6),
                    metadata=dict(metadata),
                )
            )
        return documents
    def _score_document(self, document: EvidenceDocument, *, query_tokens: set[str], ticker: str) -> float:
        text = " ".join(
            [
                document.ticker or "",
                document.title or "",
                document.source or "",
                document.content or "",
                " ".join(str(value) for value in document.metadata.values() if isinstance(value, (str, int, float))),
            ]
        )
        doc_tokens = _tokenize(text)
        if not doc_tokens:
            return 0.0
        overlap = query_tokens & doc_tokens
        ticker_match = bool(ticker and (document.ticker or "").upper() == ticker)
        ticker_in_doc = bool(ticker and ticker.lower() in doc_tokens)
        if not overlap and not ticker_match and not ticker_in_doc:
            return 0.0

        lexical = len(overlap) / max(1, len(query_tokens))
        density = len(overlap) / max(1.0, math.sqrt(len(doc_tokens)))
        reliability = _clamp(float(document.reliability_score or _SOURCE_PRIORS.get(document.source_type, 0.6)))
        recency = self._recency_score(document.published_at)
        ticker_boost = 0.12 if ticker_match else 0.06 if ticker_in_doc else 0.0
        source_prior = _SOURCE_PRIORS.get(document.source_type, 0.58)
        score = 0.50 * lexical + 0.22 * density + 0.13 * reliability + 0.08 * source_prior + 0.07 * recency + ticker_boost
        return _clamp(score)

    @staticmethod
    def _recency_score(value: datetime | date | None) -> float:
        published = _published_at_key(value)
        if published is None:
            return 0.35
        age_days = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 86400.0)
        if age_days <= 45:
            return 1.0
        if age_days <= 365:
            return 0.72
        if age_days <= 365 * 3:
            return 0.48
        return 0.28

    @staticmethod
    def _coverage_score(citations: list[EvidenceCitation]) -> float:
        if not citations:
            return 0.0
        top = citations[:5]
        weighted = sum(item.confidence_score for item in top) / max(1, len(top))
        diversity = len({item.source_type for item in top}) / 5.0
        return round(_clamp(0.82 * weighted + 0.18 * diversity), 4)

    @staticmethod
    def _confidence_adjustment(coverage: float, citations: list[EvidenceCitation]) -> float:
        if not citations:
            return -0.16
        if coverage < 0.25:
            return -0.10
        if coverage < 0.45:
            return -0.05
        if coverage >= 0.72:
            return 0.04
        return 0.0

    @staticmethod
    def build_prompt_context(citations: list[EvidenceCitation], *, max_items: int = 5) -> str:
        if not citations:
            return (
                "RAG_EVIDENCE: none retrieved. Treat unsupported directional judgments as low confidence "
                "and state that evidence coverage is missing."
            )
        lines = [
            "RAG_EVIDENCE:",
            "Use only these retrieved items as supporting evidence; include source/date/confidence in reasoning.",
        ]
        for citation in citations[:max_items]:
            date_text = citation.published_at or "unknown-date"
            lines.append(
                f"- {citation.source_type.value} | {citation.source} | {date_text} | "
                f"confidence={citation.confidence_score:.2f} | {citation.snippet}"
            )
        return "\n".join(lines)

    @staticmethod
    def _to_citation(
        document: EvidenceDocument,
        *,
        score: float,
        query_tokens: set[str],
    ) -> EvidenceCitation:
        reliability = _clamp(float(document.reliability_score or _SOURCE_PRIORS.get(document.source_type, 0.6)))
        confidence = _clamp((0.68 * score) + (0.32 * reliability))
        return EvidenceCitation(
            document_id=_document_id(document),
            ticker=document.ticker,
            source_type=document.source_type,
            source=document.source,
            title=document.title,
            published_at=_published_at_text(document.published_at),
            source_url=document.source_url,
            snippet=_best_snippet(document.content, query_tokens=query_tokens),
            relevance_score=round(score, 4),
            reliability_score=round(reliability, 4),
            confidence_score=round(confidence, 4),
            metadata=dict(document.metadata or {}),
        )


__all__ = ["EvidenceStoreRepository"]
