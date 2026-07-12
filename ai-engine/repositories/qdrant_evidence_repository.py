from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
from typing import Any, Iterable, Mapping, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

try:
    from core.external_retriever import HashEmbeddingProvider, OpenAIEmbeddingProvider
    from models.evidence_models import (
        EvidenceBackend,
        EvidenceCitation,
        EvidenceDocument,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        EvidenceSourceType,
    )
except ImportError:  # pragma: no cover
    from ..core.external_retriever import HashEmbeddingProvider, OpenAIEmbeddingProvider
    from ..models.evidence_models import (
        EvidenceBackend,
        EvidenceCitation,
        EvidenceDocument,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        EvidenceSourceType,
    )


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


def _clip(value: str, limit: int = 360) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


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
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


def _parse_embedding_dimension(dimension: Any, default: int = 256) -> int:
    try:
        parsed = int(dimension)
    except (TypeError, ValueError):
        parsed = default
    return max(32, parsed)


def _chunk_text(text: str, *, max_chars: int = 1200, overlap_chars: int = 160) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]
    chunks: list[str] = []
    start = 0
    step = max(1, max_chars - max(0, min(overlap_chars, max_chars - 1)))
    while start < len(normalized):
        chunk = normalized[start : start + max_chars].strip()
        if chunk:
            chunks.append(chunk)
        if start + max_chars >= len(normalized):
            break
        start += step
    return chunks


def _speaker_turn_entries(
    document: EvidenceDocument,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[dict[str, Any]]:
    turns = document.metadata.get("speaker_turns")
    if document.source_type != EvidenceSourceType.EARNINGS_CALL or not isinstance(turns, list):
        return []
    entries: list[dict[str, Any]] = []
    for turn_index, raw_turn in enumerate(turns):
        if not isinstance(raw_turn, Mapping):
            continue
        speaker = " ".join(str(raw_turn.get("speaker") or "").split())
        text = " ".join(str(raw_turn.get("text") or "").split())
        if not text:
            continue
        for turn_chunk_index, chunk in enumerate(_chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)):
            entries.append(
                {
                    "chunk_text": chunk,
                    "speaker": speaker or None,
                    "turn_index": turn_index,
                    "turn_chunk_index": turn_chunk_index,
                }
            )
    return entries


def _document_chunk_entries(
    document: EvidenceDocument,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[dict[str, Any]]:
    speaker_entries = _speaker_turn_entries(document, max_chars=max_chars, overlap_chars=overlap_chars)
    if speaker_entries:
        return speaker_entries
    return [
        {"chunk_text": chunk}
        for chunk in _chunk_text(document.content, max_chars=max_chars, overlap_chars=overlap_chars)
    ]


def _as_datetime(value: datetime | date | int | float | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    return None


def _published_at_epoch(value: datetime | date | int | float | None) -> int | None:
    parsed = _as_datetime(value)
    return int(parsed.timestamp()) if parsed is not None else None


def _published_at_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC).date().isoformat()
    return str(value)


def _source_type(value: Any) -> EvidenceSourceType:
    raw = value.value if hasattr(value, "value") else str(value or EvidenceSourceType.OTHER.value)
    try:
        return EvidenceSourceType(raw)
    except ValueError:
        return EvidenceSourceType.OTHER


def _payload_value(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None)
    if payload is None and isinstance(point, Mapping):
        payload = point.get("payload")
    return dict(payload or {})


def _score_value(point: Any) -> float:
    if hasattr(point, "score"):
        return float(getattr(point, "score") or 0.0)
    if isinstance(point, Mapping):
        return float(point.get("score") or 0.0)
    return 0.0


def _extract_points(response: Any) -> list[Any]:
    if response is None:
        return []
    if hasattr(response, "points"):
        return list(getattr(response, "points") or [])
    if isinstance(response, tuple) and response:
        return list(response[0] or [])
    if isinstance(response, list):
        return response
    return []


def _point_id(chunk_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"earningwhisperer:evidence:{chunk_id}"))


