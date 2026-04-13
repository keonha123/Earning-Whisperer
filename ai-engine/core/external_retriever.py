"""External evidence retrieval helpers with pluggable memory and Qdrant backends."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from config import get_settings

logger = logging.getLogger(__name__)

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
_QDRANT_COLLECTION_VECTOR_NAME = "dense"


@dataclass(frozen=True)
class ExternalDocument:
    """Normalized document shape used by external retrieval."""

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


@dataclass
class RetrieverStats:
    """Basic retrieval stats for monitoring."""

    requested_backend: str
    effective_backend: str
    retrieval_count: int = 0
    empty_hits: int = 0
    error_count: int = 0
    upserted_chunks: int = 0
    total_latency_ms: float = 0.0
    last_error: str = ""

    def to_dict(self) -> dict[str, object]:
        retrievals = max(self.retrieval_count, 1)
        return {
            "requested_backend": self.requested_backend,
            "effective_backend": self.effective_backend,
            "retrieval_count": self.retrieval_count,
            "empty_hit_rate": round(self.empty_hits / retrievals, 4),
            "error_count": self.error_count,
            "avg_latency_ms": round(self.total_latency_ms / retrievals, 1),
            "upserted_chunks": self.upserted_chunks,
            "last_error": self.last_error,
        }


class EmbeddingProvider(Protocol):
    """Embedding provider contract used by the vector backend."""

    name: str
    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    """Deterministic local embedding fallback for tests and offline environments."""

    name = "hash"

    def __init__(self, *, dimension: int) -> None:
        self.dimension = max(32, int(dimension))

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in _significant_tokens(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:4], "big") % self.dimension
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[bucket] += sign
            vectors.append(_normalize_vector(vector))
        return vectors


class GeminiEmbeddingProvider:
    """Gemini embedding wrapper used when a live API-backed embedder is configured."""

    name = "gemini"

    def __init__(self, *, model: str, dimension: int) -> None:
        self.model = model
        self.dimension = max(32, int(dimension))
        self._modern_client: Any = None
        self._modern_api_key: str | None = None

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings")

        try:
            from google import genai as modern_genai
        except ImportError:  # pragma: no cover - depends on local environment
            modern_genai = None

        if modern_genai is not None:
            if self._modern_client is None or self._modern_api_key != settings.gemini_api_key:
                self._modern_client = modern_genai.Client(api_key=settings.gemini_api_key)
                self._modern_api_key = settings.gemini_api_key
            response = self._modern_client.models.embed_content(
                model=self.model,
                contents=list(texts),
            )
            raw_embeddings = getattr(response, "embeddings", None)
            if raw_embeddings is None:
                single_embedding = getattr(response, "embedding", None)
                raw_embeddings = [single_embedding] if single_embedding is not None else []
            vectors = [_coerce_embedding_vector(item) for item in raw_embeddings]
            if len(vectors) != len(texts):
                raise RuntimeError("Gemini embedding response size mismatch")
            return [_truncate_or_pad(vector, self.dimension) for vector in vectors]

        try:
            import google.generativeai as legacy_genai
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError("No Gemini embedding SDK is installed") from exc

        legacy_genai.configure(api_key=settings.gemini_api_key)
        vectors: list[list[float]] = []
        for text in texts:
            response = legacy_genai.embed_content(
                model=self.model,
                content=text,
            )
            vectors.append(_truncate_or_pad(_coerce_embedding_vector(response), self.dimension))
        return vectors


class BaseExternalRetriever:
    """Common backend contract."""

    backend_name = "base"

    def __init__(self, *, requested_backend: str, effective_backend: str | None = None) -> None:
        self._stats = RetrieverStats(
            requested_backend=requested_backend,
            effective_backend=effective_backend or self.backend_name,
        )

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

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
        raise NotImplementedError

    def get_stats(self) -> dict[str, object]:
        return self._stats.to_dict()

    def close(self) -> None:
        return None

    def _record_upsert(self, chunk_count: int) -> None:
        self._stats.upserted_chunks += max(0, int(chunk_count))

    def _record_retrieval(
        self,
        *,
        latency_ms: float,
        hit_count: int,
        error: Exception | None = None,
    ) -> None:
        self._stats.retrieval_count += 1
        self._stats.total_latency_ms += max(0.0, latency_ms)
        if hit_count == 0:
            self._stats.empty_hits += 1
        if error is not None:
            self._stats.error_count += 1
            self._stats.last_error = str(error)


class InMemoryExternalRetriever(BaseExternalRetriever):
    """Minimal retriever with an in-memory corpus and vector-DB-compatible API."""

    backend_name = "memory"

    def __init__(self, *, requested_backend: str = "memory") -> None:
        super().__init__(requested_backend=requested_backend, effective_backend=self.backend_name)
        self._documents: dict[str, ExternalDocument] = {}

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        for document in documents:
            self._documents[document.doc_id] = document
        self._record_upsert(len(documents))

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
        start = time.monotonic()
        error: Exception | None = None
        scored: list[ExternalRetrievedDocument] = []
        try:
            settings = get_settings()
            top_k = limit or settings.rag_top_k
            if not query.strip() or not ticker.strip():
                return []

            lower_sources = {
                str(source).strip().lower()
                for source in (preferred_sources or [])
                if source
            }
            query_tokens = _significant_tokens(query)
            if not query_tokens:
                return []

            lower_bound = _lower_bound_timestamp(chunk_timestamp=chunk_timestamp, lookback_days=lookback_days)
            candidate_documents: list[ExternalDocument] = []
            for document in self._documents.values():
                if not _document_matches_filters(
                    document=document,
                    ticker=ticker,
                    chunk_timestamp=chunk_timestamp,
                    lower_bound=lower_bound,
                    preferred_sources=lower_sources,
                ):
                    continue
                candidate_documents.append(document)

            lexical_score_map = _bm25_lexical_scores(
                query=query,
                query_tokens=query_tokens,
                documents=candidate_documents,
            )
            for document in candidate_documents:
                lexical_score = lexical_score_map.get(document.doc_id, 0.0)
                if lexical_score < settings.rag_min_relevance_score:
                    continue

                scored.append(_retrieved_document_from_source(document=document, score=lexical_score))

            scored.sort(key=lambda doc: (-doc.score, -doc.published_at, doc.doc_id))
            return scored[:top_k]
        except Exception as exc:  # pragma: no cover - defensive
            error = exc
            raise
        finally:
            self._record_retrieval(
                latency_ms=(time.monotonic() - start) * 1000,
                hit_count=len(scored),
                error=error,
            )


class QdrantExternalRetriever(BaseExternalRetriever):
    """Hybrid vector retriever backed by Qdrant."""

    backend_name = "qdrant"

    def __init__(
        self,
        *,
        client: Any | None = None,
        embedder: EmbeddingProvider | None = None,
        requested_backend: str = "qdrant",
    ) -> None:
        super().__init__(requested_backend=requested_backend, effective_backend=self.backend_name)
        settings = get_settings()
        self._client = client
        self._embedder = embedder or _build_embedding_provider()
        self._collection_name = settings.qdrant_collection_name
        self._collection_ready = False
        self._dense_candidate_limit = max(settings.rag_top_k * 4, settings.rag_dense_candidate_limit)
        self._keyword_candidate_limit = max(settings.rag_top_k * 8, settings.rag_keyword_candidate_limit)

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        if not documents:
            return
        client = self._get_client()
        self._ensure_collection(client)

        points: list[Any] = []
        for document in documents:
            chunks = _chunk_document(document)
            embeddings = self._embedder.embed_texts([chunk.text for chunk in chunks])
            for chunk, embedding in zip(chunks, embeddings):
                payload = _build_payload(document=chunk, embedding_provider=self._embedder.name)
                points.append(_make_qdrant_point(point_id=chunk.doc_id, vector=embedding, payload=payload))

        if not points:
            return

        client.upsert(collection_name=self._collection_name, points=points)
        self._record_upsert(len(points))

    def clear(self) -> None:
        client = self._client
        if client is None:
            self._collection_ready = False
            return
        if hasattr(client, "delete_collection"):
            try:
                client.delete_collection(collection_name=self._collection_name)
            except TypeError:  # pragma: no cover - client compatibility
                client.delete_collection(self._collection_name)
            except Exception:  # pragma: no cover - defensive
                logger.debug("Qdrant collection clear skipped", exc_info=True)
        self._collection_ready = False

    def close(self) -> None:
        client = self._client
        if client is None:
            return
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # pragma: no cover - defensive
                logger.debug("Qdrant client close skipped", exc_info=True)
        self._client = None
        self._collection_ready = False

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
        start = time.monotonic()
        error: Exception | None = None
        results: list[ExternalRetrievedDocument] = []

        try:
            settings = get_settings()
            top_k = limit or settings.rag_top_k
            if not query.strip() or not ticker.strip():
                return []

            query_tokens = _significant_tokens(query)
            if not query_tokens:
                return []

            lower_sources = {
                str(source).strip().lower()
                for source in (preferred_sources or [])
                if source
            }
            lower_bound = _lower_bound_timestamp(chunk_timestamp=chunk_timestamp, lookback_days=lookback_days)
            client = self._get_client()
            self._ensure_collection(client)
            qdrant_filter = _make_qdrant_filter(
                ticker=ticker,
                chunk_timestamp=chunk_timestamp,
                lower_bound=lower_bound,
                preferred_sources=lower_sources,
            )

            dense_candidates = self._search_dense(
                client=client,
                query=query,
                qdrant_filter=qdrant_filter,
                limit=self._dense_candidate_limit,
            )
            lexical_candidates = self._search_keyword(
                client=client,
                query=query,
                query_tokens=query_tokens,
                qdrant_filter=qdrant_filter,
                chunk_timestamp=chunk_timestamp,
                lookback_days=lookback_days,
                limit=self._keyword_candidate_limit,
            )
            merged = self._merge_candidates(
                dense_candidates=dense_candidates,
                lexical_candidates=lexical_candidates,
                chunk_timestamp=chunk_timestamp,
                lookback_days=lookback_days,
            )
            results = [
                item
                for item in merged
                if item.score >= settings.rag_min_relevance_score
            ][:top_k]
            return results
        except Exception as exc:
            error = exc
            logger.warning("Qdrant retrieval failed: %s", exc)
            return []
        finally:
            self._record_retrieval(
                latency_ms=(time.monotonic() - start) * 1000,
                hit_count=len(results),
                error=error,
            )

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    @staticmethod
    def _build_client() -> Any:
        settings = get_settings()
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError("qdrant-client is not installed") from exc

        if settings.qdrant_path.strip():
            return QdrantClient(
                path=settings.qdrant_path,
                force_disable_check_same_thread=True,
            )
        if not settings.qdrant_url.strip():
            raise RuntimeError("QDRANT_URL or QDRANT_PATH is not configured")

        kwargs = {
            "url": settings.qdrant_url,
            "timeout": settings.qdrant_timeout_seconds,
        }
        if settings.qdrant_api_key:
            kwargs["api_key"] = settings.qdrant_api_key
        if settings.qdrant_prefer_grpc:
            kwargs["prefer_grpc"] = True
        return QdrantClient(**kwargs)

    def _ensure_collection(self, client: Any) -> None:
        if self._collection_ready:
            return

        try:
            client.get_collection(self._collection_name)
        except Exception:
            vector_config = _make_qdrant_vector_config(size=self._embedder.dimension)
            client.create_collection(
                collection_name=self._collection_name,
                vectors_config=vector_config,
            )
        self._collection_ready = True

    def _search_dense(
        self,
        *,
        client: Any,
        query: str,
        qdrant_filter: Any,
        limit: int,
    ) -> list[tuple[ExternalDocument, float]]:
        query_vector = self._embedder.embed_texts([query])[0]
        if hasattr(client, "search"):
            hits = client.search(
                collection_name=self._collection_name,
                query_vector=_wrap_query_vector(query_vector),
                query_filter=qdrant_filter,
                limit=max(1, limit),
                with_payload=True,
            )
        else:
            response = client.query_points(
                collection_name=self._collection_name,
                query=query_vector,
                using=_QDRANT_COLLECTION_VECTOR_NAME,
                query_filter=qdrant_filter,
                limit=max(1, limit),
                with_payload=True,
            )
            hits = getattr(response, "points", None) or getattr(response, "result", None) or []
        dense_candidates: list[tuple[ExternalDocument, float]] = []
        for hit in hits or []:
            payload = _extract_payload(hit)
            if not payload:
                continue
            document = _document_from_payload(payload)
            dense_candidates.append((document, _normalize_dense_score(getattr(hit, "score", 0.0))))
        return dense_candidates

    def _search_keyword(
        self,
        *,
        client: Any,
        query: str,
        query_tokens: set[str],
        qdrant_filter: Any,
        chunk_timestamp: int,
        lookback_days: int,
        limit: int,
    ) -> list[tuple[ExternalDocument, float]]:
        scroll_result = client.scroll(
            collection_name=self._collection_name,
            scroll_filter=qdrant_filter,
            limit=max(1, limit),
            with_payload=True,
        )
        if isinstance(scroll_result, tuple):
            points = scroll_result[0]
        else:  # pragma: no cover - compatibility
            points = scroll_result

        candidate_documents: list[ExternalDocument] = []
        for point in points or []:
            payload = _extract_payload(point)
            if not payload:
                continue
            candidate_documents.append(_document_from_payload(payload))

        lexical_score_map = _bm25_lexical_scores(
            query=query,
            query_tokens=query_tokens,
            documents=candidate_documents,
        )
        lexical_candidates: list[tuple[ExternalDocument, float]] = [
            (document, lexical_score_map.get(document.doc_id, 0.0))
            for document in candidate_documents
            if lexical_score_map.get(document.doc_id, 0.0) > 0.0
        ]
        lexical_candidates.sort(key=lambda item: (-item[1], -item[0].published_at, item[0].doc_id))
        return lexical_candidates[:limit]

    def _merge_candidates(
        self,
        *,
        dense_candidates: Sequence[tuple[ExternalDocument, float]],
        lexical_candidates: Sequence[tuple[ExternalDocument, float]],
        chunk_timestamp: int,
        lookback_days: int,
    ) -> list[ExternalRetrievedDocument]:
        settings = get_settings()
        merged: dict[str, dict[str, Any]] = {}

        for document, score in dense_candidates:
            entry = merged.setdefault(
                document.doc_id,
                {
                    "document": document,
                    "dense_score": 0.0,
                    "lexical_score": 0.0,
                },
            )
            entry["dense_score"] = max(entry["dense_score"], score)

        for document, score in lexical_candidates:
            entry = merged.setdefault(
                document.doc_id,
                {
                    "document": document,
                    "dense_score": 0.0,
                    "lexical_score": 0.0,
                },
            )
            entry["lexical_score"] = max(entry["lexical_score"], score)

        documents: list[ExternalRetrievedDocument] = []
        for entry in merged.values():
            document = entry["document"]
            business_score = _business_signal_score(
                document=document,
                chunk_timestamp=chunk_timestamp,
                lookback_days=max(1, lookback_days),
            )
            hybrid_score = (
                settings.rag_score_dense_weight * entry["dense_score"]
                + settings.rag_score_lexical_weight * entry["lexical_score"]
                + settings.rag_score_business_weight * business_score
            )
            documents.append(_retrieved_document_from_source(document=document, score=min(1.0, hybrid_score)))

        documents.sort(key=lambda doc: (-doc.score, -doc.published_at, doc.doc_id))
        return documents


class ExternalRetrieverFacade:
    """Delegates to the configured backend while preserving the old module-level API."""

    def __init__(self) -> None:
        self._backend: BaseExternalRetriever | None = None
        self._signature: tuple[Any, ...] | None = None
        self._lock = threading.Lock()

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        self._get_backend().upsert_documents(documents)

    def clear(self) -> None:
        self._get_backend().clear()

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
        return self._get_backend().retrieve(
            query=query,
            ticker=ticker,
            chunk_timestamp=chunk_timestamp,
            preferred_sources=preferred_sources,
            lookback_days=lookback_days,
            limit=limit,
        )

    def get_stats(self) -> dict[str, object]:
        return self._get_backend().get_stats()

    def reset_backend(self) -> None:
        with self._lock:
            if self._backend is not None:
                self._backend.close()
            self._backend = None
            self._signature = None

    def _get_backend(self) -> BaseExternalRetriever:
        signature = self._settings_signature()
        with self._lock:
            if self._backend is None or self._signature != signature:
                self._backend = self._build_backend()
                self._signature = signature
            return self._backend

    @staticmethod
    def _settings_signature() -> tuple[Any, ...]:
        settings = get_settings()
        return (
            settings.vector_store_backend,
            settings.qdrant_url,
            settings.qdrant_path,
            settings.qdrant_collection_name,
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_dimension,
            settings.rag_hybrid_alpha,
            settings.rag_bm25_k1,
            settings.rag_bm25_b,
            settings.rag_score_dense_weight,
            settings.rag_score_lexical_weight,
            settings.rag_score_business_weight,
        )

    @staticmethod
    def _build_backend() -> BaseExternalRetriever:
        settings = get_settings()
        requested_backend = settings.vector_store_backend.lower().strip()
        if requested_backend == "qdrant" and (
            settings.qdrant_url.strip() or settings.qdrant_path.strip()
        ):
            return QdrantExternalRetriever(requested_backend=requested_backend)
        return InMemoryExternalRetriever(requested_backend=requested_backend)


@dataclass(frozen=True)
class _ChunkedDocument:
    doc_id: str
    ticker: str
    text: str
    title: str
    published_at: int
    source_type: str
    url: str
    form_type: str
    importance: float
    metadata: dict[str, object]


def _build_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    provider_name = settings.embedding_provider.strip().lower()
    if provider_name == "gemini":
        return GeminiEmbeddingProvider(
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )
    return HashEmbeddingProvider(dimension=settings.embedding_dimension)


def _build_payload(*, document: _ChunkedDocument, embedding_provider: str) -> dict[str, object]:
    metadata = dict(document.metadata)
    metadata.setdefault("embedding_provider", embedding_provider)
    return {
        "doc_id": document.doc_id,
        "ticker": document.ticker,
        "text": document.text,
        "title": document.title,
        "published_at": document.published_at,
        "source_type": document.source_type,
        "url": document.url,
        "form_type": document.form_type,
        "importance": document.importance,
        "metadata": metadata,
    }


def _chunk_document(document: ExternalDocument) -> list[_ChunkedDocument]:
    settings = get_settings()
    text = document.text.strip()
    if not text:
        return []

    max_chars = max(400, settings.external_chunk_size_chars)
    overlap = max(0, min(settings.external_chunk_overlap_chars, max_chars // 2))
    if len(text) <= max_chars:
        return [
            _ChunkedDocument(
                doc_id=document.doc_id,
                ticker=document.ticker,
                text=text,
                title=document.title,
                published_at=document.published_at,
                source_type=document.source_type,
                url=document.url,
                form_type=document.form_type,
                importance=document.importance,
                metadata=dict(document.metadata),
            )
        ]

    chunks: list[_ChunkedDocument] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(
                _ChunkedDocument(
                    doc_id=f"{document.doc_id}#chunk-{index}",
                    ticker=document.ticker,
                    text=chunk_text,
                    title=document.title,
                    published_at=document.published_at,
                    source_type=document.source_type,
                    url=document.url,
                    form_type=document.form_type,
                    importance=document.importance,
                    metadata={
                        **dict(document.metadata),
                        "original_doc_id": document.doc_id,
                        "chunk_index": index,
                    },
                )
            )
        if end >= len(text):
            break
        start = max(0, end - overlap)
        index += 1
    return chunks


def _document_matches_filters(
    *,
    document: ExternalDocument,
    ticker: str,
    chunk_timestamp: int,
    lower_bound: int,
    preferred_sources: set[str],
) -> bool:
    if document.ticker.upper() != ticker.upper():
        return False
    if document.published_at and chunk_timestamp and document.published_at > chunk_timestamp:
        return False
    if document.published_at and document.published_at < lower_bound:
        return False
    if preferred_sources and document.source_type.lower() not in preferred_sources:
        return False
    return True


def _make_qdrant_filter(
    *,
    ticker: str,
    chunk_timestamp: int,
    lower_bound: int,
    preferred_sources: set[str],
) -> Any:
    conditions = [_make_field_condition("ticker", match=_make_match_value(ticker))]
    if chunk_timestamp:
        conditions.append(
            _make_field_condition("published_at", range_filter=_make_range(lte=int(chunk_timestamp)))
        )
    if lower_bound > 0:
        conditions.append(
            _make_field_condition("published_at", range_filter=_make_range(gte=int(lower_bound)))
        )
    if preferred_sources:
        conditions.append(
            _make_field_condition(
                "source_type",
                match=_make_match_any(sorted(preferred_sources)),
            )
        )
    return _make_filter(conditions)


def _make_qdrant_vector_config(*, size: int) -> Any:
    models = _load_qdrant_models()
    if models is None:
        return {"dense": {"size": int(size), "distance": "Cosine"}}
    return {
        _QDRANT_COLLECTION_VECTOR_NAME: models.VectorParams(
            size=int(size),
            distance=models.Distance.COSINE,
        )
    }


def _make_qdrant_point(*, point_id: str, vector: list[float], payload: dict[str, object]) -> Any:
    models = _load_qdrant_models()
    wrapped_vector = _wrap_query_vector(vector)
    normalized_id = str(uuid5(NAMESPACE_URL, point_id))
    if models is None:
        return {"id": normalized_id, "vector": wrapped_vector, "payload": payload}
    return models.PointStruct(id=normalized_id, vector=wrapped_vector, payload=payload)


def _wrap_query_vector(vector: list[float]) -> Any:
    return {_QDRANT_COLLECTION_VECTOR_NAME: vector}


def _make_filter(conditions: Sequence[Any]) -> Any:
    models = _load_qdrant_models()
    if models is None:
        return {"must": list(conditions)}
    return models.Filter(must=list(conditions))


def _make_field_condition(key: str, *, match: Any | None = None, range_filter: Any | None = None) -> Any:
    models = _load_qdrant_models()
    if models is None:
        payload = {"key": key}
        if match is not None:
            payload["match"] = match
        if range_filter is not None:
            payload["range"] = range_filter
        return payload
    return models.FieldCondition(key=key, match=match, range=range_filter)


def _make_match_value(value: str) -> Any:
    models = _load_qdrant_models()
    if models is None:
        return {"value": value}
    return models.MatchValue(value=value)


def _make_match_any(values: Sequence[str]) -> Any:
    models = _load_qdrant_models()
    if models is None:
        return {"any": list(values)}
    return models.MatchAny(any=list(values))


def _make_range(*, gte: int | None = None, lte: int | None = None) -> Any:
    models = _load_qdrant_models()
    if models is None:
        payload: dict[str, int] = {}
        if gte is not None:
            payload["gte"] = int(gte)
        if lte is not None:
            payload["lte"] = int(lte)
        return payload
    return models.Range(gte=gte, lte=lte)


def _load_qdrant_models() -> Any | None:
    try:
        from qdrant_client.http import models
    except ImportError:  # pragma: no cover - depends on local environment
        return None
    return models


def _extract_payload(hit: Any) -> dict[str, Any]:
    if isinstance(hit, dict):
        return dict(hit.get("payload", {}))
    return dict(getattr(hit, "payload", {}) or {})


def _document_from_payload(payload: dict[str, Any]) -> ExternalDocument:
    return ExternalDocument(
        doc_id=str(payload.get("doc_id", "")),
        ticker=str(payload.get("ticker", "")),
        text=str(payload.get("text", "")),
        title=str(payload.get("title", "")),
        published_at=int(payload.get("published_at", 0) or 0),
        source_type=str(payload.get("source_type", "news")),
        url=str(payload.get("url", "")),
        form_type=str(payload.get("form_type", "")),
        importance=float(payload.get("importance", 0.5) or 0.5),
        metadata=dict(payload.get("metadata", {}) or {}),
    )


def _retrieved_document_from_source(
    *,
    document: ExternalDocument,
    score: float,
) -> ExternalRetrievedDocument:
    return ExternalRetrievedDocument(
        doc_id=document.doc_id,
        text=document.text,
        score=round(max(0.0, min(score, 1.0)), 4),
        title=document.title,
        published_at=document.published_at,
        source_type=document.source_type,
        url=document.url,
        form_type=document.form_type,
        metadata=dict(document.metadata),
    )


def _bm25_lexical_scores(
    *,
    query: str,
    query_tokens: set[str],
    documents: Sequence[ExternalDocument],
) -> dict[str, float]:
    if not documents or not query_tokens:
        return {}

    settings = get_settings()
    doc_counters: dict[str, Counter[str]] = {}
    doc_lengths: dict[str, int] = {}
    document_texts: dict[str, str] = {}
    document_frequency: Counter[str] = Counter()

    for document in documents:
        doc_text = " ".join(part for part in (document.title, document.text) if part)
        doc_tokens = _document_lexical_tokens(document)
        if not doc_tokens:
            continue
        frequencies = Counter(doc_tokens)
        doc_counters[document.doc_id] = frequencies
        doc_lengths[document.doc_id] = len(doc_tokens)
        document_texts[document.doc_id] = doc_text
        document_frequency.update(query_tokens & set(frequencies))

    if not doc_counters:
        return {}

    avg_doc_length = sum(doc_lengths.values()) / max(len(doc_lengths), 1)
    raw_scores: dict[str, float] = {}
    corpus_size = len(doc_counters)
    for document in documents:
        frequencies = doc_counters.get(document.doc_id)
        if frequencies is None:
            continue
        raw_score = 0.0
        doc_length = max(1, doc_lengths.get(document.doc_id, 0))
        for term in query_tokens:
            term_frequency = frequencies.get(term, 0)
            if term_frequency <= 0:
                continue
            term_document_frequency = document_frequency.get(term, 0)
            idf = math.log(
                1.0 + (corpus_size - term_document_frequency + 0.5) / (term_document_frequency + 0.5)
            )
            denominator = term_frequency + settings.rag_bm25_k1 * (
                1.0 - settings.rag_bm25_b + settings.rag_bm25_b * (doc_length / max(avg_doc_length, 1.0))
            )
            raw_score += idf * (
                term_frequency * (settings.rag_bm25_k1 + 1.0) / max(denominator, 1e-9)
            )
        if raw_score > 0.0:
            raw_scores[document.doc_id] = raw_score

    if not raw_scores:
        return {}

    max_raw_score = max(raw_scores.values())
    lexical_scores: dict[str, float] = {}
    for document in documents:
        raw_score = raw_scores.get(document.doc_id, 0.0)
        if raw_score <= 0.0:
            continue
        normalized_bm25 = raw_score / max(max_raw_score, 1e-9)
        phrase_signal = 1.0 if _contains_phrase_overlap(query, document_texts[document.doc_id]) else 0.0
        lexical_scores[document.doc_id] = min(1.0, 0.88 * normalized_bm25 + 0.12 * phrase_signal)
    return lexical_scores


def _business_signal_score(
    *,
    document: ExternalDocument,
    chunk_timestamp: int,
    lookback_days: int,
) -> float:
    recency_signal = _recency_signal(
        published_at=document.published_at,
        chunk_timestamp=chunk_timestamp,
        lookback_days=lookback_days,
    )
    importance_signal = max(0.0, min(float(document.importance or 0.0), 1.0))
    source_signal = _source_signal(document.source_type)
    return min(1.0, (0.50 * recency_signal) + (0.30 * importance_signal) + (0.20 * source_signal))


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


def _recency_signal(*, published_at: int, chunk_timestamp: int, lookback_days: int) -> float:
    if not published_at or not chunk_timestamp or published_at > chunk_timestamp:
        return 0.0

    age_seconds = max(0, chunk_timestamp - published_at)
    max_age_seconds = max(1, lookback_days * 86400)
    freshness = 1.0 - min(age_seconds / max_age_seconds, 1.0)
    return math.sqrt(freshness)


def _source_signal(source_type: str) -> float:
    normalized = str(source_type or "").strip().lower()
    if normalized == "filing":
        return 1.0
    if normalized == "ir":
        return 0.85
    if normalized == "press_release":
        return 0.70
    return 0.55


def _lower_bound_timestamp(*, chunk_timestamp: int, lookback_days: int) -> int:
    if not chunk_timestamp:
        return 0
    window_seconds = max(1, int(lookback_days)) * 86400
    return max(0, int(chunk_timestamp) - window_seconds)


def _normalize_dense_score(score: float) -> float:
    if -1.0 <= score <= 1.0:
        return max(0.0, min((score + 1.0) / 2.0, 1.0))
    return max(0.0, min(score, 1.0))


def _significant_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    }


def _document_lexical_tokens(document: ExternalDocument) -> list[str]:
    title_tokens = [
        token.lower()
        for token in _TOKEN_RE.findall(document.title or "")
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    ]
    text_tokens = [
        token.lower()
        for token in _TOKEN_RE.findall(document.text or "")
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    ]
    return title_tokens + title_tokens + text_tokens


def _normalize_vector(vector: Sequence[float]) -> list[float]:
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude <= 0.0:
        return [0.0 for _ in vector]
    return [component / magnitude for component in vector]


def _truncate_or_pad(vector: Sequence[float], dimension: int) -> list[float]:
    if len(vector) >= dimension:
        return list(vector[:dimension])
    return list(vector) + ([0.0] * (dimension - len(vector)))


def _coerce_embedding_vector(item: Any) -> list[float]:
    if item is None:
        return []
    if isinstance(item, list):
        return [float(value) for value in item]
    values = getattr(item, "values", None)
    if values is not None:
        return [float(value) for value in values]
    if isinstance(item, dict):
        for key in ("values", "embedding"):
            if key in item:
                return [float(value) for value in item[key]]
    embedding = getattr(item, "embedding", None)
    if embedding is not None and embedding is not item:
        return _coerce_embedding_vector(embedding)
    raise RuntimeError("Unsupported embedding payload")


external_retriever = ExternalRetrieverFacade()
