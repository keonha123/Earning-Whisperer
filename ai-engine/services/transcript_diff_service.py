from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

try:
    from config import get_settings
    from core.gemini_client import gemini_client
    from models.evidence_models import EvidenceCitation
    from models.request_models import SourceType
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from ..core.gemini_client import gemini_client
    from ..models.evidence_models import EvidenceCitation
    from ..models.request_models import SourceType


TOPIC_TERMS: dict[str, set[str]] = {
    "guidance": {"guidance", "outlook", "forecast", "raise", "raised", "cut", "lowered", "full-year", "fy"},
    "margin": {"margin", "gross", "operating", "profitability", "cost", "pricing", "bps"},
    "demand": {"demand", "orders", "bookings", "backlog", "customer", "customers"},
    "capex": {"capex", "capital", "investment", "spend", "spending", "capacity"},
    "supply": {"supply", "inventory", "shortage", "capacity", "component", "foundry"},
    "competition": {"competition", "competitor", "share", "pricing", "market"},
    "revenue": {"revenue", "sales", "growth", "topline"},
}
POSITIVE = {
    "raise",
    "raised",
    "raising",
    "strong",
    "stronger",
    "improve",
    "improved",
    "growth",
    "accelerate",
    "accelerated",
    "higher",
    "beat",
    "robust",
    "expanded",
    "expansion",
}
NEGATIVE = {
    "cut",
    "lower",
    "lowered",
    "weak",
    "weaker",
    "decline",
    "declined",
    "pressure",
    "slow",
    "slowed",
    "miss",
    "headwind",
    "compressed",
    "compression",
}
CHANGE_TYPES = {"improved", "weakened", "unchanged", "mixed", "new_claim"}


class TranscriptDiffService:
    """Compare a live earnings-call chunk with the most recent prior transcript."""

    min_current_tokens = 8
    min_relevance_score = 0.68
    min_confidence_score = 0.72

    def __init__(self, repository) -> None:
        self.repository = repository

    async def analyze(
        self,
        *,
        ticker: str,
        current_chunk: str,
        source_type: SourceType,
        request_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if source_type != SourceType.EARNINGS_CALL:
            return None
        normalized_ticker = ticker.upper()
        metadata = request_metadata or {}
        if not hasattr(self.repository, "find_latest_transcript") or not hasattr(self.repository, "search_prior_transcript_chunks"):
            return _unavailable(normalized_ticker, "transcript_repository_not_configured")

        previous = self.repository.find_latest_transcript(
            ticker=normalized_ticker,
            before=_metadata_timestamp(metadata),
        )
        if previous is None:
            return _unavailable(normalized_ticker, "previous_transcript_not_found")

        document_id = str(previous.get("document_id") or "")
        topics = _topics_for(current_chunk)
        if not _is_material_chunk(current_chunk, topics):
            return {
                "available": True,
                "ticker": normalized_ticker,
                "previous_document": _previous_document(previous),
                "items": [],
                "warnings": ["current_chunk_not_material"],
            }

        citations = self.repository.search_prior_transcript_chunks(
            ticker=normalized_ticker,
            query=_query_for(normalized_ticker, current_chunk, topics),
            document_id=document_id,
            top_k=5,
        )
        gated = _gate_citations(citations)
        if not gated:
            return {
                "available": True,
                "ticker": normalized_ticker,
                "previous_document": _previous_document(previous),
                "items": [],
                "warnings": ["weak_prior_transcript_evidence"],
            }

        warnings: list[str] = []
        try:
            items = await self._generate_llm_diff(
                ticker=normalized_ticker,
                current_chunk=current_chunk,
                topics=topics,
                citations=gated,
            )
        except Exception as exc:
            warnings.append("historical_transcript_diff_llm_failed")
            warnings.append(str(exc)[:160])
            items = _fallback_items(current_chunk=current_chunk, citations=gated, topics=topics)

        if not items:
            warnings.append("historical_transcript_diff_empty")
            items = _fallback_items(current_chunk=current_chunk, citations=gated, topics=topics)

        return {
            "available": True,
            "ticker": normalized_ticker,
            "previous_document": _previous_document(previous),
            "items": items[:3],
            "warnings": warnings,
        }

    async def _generate_llm_diff(
        self,
        *,
        ticker: str,
        current_chunk: str,
        topics: list[str],
        citations: list[EvidenceCitation],
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        model = settings.gemini_primary_model or settings.gemini_model_fast
        prompt = _build_prompt(ticker=ticker, current_chunk=current_chunk, topics=topics, citations=citations)
        usage = await gemini_client.generate_content_with_metadata(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": 512,
                "route_profile": "economy",
            },
        )
        parsed = json.loads(usage.text)
        raw_items = parsed.get("items") if isinstance(parsed, dict) else None
        if not isinstance(raw_items, list):
            raise ValueError("LLM transcript diff response must contain items[]")
        return _normalize_llm_items(raw_items, citations)


def _unavailable(ticker: str, warning: str) -> dict[str, Any]:
    return {
        "available": False,
        "ticker": ticker,
        "items": [],
        "warnings": [warning],
    }


def _metadata_timestamp(metadata: dict[str, Any]) -> datetime | None:
    value = metadata.get("timestamp") or metadata.get("event_time") or metadata.get("original_timestamp")
    if value is None:
        return None
    try:
        numeric = float(value)
        return datetime.fromtimestamp(numeric, tz=UTC)
    except (TypeError, ValueError):
        return None


def _previous_document(previous: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": previous.get("document_id"),
        "title": previous.get("title"),
        "published_at": str(previous.get("published_at") or ""),
        "fiscal_quarter": previous.get("fiscal_quarter"),
        "source_url": previous.get("source_url"),
    }


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-z0-9-]{2,}", text or "")}


