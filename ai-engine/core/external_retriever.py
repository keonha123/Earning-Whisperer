"""External evidence retrieval with memory-first and optional Qdrant backends.

This module follows the `hyeongyu` branch RAG architecture:
`ExternalDocument` -> `ExternalRetrieverFacade` -> `ExternalRetrievedDocument`.
The implementation is intentionally memory-first so the upgraded v9 engine can
run without Qdrant/OpenAI installed, while the facade keeps the vector backend
boundary explicit.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import importlib
import json
import logging
import math
import re
import threading
import time
from typing import Any, Mapping, Protocol, Sequence
import urllib.error
import urllib.request
from uuid import NAMESPACE_URL, uuid5

try:
    from config import get_settings
except ImportError:  # pragma: no cover
    from ..config import get_settings


logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
    "about", "after", "before", "between", "could", "should", "would", "their", "there",
    "these", "those", "when", "where", "which", "while", "will", "year", "quarter",
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
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalRetrievedDocument:
    """Prompt-ready evidence document returned from retrieval."""

    doc_id: str
    text: str
    score: float
    semantic_score: float = 0.0
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
    name: str
    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    """Deterministic local embedding fallback for tests/offline runs."""

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
                vector[bucket] += 1.0 if digest[4] % 2 == 0 else -1.0
            vectors.append(_normalize_vector(vector))
        return vectors


class GeminiEmbeddingProvider:
    """Gemini embedding wrapper.

    무료 등급 키로 쓸 수 있는 유일한 실제 의미 임베딩이다. OpenAI 키가 없는 환경에서
    ``hash`` 로 조용히 떨어지면 근거 검색이 단어 겹침 수준으로 퇴화하고, 관련도 임계값
    (기본 0.42)을 아무것도 넘지 못해 모든 판정이 INSUFFICIENT_EVIDENCE 가 된다.
    그 실패는 화면에서 "근거가 없는 주장" 과 구별되지 않으므로 여기서 막는다.

    배치 크기를 20 으로 제한하는 이유: 무료 등급에서 100건을 한 번에 보내면 429 가 난다.
    실측값이다.
    """

    name = "gemini"

    #: 무료 등급에서 429 없이 통과하는 것을 확인한 상한.
    MAX_BATCH = 20


    MAX_RETRIES = 6
    RETRY_BASE_DELAY_SECONDS = 4.0
    MAX_RETRY_DELAY_SECONDS = 60.0

    _ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"

    def __init__(self, *, model: str, dimension: int) -> None:
        self.model = model or "gemini-embedding-001"
        self.dimension = max(32, int(dimension))

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = get_settings()
        api_key = str(getattr(settings, "gemini_api_key", "") or "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings")

        vectors: list[list[float]] = []
        for index, start in enumerate(range(0, len(texts), self.MAX_BATCH)):
            if index:
                # 배치의 각 항목이 요청 1건으로 계산된다. 20건 배치를 1.5초 간격으로
                # 보내면 분당 800건꼴이라 무료 등급 한도를 크게 넘는다. 목표 RPM 에서
                # 간격을 역산한다.
                time.sleep(self._inter_batch_sleep(settings))
            window = list(texts[start : start + self.MAX_BATCH])
            vectors.extend(self._embed_batch_with_retry(window, api_key))
        if len(vectors) != len(texts):
            raise RuntimeError("Gemini embedding response size mismatch")
        return vectors

    def _inter_batch_sleep(self, settings: Any) -> float:
        rpm = max(1, int(getattr(settings, "gemini_embed_requests_per_minute", 90) or 90))
        return self.MAX_BATCH / (rpm / 60.0)

    def _embed_batch_with_retry(self, texts: list[str], api_key: str) -> list[list[float]]:
        """429 를 지수 백오프로 넘긴다.

        여기서 예외를 그냥 올리면 뉴스 인입 배치 전체가 500 으로 실패하고, 어디까지
        들어갔는지 알 수 없는 상태가 된다. 한도는 기다리면 풀리는 문제이므로 기다린다.
        """
        delay = self.RETRY_BASE_DELAY_SECONDS
        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return self._embed_batch(texts, api_key)
            except urllib.error.HTTPError as exc:  # noqa: PERF203
                if exc.code not in (429, 500, 503):
                    raise
                last_error = exc
                logger.warning(
                    "Gemini 임베딩 %s — %.1f초 후 재시도 (%d/%d)",
                    exc.code, delay, attempt + 1, self.MAX_RETRIES,
                )
                time.sleep(delay)
                delay = min(delay * 2, self.MAX_RETRY_DELAY_SECONDS)
        raise RuntimeError(f"Gemini embedding failed after {self.MAX_RETRIES} retries") from last_error

    def _embed_batch(self, texts: list[str], api_key: str) -> list[list[float]]:
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text or " "}]},
                    "outputDimensionality": self.dimension,
                }
                for text in texts
            ]
        }
        request = urllib.request.Request(
            self._ENDPOINT.format(model=self.model),
            data=json.dumps(payload).encode("utf-8"),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read())
        embeddings = body.get("embeddings") or []
        if len(embeddings) != len(texts):
            raise RuntimeError("Gemini embedding batch size mismatch")
        # 차원 축소 임베딩은 정규화되어 오지 않는다. 코사인 유사도를 쓰는 저장소에
        # 그대로 넣으면 관련도 점수가 문서 길이에 흔들린다.
        return [
            _normalize_vector(_truncate_or_pad(_coerce_embedding_vector(item.get("values")), self.dimension))
            for item in embeddings
        ]


class OpenAIEmbeddingProvider:
    """OpenAI embedding wrapper used only when configured."""

    name = "openai"

    def __init__(self, *, model: str, dimension: int) -> None:
        self.model = model
        self.dimension = max(32, int(dimension))
        self._client: Any = None
        self._api_key: str | None = None

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings")
        if self._client is None or self._api_key != settings.openai_api_key:
            try:
                openai_module = importlib.import_module("openai")
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("openai package is not installed") from exc
            self._client = openai_module.OpenAI(api_key=settings.openai_api_key)
            self._api_key = settings.openai_api_key
        kwargs: dict[str, Any] = {"model": self.model, "input": list(texts), "encoding_format": "float"}
        if self.model.startswith("text-embedding-3"):
            kwargs["dimensions"] = self.dimension
        response = self._client.embeddings.create(**kwargs)
        vectors = [_truncate_or_pad(_coerce_embedding_vector(item.embedding), self.dimension) for item in response.data]
        if len(vectors) != len(texts):
            raise RuntimeError("OpenAI embedding response size mismatch")
        return vectors


class BaseExternalRetriever:
    backend_name = "base"

    def __init__(self, *, requested_backend: str, effective_backend: str | None = None) -> None:
        self._stats = RetrieverStats(requested_backend=requested_backend, effective_backend=effective_backend or self.backend_name)

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def delete_expired_documents(self, *, now: int | None = None) -> dict[str, object]:
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
        semantic_only: bool = False,
    ) -> list[ExternalRetrievedDocument]:
        raise NotImplementedError

    def retrieve_many(
        self,
        *,
        queries: Sequence[str],
        ticker: str,
        chunk_timestamps: Sequence[int],
        preferred_sources: Sequence[str] | None = None,
        lookback_days: int = 7,
        limit: int | None = None,
        semantic_only: bool = False,
    ) -> list[list[ExternalRetrievedDocument]]:
        if len(queries) != len(chunk_timestamps):
            raise ValueError("queries and chunk_timestamps must have the same length")
        return [
            self.retrieve(
                query=query,
                ticker=ticker,
                chunk_timestamp=timestamp,
                preferred_sources=preferred_sources,
                lookback_days=lookback_days,
                limit=limit,
                semantic_only=semantic_only,
            )
            for query, timestamp in zip(queries, chunk_timestamps)
        ]

    def get_stats(self) -> dict[str, object]:
        return self._stats.to_dict()

    def close(self) -> None:
        return None

    def _record_upsert(self, chunk_count: int) -> None:
        self._stats.upserted_chunks += max(0, int(chunk_count))

    def _record_retrieval(self, *, latency_ms: float, hit_count: int, error: Exception | None = None) -> None:
        self._stats.retrieval_count += 1
        self._stats.total_latency_ms += max(0.0, latency_ms)
        if hit_count == 0:
            self._stats.empty_hits += 1
        if error is not None:
            self._stats.error_count += 1
            self._stats.last_error = str(error)


    def count_documents(self, *, ticker: str, since_epoch: int | None = None) -> int:
        """해당 종목의 근거 문서 수. 임베딩 호출 없이 세기만 한다.

        시연 직전에 "근거 저장소가 비어 있는지" 를 확인하는 용도다. 이게 없으면
        근거가 하나도 없는 상태로 어닝콜을 재생해도 화면에는 그냥 "근거 부족" 만
        줄줄이 뜨고, 그것이 <b>정말 근거가 없는 주장</b>인지 <b>저장소가 빈 것</b>인지
        구별할 방법이 없다.
        """
        raise NotImplementedError


class InMemoryExternalRetriever(BaseExternalRetriever):
    """BM25-like in-memory retriever with the same facade API as Qdrant."""

    backend_name = "memory"

    def __init__(self, *, requested_backend: str = "memory") -> None:
        super().__init__(requested_backend=requested_backend, effective_backend=self.backend_name)
        self._documents: dict[str, ExternalDocument] = {}

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        chunks: list[ExternalDocument] = []
        for document in documents:
            chunks.extend(_chunk_document(document))
        for chunk in chunks:
            self._documents[chunk.doc_id] = chunk
        self._record_upsert(len(chunks))

    def clear(self) -> None:
        self._documents.clear()

    def delete_expired_documents(self, *, now: int | None = None) -> dict[str, object]:
        settings = get_settings()
        current_timestamp = int(now if now is not None else time.time())
        cutoff = max(0, current_timestamp - max(1, settings.external_evidence_retention_days) * 86400)
        expired = [doc_id for doc_id, doc in self._documents.items() if doc.published_at and doc.published_at < cutoff]
        for doc_id in expired:
            self._documents.pop(doc_id, None)
        return {"status": "completed", "cutoff_timestamp": cutoff, "deleted_count": len(expired)}

    def retrieve(
        self,
        *,
        query: str,
        ticker: str,
        chunk_timestamp: int,
        preferred_sources: Sequence[str] | None = None,
        lookback_days: int = 7,
        limit: int | None = None,
        semantic_only: bool = False,
    ) -> list[ExternalRetrievedDocument]:
        start = time.monotonic()
        error: Exception | None = None
        scored: list[ExternalRetrievedDocument] = []
        try:
            settings = get_settings()
            top_k = limit or settings.rag_top_k
            if not query.strip() or not ticker.strip():
                return []
            preferred = {str(src).strip().lower() for src in (preferred_sources or []) if src}
            query_tokens = _significant_tokens(query)
            if not query_tokens:
                return []
            lower_bound = _lower_bound_timestamp(chunk_timestamp=chunk_timestamp, lookback_days=lookback_days)
            candidates = [
                doc
                for doc in self._documents.values()
                if _document_matches_filters(
                    document=doc,
                    ticker=ticker,
                    chunk_timestamp=chunk_timestamp,
                    lower_bound=lower_bound,
                    preferred_sources=preferred,
                )
            ]
            lexical_scores = _bm25_lexical_scores(query=query, query_tokens=query_tokens, documents=candidates)
            for document in candidates:
                lexical = lexical_scores.get(document.doc_id, 0.0)
                if lexical < settings.rag_min_relevance_score:
                    continue
                business = _business_signal_score(document=document, chunk_timestamp=chunk_timestamp, lookback_days=lookback_days)
                score = _weighted_score(dense=0.0, lexical=lexical, business=business)
                scored.append(_retrieved_document_from_source(document=document, score=score, semantic_score=lexical))
            rank_score = (lambda doc: doc.semantic_score) if semantic_only else (lambda doc: doc.score)
            scored.sort(key=lambda doc: (-rank_score(doc), -doc.published_at, doc.doc_id))
            return scored[:top_k]
        except Exception as exc:  # pragma: no cover
            error = exc
            logger.warning("Memory retrieval failed: %s", exc)
            return []
        finally:
            self._record_retrieval(latency_ms=(time.monotonic() - start) * 1000, hit_count=len(scored), error=error)


    def count_documents(self, *, ticker: str, since_epoch: int | None = None) -> int:
        normalized = str(ticker or "").upper()
        return sum(
            1
            for doc in self._documents.values()
            if doc.ticker.upper() == normalized
            and (since_epoch is None or not doc.published_at or doc.published_at >= since_epoch)
        )


class QdrantExternalRetriever(BaseExternalRetriever):
    """Qdrant-backed external evidence retriever."""

    backend_name = "qdrant"

    #: 종목별 문서 수 캐시 수명. 한 번의 어닝콜 검증에서 문장마다 카운트를 다시 묻지
    #: 않으려는 목적이고, 적재 직후에도 곧 반영되도록 짧게 잡는다.
    _COUNT_CACHE_TTL_SECONDS = 30.0

    def __init__(
        self,
        *,
        requested_backend: str = "qdrant",
        client: Any | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        collection_name: str | None = None,
        embedding_version: str | None = None,
    ) -> None:
        super().__init__(requested_backend=requested_backend, effective_backend=self.backend_name)
        settings = get_settings()
        self.collection_name = collection_name or settings.qdrant_collection_name
        provider, model, dimension, version = _external_embedding_config(settings)
        self.embedding_provider = embedding_provider or _build_embedding_provider(provider=provider, model=model, dimension=dimension)
        self.embedding_version = embedding_version or version
        self.client = client or self._build_client(url=settings.qdrant_url, path=settings.qdrant_path)
        self._count_cache: dict[str, tuple[int, float]] = {}
        self._ensure_collection()

    @staticmethod
    def _build_client(*, url: str, path: str) -> Any:
        if not url.strip() and not path.strip():
            raise RuntimeError("QDRANT_URL or QDRANT_PATH is required when VECTOR_STORE_BACKEND=qdrant")
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        if path.strip():
            return QdrantClient(path=path.strip())
        return QdrantClient(url=url.strip())

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(collection_name=self.collection_name):
            return
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.embedding_provider.dimension,
                distance=models.Distance.COSINE,
            ),
        )

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        # 방금 넣은 문서를 캐시 수명 동안 못 보는 일이 없게 즉시 버린다.
        self._count_cache.clear()
        chunks: list[ExternalDocument] = []
        for document in documents:
            chunks.extend(_chunk_document(document))
        if not chunks:
            return
        vectors = self.embedding_provider.embed_texts([chunk.text for chunk in chunks])
        points = [
            self._point_struct(
                id=str(uuid5(NAMESPACE_URL, f"earningwhisperer:external:{chunk.doc_id}")),
                vector=vector,
                payload={
                    "store": "external",
                    "doc_id": chunk.doc_id,
                    "ticker": chunk.ticker.upper(),
                    "text": chunk.text,
                    "title": chunk.title,
                    "published_at": int(chunk.published_at or 0),
                    "source_type": chunk.source_type,
                    "url": chunk.url,
                    "form_type": chunk.form_type,
                    "embedding_provider": self.embedding_provider.name,
                    "embedding_version": self.embedding_version,
                    "metadata": _json_ready(chunk.metadata),
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
        self._record_upsert(len(points))

    def _ticker_document_count(self, ticker: str) -> int:
        """종목별 적재 문서 수. 한 번의 검증에서 문장마다 반복 호출되므로 짧게 캐시한다.

        캐시 수명이 짧아서 적재 직후에도 곧 반영된다. 정확한 수치가 필요한 곳
        (readiness 엔드포인트) 은 캐시를 타지 않는 ``count_documents`` 를 그대로 쓴다.
        """
        normalized = str(ticker or "").upper()
        now = time.monotonic()
        cached = self._count_cache.get(normalized)
        if cached is not None and now - cached[1] < self._COUNT_CACHE_TTL_SECONDS:
            return cached[0]
        try:
            count = self.count_documents(ticker=normalized)
        except Exception as exc:
            # 카운트에 실패했다고 검색을 막지는 않는다 — 원래 경로로 흘려보낸다.
            logger.warning("문서 수 조회 실패 — 검색을 그대로 진행한다: %s", exc)
            return 1
        self._count_cache[normalized] = (count, now)
        return count

    def count_documents(self, *, ticker: str, since_epoch: int | None = None) -> int:
        filters = [self._match_filter("ticker", str(ticker or "").upper())]
        if since_epoch is not None:
            filters.append(self._range_filter("published_at", gte=int(since_epoch)))
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=self._filter(filters),
            exact=True,
        )
        return int(getattr(result, "count", 0) or 0)


    def clear(self) -> None:
        self._count_cache.clear()
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._filter_selector([self._match_filter("store", "external")]),
        )

    def delete_expired_documents(self, *, now: int | None = None) -> dict[str, object]:
        settings = get_settings()
        current_timestamp = int(now if now is not None else time.time())
        cutoff = max(0, current_timestamp - max(1, settings.external_evidence_retention_days) * 86400)
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._filter_selector(
                [
                    self._match_filter("store", "external"),
                    self._range_filter("published_at", lt=cutoff),
                ]
            ),
        )
        return {"status": "completed", "cutoff_timestamp": cutoff, "deleted_count": None}

    def retrieve(
        self,
        *,
        query: str,
        ticker: str,
        chunk_timestamp: int,
        preferred_sources: Sequence[str] | None = None,
        lookback_days: int = 7,
        limit: int | None = None,
        semantic_only: bool = False,
    ) -> list[ExternalRetrievedDocument]:
        start = time.monotonic()
        error: Exception | None = None
        results: list[ExternalRetrievedDocument] = []
        try:
            settings = get_settings()
            if not query.strip() or not ticker.strip():
                return []
            # 그 종목의 문서가 하나도 없으면 검색할 대상이 없다. 그런데도 질의를 임베딩하면
            # 무료 등급 하루 한도를 헛되이 깎고, 한도가 이미 소진된 상태에서는 429 재시도가
            # 수 분씩 걸려 호출 측(백엔드 종합 판단)이 통째로 타임아웃된다. 근거가 없다는
            # 사실은 임베딩 없이도 알 수 있으므로 여기서 끝낸다.
            if self._ticker_document_count(ticker) == 0:
                return []
            query_vector = self.embedding_provider.embed_texts([query])[0]
            results = self._retrieve_with_vector(
                query_vector=query_vector,
                ticker=ticker,
                chunk_timestamp=chunk_timestamp,
                preferred_sources=preferred_sources,
                lookback_days=lookback_days,
                limit=limit or settings.rag_top_k,
                semantic_only=semantic_only,
            )
            return results
        except Exception as exc:
            error = exc
            raise
        finally:
            self._record_retrieval(latency_ms=(time.monotonic() - start) * 1000, hit_count=len(results), error=error)

    def retrieve_many(
        self,
        *,
        queries: Sequence[str],
        ticker: str,
        chunk_timestamps: Sequence[int],
        preferred_sources: Sequence[str] | None = None,
        lookback_days: int = 7,
        limit: int | None = None,
        semantic_only: bool = False,
    ) -> list[list[ExternalRetrievedDocument]]:
        if len(queries) != len(chunk_timestamps):
            raise ValueError("queries and chunk_timestamps must have the same length")
        if not queries:
            return []
        start = time.monotonic()
        error: Exception | None = None
        batches: list[list[ExternalRetrievedDocument]] = []
        try:
            settings = get_settings()
            vectors = self.embedding_provider.embed_texts(list(queries))
            if len(vectors) != len(queries):
                raise RuntimeError("Embedding batch size mismatch")
            for vector, timestamp in zip(vectors, chunk_timestamps):
                batches.append(
                    self._retrieve_with_vector(
                        query_vector=vector,
                        ticker=ticker,
                        chunk_timestamp=int(timestamp),
                        preferred_sources=preferred_sources,
                        lookback_days=lookback_days,
                        limit=limit or settings.rag_top_k,
                        semantic_only=semantic_only,
                    )
                )
            return batches
        except Exception as exc:
            error = exc
            raise
        finally:
            self._record_retrieval(
                latency_ms=(time.monotonic() - start) * 1000,
                hit_count=sum(len(batch) for batch in batches),
                error=error,
            )

    def _retrieve_with_vector(
        self,
        *,
        query_vector: Sequence[float],
        ticker: str,
        chunk_timestamp: int,
        preferred_sources: Sequence[str] | None,
        lookback_days: int,
        limit: int,
        semantic_only: bool,
    ) -> list[ExternalRetrievedDocument]:
        settings = get_settings()
        lower_bound = _lower_bound_timestamp(chunk_timestamp=chunk_timestamp, lookback_days=lookback_days)
        filters = [
            self._match_filter("store", "external"),
            self._match_filter("ticker", ticker.upper()),
            self._match_filter("embedding_version", self.embedding_version),
            self._range_filter("published_at", gte=lower_bound, lte=chunk_timestamp if chunk_timestamp else None),
        ]
        preferred = [str(src).strip().lower() for src in (preferred_sources or []) if src]
        if preferred:
            filters.append(self._any_filter("source_type", preferred))
        results: list[ExternalRetrievedDocument] = []
        for point in self._query(query_vector, limit=limit, filters=filters):
            document = self._document_from_point(point)
            dense = max(0.0, min(1.0, _point_score(point)))
            business = _business_signal_score(document=document, chunk_timestamp=chunk_timestamp, lookback_days=lookback_days)
            score = _weighted_score(dense=dense, lexical=0.0, business=business)
            if score >= settings.rag_min_relevance_score:
                results.append(_retrieved_document_from_source(document=document, score=score, semantic_score=dense))
        rank_score = (lambda doc: doc.semantic_score) if semantic_only else (lambda doc: doc.score)
        results.sort(key=lambda doc: (-rank_score(doc), -doc.published_at, doc.doc_id))
        return results[:limit]

    def _query(self, query_vector: Sequence[float], *, limit: int, filters: Sequence[Any]) -> list[Any]:
        query_filter = self._filter(filters)
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=list(query_vector),
                query_filter=query_filter,
                limit=int(limit),
                with_payload=True,
            )
            return _qdrant_points(response)
        response = self.client.search(
            collection_name=self.collection_name,
            query_vector=list(query_vector),
            query_filter=query_filter,
            limit=int(limit),
            with_payload=True,
        )
        return _qdrant_points(response)

    @staticmethod
    def _point_struct(*, id: str, vector: Sequence[float], payload: Mapping[str, Any]) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        return models.PointStruct(id=id, vector=list(vector), payload=dict(payload))

    @staticmethod
    def _filter(filters: Sequence[Any]) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        return models.Filter(must=list(filters))

    @staticmethod
    def _filter_selector(filters: Sequence[Any]) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        return models.FilterSelector(filter=models.Filter(must=list(filters)))

    @staticmethod
    def _match_filter(key: str, value: Any) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    @staticmethod
    def _any_filter(key: str, values: Sequence[Any]) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        return models.FieldCondition(key=key, match=models.MatchAny(any=list(values)))

    @staticmethod
    def _range_filter(key: str, *, lt: int | None = None, gte: int | None = None, lte: int | None = None) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("qdrant-client package is required when VECTOR_STORE_BACKEND=qdrant") from exc
        return models.FieldCondition(key=key, range=models.Range(lt=lt, gte=gte, lte=lte))

    @staticmethod
    def _document_from_point(point: Any) -> ExternalDocument:
        payload = _point_payload(point)
        return ExternalDocument(
            doc_id=str(payload.get("doc_id") or ""),
            ticker=str(payload.get("ticker") or "").upper(),
            text=str(payload.get("text") or ""),
            title=str(payload.get("title") or ""),
            published_at=int(payload.get("published_at") or 0),
            source_type=str(payload.get("source_type") or "news"),
            url=str(payload.get("url") or ""),
            form_type=str(payload.get("form_type") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


class ExternalRetrieverFacade:
    """Delegates to the configured backend while preserving module-level API."""

    def __init__(self) -> None:
        self._backend: BaseExternalRetriever | None = None
        self._signature: tuple[Any, ...] | None = None
        self._lock = threading.Lock()

    def upsert_documents(self, documents: Sequence[ExternalDocument]) -> None:
        self._get_backend().upsert_documents(documents)

    def clear(self) -> None:
        self._get_backend().clear()

    def delete_expired_documents(self, *, now: int | None = None) -> dict[str, object]:
        return self._get_backend().delete_expired_documents(now=now)

    def count_documents(self, *, ticker: str, since_epoch: int | None = None) -> int:
        return self._get_backend().count_documents(ticker=ticker, since_epoch=since_epoch)

    def retrieve(
        self,
        *,
        query: str,
        ticker: str,
        chunk_timestamp: int,
        preferred_sources: Sequence[str] | None = None,
        lookback_days: int = 7,
        limit: int | None = None,
        semantic_only: bool = False,
    ) -> list[ExternalRetrievedDocument]:
        return self._get_backend().retrieve(
            query=query,
            ticker=ticker,
            chunk_timestamp=chunk_timestamp,
            preferred_sources=preferred_sources,
            lookback_days=lookback_days,
            limit=limit,
            semantic_only=semantic_only,
        )

    def retrieve_many(
        self,
        *,
        queries: Sequence[str],
        ticker: str,
        chunk_timestamps: Sequence[int],
        preferred_sources: Sequence[str] | None = None,
        lookback_days: int = 7,
        limit: int | None = None,
        semantic_only: bool = False,
    ) -> list[list[ExternalRetrievedDocument]]:
        return self._get_backend().retrieve_many(
            queries=queries,
            ticker=ticker,
            chunk_timestamps=chunk_timestamps,
            preferred_sources=preferred_sources,
            lookback_days=lookback_days,
            limit=limit,
            semantic_only=semantic_only,
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
        provider, model, dimension, version = _external_embedding_config(settings)
        return (
            settings.vector_store_backend,
            settings.qdrant_url,
            settings.qdrant_path,
            settings.qdrant_collection_name,
            provider,
            model,
            dimension,
            version,
        )

    @staticmethod
    def _build_backend() -> BaseExternalRetriever:
        settings = get_settings()
        requested = settings.vector_store_backend.lower().strip()
        if requested == "qdrant":
            return QdrantExternalRetriever(requested_backend=requested)
        return InMemoryExternalRetriever(requested_backend=requested or "memory")


def _external_embedding_config(settings: Any | None = None) -> tuple[str, str, int, str]:
    settings = settings or get_settings()
    provider = (settings.external_embedding_provider or settings.embedding_provider).strip().lower()
    model = (settings.external_embedding_model or settings.embedding_model).strip()
    dimension = int(settings.external_embedding_dimension or settings.embedding_dimension)
    configured_version = str(settings.external_embedding_version or "").strip()
    version = configured_version or f"{provider}-{model}-{dimension}-v1"
    return provider, model, dimension, version


def _build_embedding_provider(*, provider: str | None = None, model: str | None = None, dimension: int | None = None) -> EmbeddingProvider:
    settings = get_settings()
    effective_provider = (provider or settings.embedding_provider).strip().lower()
    effective_model = (model or settings.embedding_model).strip()
    effective_dimension = int(dimension or settings.embedding_dimension)
    if effective_provider == "openai":
        return OpenAIEmbeddingProvider(model=effective_model, dimension=effective_dimension)
    if effective_provider == "gemini":
        return GeminiEmbeddingProvider(model=effective_model, dimension=effective_dimension)
    if effective_provider not in {"", "hash"}:
        # 오타로 알 수 없는 값이 들어오면 해시로 떨어뜨리지 않는다. 그렇게 되면
        # 의미 검색이 죽은 채로 조용히 돌아간다.
        raise ValueError(f"Unknown EMBEDDING_PROVIDER: {effective_provider}")
    return HashEmbeddingProvider(dimension=effective_dimension)


def _chunk_document(document: ExternalDocument) -> list[ExternalDocument]:
    settings = get_settings()
    text = document.text.strip()
    if not text:
        return []
    max_chars = max(400, settings.external_chunk_size_chars)
    overlap = max(0, min(settings.external_chunk_overlap_chars, max_chars - 1))
    if len(text) <= max_chars:
        return [document]
    chunks: list[ExternalDocument] = []
    start = 0
    index = 0
    step = max(1, max_chars - overlap)
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(
                ExternalDocument(
                    doc_id=f"{document.doc_id}#chunk-{index}",
                    ticker=document.ticker,
                    text=chunk_text,
                    title=document.title,
                    published_at=document.published_at,
                    source_type=document.source_type,
                    url=document.url,
                    form_type=document.form_type,
                    metadata={**dict(document.metadata), "original_doc_id": document.doc_id, "chunk_index": index},
                )
            )
        if end >= len(text):
            break
        start += step
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


def _bm25_lexical_scores(
    *,
    query: str,
    query_tokens: set[str],
    documents: Sequence[ExternalDocument],
) -> dict[str, float]:
    if not documents or not query_tokens:
        return {}
    settings = get_settings()
    counters: dict[str, Counter[str]] = {}
    lengths: dict[str, int] = {}
    df: Counter[str] = Counter()
    texts: dict[str, str] = {}
    for doc in documents:
        tokens = _document_lexical_tokens(doc)
        if not tokens:
            continue
        counter = Counter(tokens)
        counters[doc.doc_id] = counter
        lengths[doc.doc_id] = len(tokens)
        texts[doc.doc_id] = f"{doc.title} {doc.text}"
        df.update(query_tokens & set(counter))
    if not counters:
        return {}
    avg_len = sum(lengths.values()) / max(len(lengths), 1)
    raw: dict[str, float] = {}
    corpus_size = len(counters)
    for doc in documents:
        counter = counters.get(doc.doc_id)
        if counter is None:
            continue
        doc_len = max(1, lengths.get(doc.doc_id, 0))
        score = 0.0
        for term in query_tokens:
            tf = counter.get(term, 0)
            if tf <= 0:
                continue
            term_df = df.get(term, 0)
            idf = math.log(1.0 + (corpus_size - term_df + 0.5) / (term_df + 0.5))
            denom = tf + settings.rag_bm25_k1 * (1.0 - settings.rag_bm25_b + settings.rag_bm25_b * (doc_len / max(avg_len, 1.0)))
            score += idf * (tf * (settings.rag_bm25_k1 + 1.0) / max(denom, 1e-9))
        if score > 0.0:
            raw[doc.doc_id] = score
    if not raw:
        return {}
    max_raw = max(raw.values())
    return {
        doc_id: min(1.0, 0.88 * (score / max(max_raw, 1e-9)) + 0.12 * (1.0 if _contains_phrase_overlap(query, texts[doc_id]) else 0.0))
        for doc_id, score in raw.items()
    }


def _business_signal_score(*, document: ExternalDocument, chunk_timestamp: int, lookback_days: int) -> float:
    if not document.published_at or not chunk_timestamp or document.published_at > chunk_timestamp:
        return 0.0
    age_seconds = max(0, chunk_timestamp - document.published_at)
    max_age_seconds = max(1, lookback_days * 86400)
    recency = 1.0 - min(age_seconds / max_age_seconds, 1.0)
    return min(1.0, math.sqrt(recency))


def _weighted_score(*, dense: float, lexical: float, business: float) -> float:
    settings = get_settings()
    score = (
        settings.rag_score_dense_weight * dense
        + settings.rag_score_lexical_weight * lexical
        + settings.rag_score_business_weight * business
    )
    if dense <= 0.0:
        score = min(1.0, score + 0.30 * lexical)
    return round(max(0.0, min(score, 1.0)), 4)


def _retrieved_document_from_source(*, document: ExternalDocument, score: float, semantic_score: float) -> ExternalRetrievedDocument:
    return ExternalRetrievedDocument(
        doc_id=document.doc_id,
        text=document.text,
        score=round(max(0.0, min(score, 1.0)), 4),
        semantic_score=round(max(0.0, min(semantic_score, 1.0)), 4),
        title=document.title,
        published_at=document.published_at,
        source_type=document.source_type,
        url=document.url,
        form_type=document.form_type,
        metadata=dict(document.metadata),
    )


def _contains_phrase_overlap(query: str, text: str) -> bool:
    words = [token for token in _TOKEN_RE.findall(query.lower()) if len(token) >= 3 and token not in _STOPWORDS]
    if len(words) < 2:
        return False
    text_l = f" {text.lower()} "
    return any(f" {words[idx]} {words[idx + 1]} " in text_l for idx in range(len(words) - 1))


def _lower_bound_timestamp(*, chunk_timestamp: int, lookback_days: int) -> int:
    if not chunk_timestamp:
        return 0
    return max(0, int(chunk_timestamp) - max(1, int(lookback_days)) * 86400)


def _significant_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if len(token) >= 3 and token.lower() not in _STOPWORDS
    }


def _document_lexical_tokens(document: ExternalDocument) -> list[str]:
    title = [token.lower() for token in _TOKEN_RE.findall(document.title or "") if len(token) >= 3 and token.lower() not in _STOPWORDS]
    body = [token.lower() for token in _TOKEN_RE.findall(document.text or "") if len(token) >= 3 and token.lower() not in _STOPWORDS]
    return title + title + body


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
    raise RuntimeError("Unsupported embedding payload")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _point_payload(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None)
    if payload is None and isinstance(point, Mapping):
        payload = point.get("payload")
    return dict(payload or {})


def _point_score(point: Any) -> float:
    if hasattr(point, "score"):
        return float(getattr(point, "score") or 0.0)
    if isinstance(point, Mapping):
        return float(point.get("score") or 0.0)
    return 0.0


def _qdrant_points(response: Any) -> list[Any]:
    if response is None:
        return []
    if hasattr(response, "points"):
        return list(getattr(response, "points") or [])
    if isinstance(response, tuple) and response:
        return list(response[0] or [])
    if isinstance(response, list):
        return response
    return []


external_retriever = ExternalRetrieverFacade()


__all__ = [
    "ExternalDocument",
    "ExternalRetrievedDocument",
    "ExternalRetrieverFacade",
    "HashEmbeddingProvider",
    "InMemoryExternalRetriever",
    "OpenAIEmbeddingProvider",
    "QdrantExternalRetriever",
    "_bm25_lexical_scores",
    "_build_embedding_provider",
    "_business_signal_score",
    "_chunk_document",
    "external_retriever",
]
