"""직전 콜 핵심 문장 기반 대조.

`TranscriptDiffService` 가 직전 콜의 핵심 문장(`TranscriptStatementService` 가 적재 시 저장한 원문
문장)을 찾았을 때 이 모듈로 대조한다.

기존 방식은 발언 단위 청크를 검색해 360자로 자른 발췌를 LLM 에 넘기고, LLM 이 "직전 발언" 을 직접
써서 돌려줬다. 그래서 직전 발언이 원문에 없는 문장이 되거나 숫자가 잘려 나가는 일이 잦았다.
여기서는 LLM 이 **문장 번호만** 고르고, 결과의 `prior_claim` 은 저장된 원문 문장을 그대로 쓴다.

호출 수: 관련 문장이 하나도 없으면 LLM 을 부르지 않는다. 관련 여부는 주제와 단어 겹침으로 판정한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Sequence

try:
    from config import get_settings
    from core.gemini_client import gemini_client
    from models.transcript_statement_models import KeyStatement
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from ..core.gemini_client import gemini_client
    from ..models.transcript_statement_models import KeyStatement


logger = logging.getLogger(__name__)

#: 실측(WMT Q2 24구간)에서 응답은 로컬 2~6초, 시연 서버 4~7초였다. backend 는 대조를 자막과 별도
#: 스레드에서 한 구간씩 차례로 보내므로(읽기 제한 50초), 구간 간격(시연 스크립트 15초)을 넘지 않으면
#: 대기열이 쌓이지 않는다.
LLM_TIMEOUT_SECONDS = 15.0
LLM_MAX_OUTPUT_TOKENS = 1024

#: LLM 에 보여 줄 직전 콜 문장 수 상한. 관련도 순으로 자른다.
MAX_CANDIDATES = 12
MAX_ITEMS = 3
#: 한 항목이 가리킬 수 있는 직전 문장 수.
MAX_STATEMENTS_PER_ITEM = 2

CHANGE_TYPES = {"improved", "weakened", "unchanged", "mixed", "new_claim"}

#: 대조 서비스의 주제(현재 발언 쪽, 키워드로 판정) → 핵심 문장 주제(직전 콜 쪽, 추출 시 LLM 이 판정).
DIFF_TO_STATEMENT_TOPICS: dict[str, set[str]] = {
    "guidance": {"guidance", "profit"},
    "margin": {"margin", "profit", "cost"},
    "demand": {"revenue", "segment"},
    "capex": {"capital"},
    "supply": {"cost", "risk"},
    "competition": {"strategy", "risk"},
    "revenue": {"revenue", "segment"},
}

#: 겹침 판정에서 뺄 단어. 어느 문장에나 나와 관련도를 부풀린다.
_STOPWORDS = {
    "the", "and", "we", "our", "of", "to", "in", "for", "that", "this", "with", "on", "is", "are", "was",
    "were", "be", "as", "it", "at", "by", "from", "have", "has", "an", "will", "would", "can", "about",
    "year", "quarter", "quarters", "we're", "we've", "us", "you", "they", "their", "which", "also", "but",
    "or", "so", "not", "more", "than", "into", "over", "very", "really", "just", "all", "some", "there",
    "been", "being", "had", "do", "did", "what", "when", "how", "its", "it's", "continue", "continued",
    "think", "see", "expect", "going", "well", "first", "second", "third", "fourth",
    # 숫자 단위 · 회계 용어. 어느 수치 문장에나 붙어 서로 무관한 문장을 이어 준다.
    "billion", "million", "percent", "basis", "point", "fiscal", "company", "business", "full", "half",
}

#: gemini_client 가 호출 실패 시 예외 대신 돌려주는 폴백 JSON 의 표식.
_GEMINI_FALLBACK_RATIONALE = "Gemini fallback response"
_QUOTE_TABLE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_TOKEN = re.compile(r"[a-z0-9][a-z0-9.%']*[a-z0-9%]|[a-z0-9]")
#: 숫자 토큰 중 소수점이나 %가 있는 것만 남긴다. 연도 · 정수(2026, 1)는 무관한 문장끼리도 흔히 겹친다.
_MEANINGFUL_NUMBER = re.compile(r"\d[\d.]*(?:\.\d+%?|%)")
#: current_claim 이 이보다 짧으면 원문에 있어도 받지 않는다("EPS" 같은 단어 하나는 대조할 주장이 아니다).
MIN_CURRENT_CLAIM_CHARS = 15


class StatementDiffError(Exception):
    """LLM 호출 실패 · 시간 초과 · 응답 형식 오류."""


def select_candidates(
    statements: Sequence[KeyStatement],
    *,
    current_chunk: str,
    diff_topics: Sequence[str],
) -> list[KeyStatement]:
    """현재 발언과 견줄 만한 직전 콜 문장을 고른다. 콜 안의 순서로 돌려준다.

    주제가 대응하면서 단어가 하나 이상 겹치거나, 주제와 무관하게 단어가 두 개 이상 겹치는 문장만 남긴다.
    """
    current_tokens = _content_tokens(current_chunk)
    if not current_tokens:
        return []
    wanted_topics = set().union(*(DIFF_TO_STATEMENT_TOPICS.get(topic, set()) for topic in diff_topics))
    scored: list[tuple[int, KeyStatement]] = []
    for statement in statements:
        overlap = len(current_tokens & _content_tokens(statement.text))
        topic_match = statement.topic in wanted_topics
        if (topic_match and overlap >= 1) or overlap >= 2:
            scored.append((overlap + (2 if topic_match else 0), statement))
    scored.sort(key=lambda pair: (-pair[0], pair[1].order))
    return sorted((statement for _, statement in scored[:MAX_CANDIDATES]), key=lambda s: s.order)


async def compare(
    *,
    ticker: str,
    current_chunk: str,
    candidates: Sequence[KeyStatement],
    previous_document: dict[str, Any],
    llm_client=gemini_client,
    timeout_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """LLM 이 고른 문장 번호로 대조 항목을 만든다. (항목, 경고) 를 돌려준다.

    LLM 이 실패하면 StatementDiffError. 항목이 비는 것은 실패가 아니다(견줄 문장이 없다는 판단).
    """
    settings = get_settings()
    model = settings.gemini_primary_model or settings.gemini_model_fast
    prompt = build_prompt(ticker=ticker, current_chunk=current_chunk, candidates=candidates)
    config = {
        "response_mime_type": "application/json",
        "temperature": 0.1,
        "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
        "route_profile": "economy",
    }
    try:
        usage = await asyncio.wait_for(
            llm_client.generate_content_with_metadata(model=model, contents=prompt, config=config),
            timeout=timeout_seconds or LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise StatementDiffError("llm_timeout") from exc
    except Exception as exc:
        raise StatementDiffError(f"llm_failed:{type(exc).__name__}") from exc
    raw = str(usage.text or "")
    if _is_gemini_fallback(raw):
        _forget_cached(llm_client, model=model, prompt=prompt, config=config)
        raise StatementDiffError("llm_failed:gemini_fallback")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise StatementDiffError("invalid_response") from exc
    raw_items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_items, list):
        raise StatementDiffError("invalid_response")
    return normalize_items(raw_items, current_chunk=current_chunk, candidates=candidates, previous_document=previous_document)


def build_prompt(*, ticker: str, current_chunk: str, candidates: Sequence[KeyStatement]) -> str:
    numbered = "\n".join(
        f"[{number}] ({statement.topic}; {statement.speaker or 'management'}) {statement.text}"
        for number, statement in enumerate(candidates, start=1)
    )
    return f"""You compare what {ticker} management says on the live earnings call with what they said on the previous call.