def _topics_for(text: str) -> list[str]:
    tokens = _tokens(text)
    scored = [(topic, len(tokens & terms)) for topic, terms in TOPIC_TERMS.items()]
    return [topic for topic, score in sorted(scored, key=lambda item: item[1], reverse=True) if score > 0]


def _is_material_chunk(current_chunk: str, topics: list[str]) -> bool:
    tokens = _tokens(current_chunk)
    if len(tokens) < TranscriptDiffService.min_current_tokens:
        return False
    if topics:
        return True
    return bool((tokens & POSITIVE) or (tokens & NEGATIVE))


def _query_for(ticker: str, current_chunk: str, topics: list[str]) -> str:
    topic_part = " ".join(topics[:4])
    return " ".join(part for part in [ticker, topic_part, current_chunk] if part).strip()


def _gate_citations(citations: list[EvidenceCitation]) -> list[EvidenceCitation]:
    gated: list[EvidenceCitation] = []
    seen: set[str] = set()
    for citation in citations:
        key = " ".join(citation.snippet.lower().split())[:220]
        if key in seen:
            continue
        if citation.relevance_score < TranscriptDiffService.min_relevance_score:
            continue
        if citation.confidence_score < TranscriptDiffService.min_confidence_score:
            continue
        if len(_tokens(citation.snippet)) < 6:
            continue
        seen.add(key)
        gated.append(citation)
    return gated[:5]


def _build_prompt(*, ticker: str, current_chunk: str, topics: list[str], citations: list[EvidenceCitation]) -> str:
    evidence = []
    for idx, citation in enumerate(citations[:5], start=1):
        evidence.append(
            {
                "id": idx,
                "document_id": citation.document_id,
                "published_at": citation.published_at,
                "snippet": citation.snippet,
                "relevance_score": citation.relevance_score,
                "confidence_score": citation.confidence_score,
            }
        )
    return (
        "You compare a live earnings-call statement against prior earnings-call evidence.\n"
        "Use only the supplied current_chunk and prior_evidence. Do not add outside facts.\n"
        "Return strict JSON with key items. Each item must include: topic, change_type, summary_ko, "
        "current_claim, prior_claim, confidence, risk_score, evidence_indices.\n"
        "Allowed change_type values: improved, weakened, unchanged, mixed, new_claim.\n"
        "summary_ko must be concise Korean, one sentence.\n\n"
        f"ticker: {ticker}\n"
        f"topics: {topics[:4]}\n"
        f"current_chunk: {current_chunk}\n"
        f"prior_evidence: {json.dumps(evidence, ensure_ascii=False)}"
    )


