"""직전 콜 핵심 문장 추출.

직전 분기 콜을 적재할 때 LLM 이 원문을 읽고, 다음 콜과 견줄 가치가 있는 경영진 문장을
**원문 그대로** 골라 주제와 함께 돌려준다. 고른 문장이 원문에 실제로 있는지 코드로
검사하고, 없으면 버린다. 직전 콜 대조의 "직전 발언" 은 여기서 남긴 문장만 쓴다.

LLM 에 "요약" 이 아니라 "복사" 를 시키는 이유: 요약을 저장하면 숫자가 바뀌거나 지어져도
알아챌 방법이 없다. 실측에서 Q1 기존점 매출 4.1% 가 LLM 문장에서 3% 로 바뀌어 나왔다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Sequence

try:
    from config import Settings, get_settings
    from core.gemini_client import gemini_client
    from models.ingestion_models import TranscriptSpeakerTurn
    from models.transcript_statement_models import STATEMENT_TOPICS, KeyStatement
except ImportError:  # pragma: no cover
    from ..config import Settings, get_settings
    from ..core.gemini_client import gemini_client
    from ..models.ingestion_models import TranscriptSpeakerTurn
    from ..models.transcript_statement_models import STATEMENT_TOPICS, KeyStatement


logger = logging.getLogger(__name__)

#: LLM 한 번에 넘기는 원문 분량. 출력(고른 문장 목록)이 출력 상한 안에 들어오도록 나눈다.
BATCH_MAX_CHARS = 12_000

#: 배치 1개 제한 시간. 적재는 콜이 없을 때 돌리는 작업이라 실시간 기능보다 넉넉하게 둔다.
BATCH_TIMEOUT_SECONDS = 90.0

EXTRACTION_MAX_OUTPUT_TOKENS = 4096

#: 동시에 돌릴 배치 수. 무료 등급 분당 15요청 안에서, 콜 1건(약 6배치)을 한 번에 처리하는 정도.
MAX_CONCURRENT_BATCHES = 4

#: LLM 이 고르는 문장 길이. 너무 짧으면 비교할 내용이 없고, 길면 여러 주제가 섞인다.
MIN_STATEMENT_CHARS = 20
MAX_STATEMENT_CHARS = 500

#: 문장 경계까지 넓힌 뒤의 상한. 넓히면 길어지므로 위 상한보다 여유를 둔다.
MAX_EXPANDED_CHARS = 800

#: gemini_client 가 호출 실패(429 · 503 · 키 누락 등) 시 예외 대신 돌려주는 폴백 JSON 의 표식.
_GEMINI_FALLBACK_RATIONALE = "Gemini fallback response"

_QUOTE_TABLE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ExtractionResult:
    statements: list[KeyStatement] = field(default_factory=list)
    #: LLM 이 골랐지만 버린 문장 (원문에 없음 · 경영진 발언이 아님 · 길이 미달 등). 진단용.
    rejected: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


@dataclass(frozen=True)
class _TurnPiece:
    turn_index: int
    speaker: str
    section: str | None
    text: str
    #: 경영진 발언이 아니면(사회자 · 애널리스트 질문) LLM 에 맥락으로만 보여 주고 고르지 못하게 한다.
    management: bool = True


class TranscriptStatementExtractionService:
    def __init__(
        self,
        *,
        llm_client=gemini_client,
        settings: Settings | None = None,
        batch_timeout_seconds: float = BATCH_TIMEOUT_SECONDS,
    ) -> None:
        self.llm_client = llm_client
        self.settings = settings or get_settings()
        self.batch_timeout_seconds = batch_timeout_seconds

    async def extract(
        self,
        *,
        document_id: str,
        ticker: str,
        turns: Sequence[TranscriptSpeakerTurn],
        published_at_epoch: int | None = None,
        fiscal_quarter: str | None = None,
    ) -> ExtractionResult:
        result = ExtractionResult()
        normalized_turns = [_normalize(turn.text) for turn in turns]
        seen: set[str] = set()
        non_management = _non_management_turns(turns)
        if turns and not any(turn.section for turn in turns):
            # 애널리스트 질문은 Q&A 구간 정보로 가려낸다. 구간이 없으면 거를 수 없다.
            result.warnings.append("key_statement_no_section_analyst_filter_off")
        batches = _batches(turns, non_management)
        limiter = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)

        async def run(batch: list[_TurnPiece]) -> str:
            async with limiter:
                return await asyncio.wait_for(self._generate(ticker=ticker, batch=batch), timeout=self.batch_timeout_seconds)

        # 배치끼리는 독립이라 동시에 돌린다. 순서대로 돌리면 적재 응답이 배치 수만큼 늘어난다.
        outcomes = await asyncio.gather(*(run(batch) for batch in batches), return_exceptions=True)
        for batch_index, (batch, outcome) in enumerate(zip(batches, outcomes)):
            where = (document_id, batch_index + 1, len(batches))
            if isinstance(outcome, asyncio.TimeoutError):
                logger.warning("핵심 문장 추출 시간 초과 - document_id=%s batch=%s/%s", *where)
                result.warnings.append(f"key_statement_batch_timeout:{batch_index}")
                continue
            if isinstance(outcome, _LlmCallFailed):
                logger.warning("핵심 문장 추출 LLM 호출 실패 - document_id=%s batch=%s/%s", *where)
                result.warnings.append(f"key_statement_batch_llm_failed:{batch_index}")
                continue
            if isinstance(outcome, BaseException):
                logger.error("핵심 문장 추출 중 예기치 못한 오류 - document_id=%s batch=%s/%s", *where, exc_info=outcome)
                result.warnings.append(f"key_statement_batch_internal_error:{batch_index}")
                continue

            candidates = _parse_candidates(outcome)
            if candidates is None:
                logger.warning("핵심 문장 추출 응답 형식 오류 - document_id=%s batch=%s/%s raw=%.200s", *where, outcome)
                result.warnings.append(f"key_statement_batch_invalid_response:{batch_index}")
                continue

            batch_turns = {piece.turn_index for piece in batch if piece.management}
            for candidate in candidates:
                statement = _verified(candidate, normalized_turns=normalized_turns, allowed_turns=batch_turns)
                if statement is None:
                    result.rejected.append(str(candidate.get("text") if isinstance(candidate, dict) else candidate)[:200])
                    continue
                turn_index, topic, start, text = statement
                if text in seen:
                    continue
                seen.add(text)
                turn = turns[turn_index]
                result.statements.append(
                    KeyStatement(
                        statement_id="",
                        document_id=document_id,
                        ticker=ticker.upper(),
                        order=start,
                        turn_index=turn_index,
                        speaker=" ".join(turn.speaker.split()) or None,
                        section=turn.section,
                        topic=topic,
                        text=text,
                        published_at_epoch=published_at_epoch,
                        fiscal_quarter=fiscal_quarter,
                    )
                )

        # 원문 순서로 정렬한 뒤 번호를 매긴다. 위의 order 는 정렬용으로 잠시 쓴 발언 내 위치다.
        result.statements.sort(key=lambda s: (s.turn_index, s.order))
        result.statements = [s.model_copy(update={"order": i, "statement_id": f"{document_id}#s{i}"}) for i, s in enumerate(result.statements)]
        if result.rejected_count:
            logger.info("고르지 않을 문장을 버렸습니다 - document_id=%s rejected=%s", document_id, result.rejected_count)
        return result

    async def _generate(self, *, ticker: str, batch: list[_TurnPiece]) -> str:
        settings = self.settings
        model = settings.gemini_primary_model or settings.gemini_model_fast
        prompt = _build_prompt(ticker=ticker, batch=batch)
        config = {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "max_output_tokens": EXTRACTION_MAX_OUTPUT_TOKENS,
            "route_profile": "economy",
            "thinking_level": settings.gemini_primary_thinking_level,
        }
        usage = await self.llm_client.generate_content_with_metadata(model=model, contents=prompt, config=config)
        raw = str(usage.text or "")
        if _is_gemini_fallback(raw):
            self._forget_cached(model=model, prompt=prompt, config=config)
            raise _LlmCallFailed()
        return raw

    def _forget_cached(self, *, model: str, prompt: str, config: dict) -> None:
        """gemini_client 응답 캐시에서 폴백 응답을 지운다.

        gemini_client 는 호출 실패 시의 폴백 JSON 도 정상 응답처럼 캐시한다. 지우지 않으면
        같은 원문을 다시 적재해도 Gemini 를 부르지 않고 같은 실패를 돌려받는다.
        """
        cache = getattr(self.llm_client, "_response_cache", None)
        cache_key = getattr(self.llm_client, "_cache_key", None)
        if isinstance(cache, dict) and callable(cache_key):
            cache.pop(cache_key(model, prompt, config), None)


class _LlmCallFailed(Exception):
    """gemini_client 가 호출 실패를 폴백 JSON 으로 감춘 경우."""


def _normalize(text: str) -> str:
    """원문 대조용 정규화. 공백을 합치고 둥근 따옴표 · 긴 대시를 일반 문자로 바꾼다.

    LLM 은 원문의 ’ 를 ' 로 바꿔 복사하는 일이 흔하다. 이것까지 불일치로 보면 정상적인
    인용을 대부분 버리게 된다. 단어나 숫자가 다르면 여전히 불일치다.
    """
    return " ".join(str(text or "").translate(_QUOTE_TABLE).split())


def _non_management_turns(turns: Sequence[TranscriptSpeakerTurn]) -> set[int]:
    """사회자 발언과 애널리스트 질문의 발언 번호.

    적재 요청에는 발화자 역할이 없다. 대신 Q&A 에서 사회자가 다음 질문자를 소개한 직후의
    발언이 애널리스트 질문이라는 순서를 쓴다. 같은 애널리스트가 이어서 묻는 경우도 있어,
    한 번 질문자로 잡힌 이름은 Q&A 안에서 계속 질문자로 본다.

    이걸 거르지 않으면 애널리스트가 질문에서 인용한 숫자("up 3% at Walmart US")가
    경영진의 직전 발언처럼 저장된다. 실측에서 실제로 그렇게 잡혔다.
    """
    excluded: set[int] = set()
    analysts: set[str] = set()
    # 준비 발언을 했거나 Q&A 에서 답한 사람은 경영진이다. 사회자가 Q&A 끝에 CEO 마무리 발언을
    # 소개하는 경우처럼, 사회자 직후라도 경영진이면 질문자로 보지 않는다.
    management: set[str] = set()
    previous_operator = False
    for index, turn in enumerate(turns):
        speaker = " ".join(turn.speaker.split()).lower()
        is_operator = speaker == "operator"
        in_qa = (turn.section or "").lower() in {"qa", "q&a", "question_and_answer"}
        if is_operator:
            excluded.add(index)
        elif not in_qa:
            management.add(speaker)
        elif speaker in analysts or (previous_operator and speaker not in management):
            excluded.add(index)
            analysts.add(speaker)
        else:
            management.add(speaker)
        previous_operator = is_operator
    return excluded


def _batches(turns: Sequence[TranscriptSpeakerTurn], non_management: set[int] | None = None) -> list[list[_TurnPiece]]:
    non_management = non_management or set()
    pieces: list[_TurnPiece] = []
    for index, turn in enumerate(turns):
        text = _normalize(turn.text)
        if not text:
            continue
        speaker = " ".join(turn.speaker.split())
        for part in _split_long(text, BATCH_MAX_CHARS):
            pieces.append(
                _TurnPiece(
                    turn_index=index,
                    speaker=speaker,
                    section=turn.section,
                    text=part,
                    management=index not in non_management,
                )
            )

    batches: list[list[_TurnPiece]] = []
    current: list[_TurnPiece] = []
    size = 0
    for piece in pieces:
        if current and size + len(piece.text) > BATCH_MAX_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(piece)
        size += len(piece.text)
    if current:
        batches.append(current)
    return batches


def _split_long(text: str, limit: int) -> list[str]:
    """한 발언이 배치 상한보다 길면 문장 경계에서 나눈다."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + 1 + len(sentence) > limit:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def _build_prompt(*, ticker: str, batch: list[_TurnPiece]) -> str:
    turns = "\n\n".join(
        f"[T{piece.turn_index}] ({piece.section or 'unknown'}{'' if piece.management else ', NOT management - do not select'}) "
        f"{piece.speaker or 'Unknown'}:\n{piece.text}"
        for piece in batch
    )
    topics = ", ".join(STATEMENT_TOPICS)
    return f"""You read part of a {ticker} earnings call transcript and copy out the management statements
that an investor would want to compare against the NEXT quarter's call.

Select a statement when it contains one of:
- guidance or outlook with numbers (ranges, raised / reiterated / lowered). Copy EVERY guidance figure
  separately: sales, operating income, EPS, for the next quarter and for the full year
- a reported metric with a number (growth rate, comp sales, EPS, operating income, margin, basis points)
- a headwind or tailwind and its size (tariffs, regulation, FX, pricing)
- a capital allocation figure (capex, buybacks, dividends, cash flow)
- a concrete strategic claim with a number (stores, markets, users, share)

Do NOT select:
- greetings, thanks, introductions, safe-harbor language
- paragraphs marked "NOT management" (operator, analyst questions). Use them only as context
- vague claims with no number or concrete fact ("we are excited about the momentum")

Rules for "text":
- Copy it EXACTLY from the transcript, character for character. Do not paraphrase, shorten, or fix grammar.
- One or two consecutive sentences, at most {MAX_STATEMENT_CHARS} characters.
- "turn" is the number in [T..] of the paragraph you copied from.
- "topic" is one of: {topics}.

Return JSON only: {{"statements": [{{"turn": 3, "topic": "guidance", "text": "..."}}]}}
Return {{"statements": []}} if nothing qualifies.

Transcript:
{turns}"""