def _json_ready(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _metadata_payload(document: EvidenceDocument) -> dict[str, Any]:
    metadata = dict(document.metadata or {})
    if not metadata:
        return {}
    if metadata.get("speaker_turns") is not None:
        metadata.pop("speaker_turns", None)
        return _json_ready(metadata) if metadata else {}
    return _json_ready(metadata)


class QdrantEvidenceRepository:
    """Qdrant-backed evidence repository for transcript/RAG documents."""

    backend = EvidenceBackend.QDRANT

    def __init__(
        self,
        *,
        client: Any | None = None,
        url: str = "",
        path: str = "",
        collection_name: str = "earningwhisperer_evidence",
        store_name: str = "evidence",
        embedding_provider: EmbeddingProvider | None = None,
        embedding_dimension: int = 256,
        chunk_size_chars: int = 1200,
        chunk_overlap_chars: int = 160,
    ) -> None:
        self.collection_name = collection_name
        self.store_name = str(store_name or "evidence")
        self.embedding_dimension = _parse_embedding_dimension(embedding_dimension)
        self.embedding_provider = embedding_provider or HashEmbeddingProvider(dimension=self.embedding_dimension)
        self.chunk_size_chars = max(400, int(chunk_size_chars))
        self.chunk_overlap_chars = max(0, int(chunk_overlap_chars))
        self.client = client or self._build_client(url=url, path=path)
        self._ensure_collection()

    @classmethod
    def from_settings(
        cls,
        *,
        settings: Any,
        collection_name: str | None = None,
        store_name: str = "evidence",
    ) -> "QdrantEvidenceRepository":
        provider_name = str(getattr(settings, "embedding_provider", "hash") or "hash").strip().lower()
        dimension = _parse_embedding_dimension(getattr(settings, "embedding_dimension", 256))
        if provider_name == "openai":
            provider = OpenAIEmbeddingProvider(
                model=str(getattr(settings, "embedding_model", "text-embedding-3-small")),
                dimension=dimension,
            )
        else:
            provider = HashEmbeddingProvider(dimension=dimension)
        return cls(
            url=str(getattr(settings, "qdrant_url", "") or ""),
            path=str(getattr(settings, "qdrant_path", "") or ""),
            collection_name=collection_name or str(getattr(settings, "qdrant_collection_name", "earningwhisperer_evidence") or "earningwhisperer_evidence"),
            store_name=store_name,
            embedding_provider=provider,
            embedding_dimension=dimension,
            chunk_size_chars=int(getattr(settings, "external_chunk_size_chars", 1200)),
            chunk_overlap_chars=int(getattr(settings, "external_chunk_overlap_chars", 160)),
        )

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
                size=self.embedding_dimension,
                distance=models.Distance.COSINE,
            ),
        )

    def add_documents(self, documents: Iterable[EvidenceDocument]) -> int:
        points: list[Any] = []
        accepted_documents = 0
        for document in documents:
            content = " ".join(str(document.content or "").split())
            if not content:
                continue
            doc_id = _document_id(document)
            chunk_entries = _document_chunk_entries(
                document,
                max_chars=self.chunk_size_chars,
                overlap_chars=self.chunk_overlap_chars,
            )
            chunk_texts = [str(entry.get("chunk_text") or "") for entry in chunk_entries]
            vectors = self.embedding_provider.embed_texts(chunk_texts)
            published_epoch = _published_at_epoch(document.published_at)
            published_text = _published_at_text(document.published_at)
            metadata_payload = _metadata_payload(document)
            for index, (entry, vector) in enumerate(zip(chunk_entries, vectors)):
                chunk = str(entry.get("chunk_text") or "")
                if "turn_index" in entry:
                    chunk_id = f"{doc_id}#turn-{entry['turn_index']}#chunk-{entry.get('turn_chunk_index', 0)}"
                else:
                    chunk_id = f"{doc_id}#chunk-{index}"
                payload = {
                    "store": self.store_name,
                    "document_id": doc_id,
                    "chunk_id": chunk_id,
                    "ticker": str(document.ticker or "").upper(),
                    "source_type": document.source_type.value,
                    "source": document.source,
                    "title": document.title,
                    "source_url": document.source_url,
                    "published_at_epoch": published_epoch,
                    "published_at_text": published_text,
                    "provider": str(document.metadata.get("provider") or document.source or "unknown"),
                    "provider_id": str(document.metadata.get("provider_id") or doc_id),
                    "fiscal_quarter": document.metadata.get("fiscal_quarter"),
                    "chunk_index": index,
                    "chunk_text": chunk,
                    "reliability_score": float(document.reliability_score),
                }
                if entry.get("speaker"):
                    payload["speaker"] = entry["speaker"]
                if "turn_index" in entry:
                    payload["turn_index"] = entry["turn_index"]
                if document.metadata.get("speaker_turn_count") is not None:
                    payload["speaker_turn_count"] = document.metadata.get("speaker_turn_count")
                if metadata_payload and self.store_name != "transcript":
                    payload["metadata_json"] = metadata_payload
                points.append(self._point_struct(id=_point_id(chunk_id), vector=vector, payload=payload))
            accepted_documents += 1
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
        return accepted_documents

    @staticmethod
    def _point_struct(*, id: str, vector: Sequence[float], payload: Mapping[str, Any]) -> Any:
        try:
            from qdrant_client import models
        except ImportError:
            return {"id": id, "vector": list(vector), "payload": dict(payload)}
        return models.PointStruct(id=id, vector=list(vector), payload=dict(payload))

    def search(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        query_vector = self.embedding_provider.embed_texts([request.query or request.ticker])[0]
        filters = [
            self._match_filter("store", self.store_name),
            self._match_filter("ticker", request.ticker.upper()),
        ]
        if request.source_types:
            filters.append(self._any_filter("source_type", [item.value for item in request.source_types]))
        points = self._query(query_vector, limit=request.top_k, filters=filters)
        citations = [self._point_to_citation(point) for point in points]
        coverage = self._coverage_score(citations)
        confidence_adjustment = self._confidence_adjustment(coverage, citations)
        warnings: list[str] = []
        if not citations:
            warnings.append("no_retrieved_evidence")
        elif coverage < 0.35:
            warnings.append("weak_retrieved_evidence")
        return EvidenceRetrievalResult(
            ticker=request.ticker.upper(),
            query=request.query,
            backend=EvidenceBackend.QDRANT,
            evidence=citations,
            coverage_score=coverage,
            confidence_adjustment=confidence_adjustment,
            evidence_context=self.build_prompt_context(citations),
            missing_evidence=not citations,
            warnings=warnings,
        )

    def find_latest_transcript(self, *, ticker: str, before: datetime | None = None) -> dict[str, Any] | None:
        before_epoch = int((before or datetime.now(UTC)).timestamp())
        filters = [
            self._match_filter("store", self.store_name),
            self._match_filter("ticker", ticker.upper()),
            self._match_filter("source_type", EvidenceSourceType.EARNINGS_CALL.value),
        ]
        points = self._scroll(filters=filters, limit=256)
        latest: dict[str, Any] | None = None
        for point in points:
            payload = _payload_value(point)
            doc_id = str(payload.get("document_id") or "")
            if not doc_id:
                continue
            published_epoch = int(payload.get("published_at_epoch") or 0)
            if published_epoch and published_epoch >= before_epoch:
                continue
            candidate = {
                "document_id": doc_id,
                "ticker": str(payload.get("ticker") or ticker).upper(),
                "title": payload.get("title"),
                "source_url": payload.get("source_url"),
                "published_at": payload.get("published_at_text"),
                "published_at_epoch": published_epoch,
                "fiscal_quarter": payload.get("fiscal_quarter"),
                "metadata_json": payload.get("metadata_json") or {},
            }
            if latest is None or candidate["published_at_epoch"] > int(latest.get("published_at_epoch") or 0):
                latest = candidate
        return latest

    def search_prior_transcript_chunks(
        self,
        *,
        ticker: str,
        query: str,
        document_id: str,
        top_k: int = 3,
    ) -> list[EvidenceCitation]:
        query_vector = self.embedding_provider.embed_texts([query])[0]
        filters = [
            self._match_filter("store", self.store_name),
            self._match_filter("ticker", ticker.upper()),
            self._match_filter("source_type", EvidenceSourceType.EARNINGS_CALL.value),
            self._match_filter("document_id", document_id),
        ]
        return [self._point_to_citation(point) for point in self._query(query_vector, limit=top_k, filters=filters)]

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
            return _extract_points(response)
        response = self.client.search(
            collection_name=self.collection_name,
            query_vector=list(query_vector),
            query_filter=query_filter,
            limit=int(limit),
            with_payload=True,
        )
        return _extract_points(response)

    def _scroll(self, *, filters: Sequence[Any], limit: int) -> list[Any]:
        response = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=self._filter(filters),
            limit=int(limit),
            with_payload=True,
            with_vectors=False,
        )
        return _extract_points(response)

    @staticmethod
    def _filter(filters: Sequence[Any]) -> Any:
        try:
            from qdrant_client import models
        except ImportError:
            return {"must": list(filters)}
        return models.Filter(must=list(filters))

    @staticmethod
    def _match_filter(key: str, value: Any) -> Any:
        try:
            from qdrant_client import models
        except ImportError:
            return {"key": key, "match": {"value": value}}
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    @staticmethod
    def _any_filter(key: str, values: Sequence[Any]) -> Any:
        try:
            from qdrant_client import models
        except ImportError:
            return {"key": key, "match": {"any": list(values)}}
        return models.FieldCondition(key=key, match=models.MatchAny(any=list(values)))

    @staticmethod
    def _range_filter(key: str, *, lt: int | None = None) -> Any:
        try:
            from qdrant_client import models
        except ImportError:
            return {"key": key, "range": {"lt": lt}}
        return models.FieldCondition(key=key, range=models.Range(lt=lt))

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
            lines.append(
                f"- {citation.source_type.value} | {citation.source} | {citation.published_at or 'unknown-date'} | "
                f"confidence={citation.confidence_score:.2f} | {citation.snippet}"
            )
        return "\n".join(lines)

    @staticmethod
    def _coverage_score(citations: list[EvidenceCitation]) -> float:
        if not citations:
            return 0.0
        top = citations[:5]
        weighted = sum(item.confidence_score for item in top) / max(1, len(top))
        diversity = len({item.source_type for item in top}) / 5.0
        return round(max(0.0, min(1.0, 0.82 * weighted + 0.18 * diversity)), 4)

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
    def _point_to_citation(point: Any) -> EvidenceCitation:
        payload = _payload_value(point)
        score = max(0.0, min(1.0, _score_value(point)))
        reliability = max(0.0, min(1.0, float(payload.get("reliability_score") or 0.6)))
        confidence = max(0.0, min(1.0, 0.70 * score + 0.30 * reliability))
        metadata = dict(payload.get("metadata_json") or {})
        for key in ("speaker", "turn_index", "speaker_turn_count"):
            if key in payload:
                metadata[key] = payload[key]
        return EvidenceCitation(
            document_id=str(payload.get("document_id") or payload.get("chunk_id") or ""),
            ticker=str(payload.get("ticker") or "").upper() or None,
            source_type=_source_type(payload.get("source_type")),
            source=str(payload.get("source") or "unknown"),
            title=payload.get("title"),
            published_at=payload.get("published_at_text"),
            source_url=payload.get("source_url"),
            snippet=_clip(str(payload.get("chunk_text") or "")),
            relevance_score=round(score, 4),
            reliability_score=round(reliability, 4),
            confidence_score=round(confidence, 4),
            metadata=metadata,
        )


__all__ = ["QdrantEvidenceRepository"]