Live call excerpt (current_chunk):
{_normalize(current_chunk)}

Previous call statements, quoted verbatim:
{numbered}

For each point in current_chunk that is directly comparable with a previous statement (the same metric, \
guidance item, segment or initiative), return one item. At most {MAX_ITEMS} items.
- "prior": the numbers of the previous statements it compares with (1 or 2). Use only numbers listed above.
- "current_claim": the exact words from current_chunk that make the point. Copy them; do not paraphrase.
- "topic": a short English label such as guidance, revenue, margin, eps, ecommerce.
- "change_type": improved, weakened, unchanged or mixed.
- "summary_ko": one Korean sentence on what changed. Include the numbers from both calls when there are any.
- "confidence": 0 to 1, how sure you are that the two are about the same thing.
- "risk_score": 0 to 1, how negative the change is for the stock.
Topic overlap alone is not enough. Skip points whose previous statement is about a different metric, segment or \
period; do not return them as mixed.
Return {{"items": []}} if nothing is directly comparable.

Return JSON only: {{"items": [{{"prior": [2], "current_claim": "...", "topic": "guidance", "change_type": "improved", \
"summary_ko": "...", "confidence": 0.8, "risk_score": 0.2}}]}}"""


def normalize_items(
    raw_items: Sequence[Any],
    *,
    current_chunk: str,
    candidates: Sequence[KeyStatement],
    previous_document: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """LLM 응답을 대조 항목으로 바꾼다. 직전 문장 번호가 올바르지 않은 항목은 버린다."""
    items: list[dict[str, Any]] = []
    dropped = 0
    paraphrased = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        selected = _selected_statements(raw.get("prior"), candidates)
        if not selected:
            dropped += 1
            continue
        current_claim = _source_span(raw.get("current_claim"), current_chunk)
        if current_claim is None:
            # 현재 발언은 화면에서 원문 옆에 놓인다. 바꿔 쓴 문장이면 원문 토막으로 대신한다.
            paraphrased += 1
            current_claim = _clip(current_chunk, 320)
        change_type = str(raw.get("change_type") or "mixed").strip().lower()
        if change_type == "new_claim":
            # 견줄 직전 발언이 없다는 판정인데 직전 문장을 붙였다. 다른 지표를 억지로 짝지은 경우였다.
            dropped += 1
            continue
        items.append(
            {
                "topic": str(raw.get("topic") or selected[0].topic).strip()[:48] or selected[0].topic,
                "change_type": change_type if change_type in CHANGE_TYPES else "mixed",
                "summary_ko": _clip(str(raw.get("summary_ko") or ""), 320) or "직전 콜의 같은 주제 발언과 대조했습니다.",
                "current_claim": current_claim,
                # 저장된 원문 문장만 쓴다. LLM 이 쓴 문장은 받지 않는다.
                "prior_claim": " … ".join(statement.text for statement in selected),
                "confidence": _clamp(raw.get("confidence"), default=0.55),
                "risk_score": _clamp(raw.get("risk_score"), default=0.35),
                "evidence": [_evidence(statement, previous_document) for statement in selected],
            }
        )
        if len(items) >= MAX_ITEMS:
            break
    warnings: list[str] = []
    if dropped:
        warnings.append(f"historical_transcript_diff_items_dropped:{dropped}")
    if paraphrased:
        warnings.append(f"historical_transcript_diff_current_claim_replaced:{paraphrased}")
    return items, warnings


def _source_span(claim: Any, current_chunk: str) -> str | None:
    """LLM 이 옮긴 구절을 현재 발언 원문에서 찾아 원문 그대로 돌려준다. 없으면 None.

    대소문자 · 따옴표 모양만 다른 것은 같은 구절로 본다. 돌려주는 값은 원문 쪽 글자다.
    """
    wanted = _normalize(claim).lower()
    if len(wanted) < MIN_CURRENT_CLAIM_CHARS:
        return None
    source = _normalize(current_chunk)
    start = source.lower().find(wanted)
    if start < 0:
        return None
    return source[start : start + len(wanted)]


def _selected_statements(value: Any, candidates: Sequence[KeyStatement]) -> list[KeyStatement]:
    numbers = value if isinstance(value, list) else [value]
    selected: list[KeyStatement] = []
    for number in numbers:
        if isinstance(number, bool):
            continue
        try:
            parsed = float(str(number).strip().lstrip("[").rstrip("]"))
        except (TypeError, ValueError):
            continue
        if not parsed.is_integer():
            continue
        index = int(parsed) - 1
        if 0 <= index < len(candidates) and candidates[index] not in selected:
            selected.append(candidates[index])
    return sorted(selected[:MAX_STATEMENTS_PER_ITEM], key=lambda s: s.order)


def _evidence(statement: KeyStatement, previous_document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": statement.document_id,
        "source": statement.document_id.split(":", 1)[0],
        "title": previous_document.get("title"),
        "published_at": str(previous_document.get("published_at") or ""),
        "source_url": previous_document.get("source_url"),
        "snippet": statement.text,
        "relevance_score": None,
        "confidence_score": None,
        "statement_id": statement.statement_id,
        "speaker": statement.speaker,
        "statement_topic": statement.topic,
    }


def _content_tokens(text: str) -> set[str]:
    # 하이픈은 단어 경계로 본다("full-year" 와 "full year" 가 같게).
    tokens = _TOKEN.findall(_normalize(text).lower().replace("-", " "))
    result: set[str] = set()
    for token in tokens:
        if any(c.isdigit() for c in token):
            if _MEANINGFUL_NUMBER.fullmatch(token):
                result.add(token)
            continue
        token = _stem(token)
        if len(token) > 2 and token not in _STOPWORDS:
            result.add(token)
    return result


def _stem(token: str) -> str:
    """소유격과 복수형 s 만 뗀다("walmart's" → "walmart", "margins" → "margin")."""
    if token.endswith("'s"):
        token = token[:-2]
    token = token.rstrip("'")
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    return token


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").translate(_QUOTE_TABLE).split())


def _clip(text: str, limit: int) -> str:
    normalized = _normalize(text)
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def _clamp(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return round(max(0.0, min(1.0, parsed)), 4)


def _is_gemini_fallback(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("rationale") == _GEMINI_FALLBACK_RATIONALE


def _forget_cached(llm_client: Any, *, model: str, prompt: str, config: dict) -> None:
    """gemini_client 는 폴백 응답도 캐시한다. 지우지 않으면 같은 요청이 계속 같은 실패를 돌려받는다."""
    cache = getattr(llm_client, "_response_cache", None)
    cache_key = getattr(llm_client, "_cache_key", None)
    if isinstance(cache, dict) and callable(cache_key):
        cache.pop(cache_key(model, prompt, config), None)


__all__ = ["StatementDiffError", "compare", "select_candidates"]