def _normalize_llm_items(raw_items: list[Any], citations: list[EvidenceCitation]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        evidence_indices = raw.get("evidence_indices") or [1]
        if not isinstance(evidence_indices, list):
            evidence_indices = [1]
        selected = []
        for index in evidence_indices:
            try:
                citation = citations[int(index) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            selected.append(_citation_payload(citation))
        if not selected:
            selected = [_citation_payload(citations[0])]
        change_type = str(raw.get("change_type") or "mixed").strip().lower()
        if change_type not in CHANGE_TYPES:
            change_type = "mixed"
        items.append(
            {
                "topic": str(raw.get("topic") or "general").strip()[:48] or "general",
                "change_type": change_type,
                "summary_ko": _clip(str(raw.get("summary_ko") or ""), 320) or "과거 발언과 현재 발언의 변화가 제한적으로 감지되었습니다.",
                "current_claim": _clip(str(raw.get("current_claim") or ""), 320),
                "prior_claim": _clip(str(raw.get("prior_claim") or ""), 320),
                "confidence": _clamp_float(raw.get("confidence"), default=0.55),
                "risk_score": _clamp_float(raw.get("risk_score"), default=0.35),
                "evidence": selected,
            }
        )
    return items


def _fallback_items(*, current_chunk: str, citations: list[EvidenceCitation], topics: list[str]) -> list[dict[str, Any]]:
    prior_text = " ".join(item.snippet for item in citations)
    topic = (topics or ["general"])[0]
    return [
        {
            "topic": topic,
            "change_type": _change_type(current_chunk, prior_text),
            "summary_ko": _fallback_summary_ko(topic, current_chunk, prior_text),
            "current_claim": _clip(current_chunk, 320),
            "prior_claim": _clip(citations[0].snippet if citations else "", 320),
            "confidence": round(max((item.confidence_score for item in citations), default=0.45), 4),
            "risk_score": _risk_score(current_chunk, prior_text),
            "evidence": [_citation_payload(item) for item in citations[:3]],
        }
    ]


def _polarity(text: str) -> int:
    tokens = _tokens(text)
    pos = len(tokens & POSITIVE)
    neg = len(tokens & NEGATIVE)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


def _change_type(current: str, previous: str) -> str:
    if not previous:
        return "new_claim"
    current_pol = _polarity(current)
    previous_pol = _polarity(previous)
    if current_pol and previous_pol and current_pol != previous_pol:
        return "weakened" if current_pol < previous_pol else "improved"
    if current_pol == previous_pol and current_pol != 0:
        return "unchanged"
    return "mixed"


def _risk_score(current: str, previous: str) -> float:
    if not previous:
        return 0.35
    current_pol = _polarity(current)
    previous_pol = _polarity(previous)
    if current_pol and previous_pol and current_pol != previous_pol:
        return 0.78
    if current_pol < 0:
        return 0.62
    return 0.22


def _fallback_summary_ko(topic: str, current: str, previous: str) -> str:
    change = _change_type(current, previous)
    labels = {
        "improved": "이전 발언보다 긍정적인 방향으로 개선되었습니다.",
        "weakened": "이전 발언보다 톤이 약해졌거나 부정적으로 바뀌었습니다.",
        "unchanged": "이전 발언과 같은 방향의 메시지가 재확인되었습니다.",
        "mixed": "관련 주제는 유사하지만 변화 방향은 혼재되어 있습니다.",
        "new_claim": "비교 가능한 이전 발언이 부족해 새로운 주장으로 분류됩니다.",
    }
    return f"{topic} 관련 발언은 {labels[change]}"


def _citation_payload(item: EvidenceCitation) -> dict[str, Any]:
    return {
        "document_id": item.document_id,
        "source": item.source,
        "title": item.title,
        "published_at": item.published_at,
        "source_url": item.source_url,
        "snippet": item.snippet,
        "relevance_score": item.relevance_score,
        "confidence_score": item.confidence_score,
    }


def _clip(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return round(max(0.0, min(1.0, parsed)), 4)


__all__ = ["TranscriptDiffService"]