def _is_gemini_fallback(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("rationale") == _GEMINI_FALLBACK_RATIONALE


def _parse_candidates(raw: str) -> list[Any] | None:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("statements"), list):
        return None
    return parsed["statements"]


def _verified(candidate: Any, *, normalized_turns: list[str], allowed_turns: set[int]) -> tuple[int, str, int, str] | None:
    """원문에 그대로 있는 문장만 통과시킨다. (turn_index, topic, 발언 내 위치, text) 또는 None.

    LLM 이 문장 중간 조각을 골라도 앞뒤 문장 경계까지 넓혀 저장한다. 조각만 두면
    "we do not expect ..." 에서 "expect ..." 만 남아 뜻이 뒤집힐 수 있다.
    """
    if not isinstance(candidate, dict):
        return None
    try:
        turn_index = int(str(candidate.get("turn")).strip().lstrip("Tt"))
    except (TypeError, ValueError):
        return None
    if turn_index not in allowed_turns:
        return None
    text = _normalize(candidate.get("text"))
    if not MIN_STATEMENT_CHARS <= len(text) <= MAX_STATEMENT_CHARS:
        return None
    source = normalized_turns[turn_index]
    found = source.find(text)
    if found < 0:
        return None
    start, end = _sentence_bounds(source, found, found + len(text))
    if end - start > MAX_EXPANDED_CHARS:
        return None
    topic = str(candidate.get("topic") or "").strip().lower()
    if topic not in STATEMENT_TOPICS:
        topic = "other"
    return turn_index, topic, start, source[start:end]


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """[start, end) 를 감싸는 문장들의 시작 · 끝 위치."""
    sentence_start = 0
    for match in _SENTENCE_END.finditer(text, 0, start + 1):
        if match.end() <= start:
            sentence_start = match.end()
    match = _SENTENCE_END.search(text, max(start, end - 1))
    sentence_end = match.start() if match else len(text)
    return sentence_start, max(sentence_end, end)


__all__ = ["ExtractionResult", "TranscriptStatementExtractionService"]
