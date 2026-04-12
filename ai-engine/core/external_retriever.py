"""External evidence retrieval helpers with a pluggable in-memory fallback."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Sequence

from config import get_settings

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
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
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(frozen=True)
class ExternalDocument:
    """Normalized document shape used by the external retriever."""

    doc_id: str
    ticker: str
    text: str
    title: str = ""
    published_at: int = 0
    source_type: str = "news"
    url: str = ""
    form_type: str = ""
    importance: float = 0.5
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalRetrievedDocument:
    """Prompt-ready evidence document returned from retrieval."""

    doc_id: str
    text: str
    score: float
    title: str = ""
    published_at: int = 0
    source_type: str = "news"
    url: str = ""
    form_type: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


class ExternalRetriever:
    """Minimal retriever with an in-memory corpus and vector-DB-compatible API."""

    def __init__(self) -> None:
        self._documents: dict[str, ExternalDocument] = {}

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        for document in documents:
            self._documents[document.doc_id] = document

    def clear(self) -> None:
        self._documents.clear()

    def retrieve(
        self,
        *,
        query: str,
        ticker: str,
        chunk_timestamp: int,
        preferred_sources: Sequence[str] | None = None,
        lookback_days: int = 7,
        limit: int | None = None,
    ) -> list[ExternalRetrievedDocument]:
        settings = get_settings()
        top_k = limit or settings.rag_top_k
        if not query.strip() or not ticker.strip():
            return []

        lower_sources = {str(source).strip().lower() for source in (preferred_sources or []) if source}
        query_tokens = _significant_tokens(query)
        if not query_tokens:
            return []

        window_seconds = max(1, lookback_days) * 86400
        lower_bound = max(0, int(chunk_timestamp) - window_seconds)

        scored: list[ExternalRetrievedDocument] = []
        for document in self._documents.values():
            if document.ticker.upper() != ticker.upper():
                continue
            if document.published_at and chunk_timestamp and document.published_at > chunk_timestamp:
                continue
            if document.published_at and document.published_at < lower_bound:
                continue
            if lower_sources and document.source_type.lower() not in lower_sources:
                continue

            score = _score_document(
                query=query,
                query_tokens=query_tokens,
                document=document,
                chunk_timestamp=chunk_timestamp,
                lookback_days=max(1, lookback_days),
            )
            if score < settings.rag_min_relevance_score:
                continue

            scored.append(
                ExternalRetrievedDocument(
                    doc_id=document.doc_id,
                    text=document.text,
                    score=round(score, 4),
                    title=document.title,
                    published_at=document.published_at,
                    source_type=document.source_type,
                    url=document.url,
                    form_type=document.form_type,
                    metadata=dict(document.metadata),
                )
            )

        scored.sort(key=lambda doc: (-doc.score, -doc.published_at, doc.doc_id))
        return scored[:top_k]


def _score_document(
    *,
    query: str,
    query_tokens: set[str],
    document: ExternalDocument,
    chunk_timestamp: int,
    lookback_days: int,
) -> float:
    doc_text = " ".join(part for part in (document.title, document.text) if part)
    doc_tokens = _significant_tokens(doc_text)
    if not doc_tokens:
        return 0.0

    overlap = query_tokens & doc_tokens
    if not overlap:
        return 0.0

    coverage = len(overlap) / max(len(query_tokens), 1)
    phrase_bonus = 0.15 if _contains_phrase_overlap(query, doc_text) else 0.0
    importance_bonus = 0.10 * max(0.0, min(document.importance, 1.0))
    source_bonus = 0.08 if document.source_type.lower() == "filing" else 0.03
    recency_bonus = _recency_bonus(
        published_at=document.published_at,
        chunk_timestamp=chunk_timestamp,
        lookback_days=lookback_days,
    )

    return min(1.0, (0.62 * coverage) + phrase_bonus + importance_bonus + source_bonus + recency_bonus)


def _contains_phrase_overlap(query: str, text: str) -> bool:
    query_lower = f" {query.lower()} "
    text_lower = f" {text.lower()} "
    words = [token for token in _TOKEN_RE.findall(query.lower()) if token not in _STOPWORDS]
    if len(words) < 2:
        return False
    for idx in range(len(words) - 1):
        phrase = f" {words[idx]} {words[idx + 1]} "
        if phrase in query_lower and phrase in text_lower:
            return True
    return False


def _recency_bonus(*, published_at: int, chunk_timestamp: int, lookback_days: int) -> float:
    if not published_at or not chunk_timestamp or published_at > chunk_timestamp:
        return 0.0

    age_seconds = max(0, chunk_timestamp - published_at)
    max_age_seconds = max(1, lookback_days * 86400)
    freshness = 1.0 - min(age_seconds / max_age_seconds, 1.0)
    return 0.12 * math.sqrt(freshness)


def _significant_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    }


external_retriever = ExternalRetriever()

