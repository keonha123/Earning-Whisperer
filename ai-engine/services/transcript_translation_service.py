"""어닝콜 세그먼트 한국어 번역.

backend 가 세그먼트 원문과 함께 그 안에서 찾은 용어 목록(`terms`)을 보내면, 그 용어의
한국어 표기를 고정해 번역한다. 용어 사전 자체는 backend 가 갖고 있고 엔진은 받은 것만 쓴다.

실패하면 `available=false` 와 사유를 돌려준다. 원문을 한국어인 척 돌려보내지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

try:
    from config import Settings, get_settings
    from core.gemini_client import gemini_client
    from services.transcript_assistant_service import _numeric_tokens, _unit_tokens, _NEGATION, _KO_NEGATION
    from models.transcript_translation_models import (
        TranscriptTranslateRequest,
        TranscriptTranslateResponse,
        TranslationTerm,
    )
except ImportError:  # pragma: no cover
    from ..config import Settings, get_settings
    from ..core.gemini_client import gemini_client
    from .transcript_assistant_service import _numeric_tokens, _unit_tokens, _NEGATION, _KO_NEGATION
    from ..models.transcript_translation_models import (
        TranscriptTranslateRequest,
        TranscriptTranslateResponse,
        TranslationTerm,
    )


logger = logging.getLogger(__name__)

#: 번역 1건 제한 시간. 시연 세그먼트 간격이 6초라 그 안에 끝나야 다음 세그먼트와 겹치지 않는다.
TRANSLATION_TIMEOUT_SECONDS = 6.0

#: 번역 출력 토큰 상한. 세그먼트 원문 상한(4000자)을 한국어로 옮겨도 넉넉한 값.
TRANSLATION_MAX_OUTPUT_TOKENS = 2048

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")

#: 번역문의 글자 중 한글이 차지해야 하는 최소 비율 (한글 / (한글 + 영문 알파벳)).
#: 회사명 · 사업부명은 원문 표기를 유지하므로 영문이 섞이는 것은 정상이다. 실측 번역문은
#: 영문 고유명사가 많은 문장도 0.45 이상이었다. 반면 영어 원문에 용어만 한국어로 끼워 넣은
#: 응답은 0.1 안팎이라, 그 사이 값으로 "번역하지 않고 돌려준 응답" 을 거른다.
MIN_HANGUL_RATIO = 0.3


class TranscriptTranslationService:
    def __init__(
        self,
        *,
        llm_client=gemini_client,
        settings: Settings | None = None,
        timeout_seconds: float = TRANSLATION_TIMEOUT_SECONDS,
    ) -> None:
        self.llm_client = llm_client
        self.settings = settings or get_settings()
        self.timeout_seconds = timeout_seconds

    async def translate(self, request: TranscriptTranslateRequest) -> TranscriptTranslateResponse:
        ticker = request.ticker.upper()
        log_ctx = (ticker, request.call_id, request.sequence)
        terms = _dedupe_terms(request.terms)
        try:
            raw = await asyncio.wait_for(
                self._generate(ticker=ticker, text=request.text, terms=terms),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            # wait_for 는 대기만 끊는다. 스레드에서 도는 SDK 호출은 끝까지 가며 할당량을 쓴다.
            logger.warning("번역 시간 초과 - ticker=%s call_id=%s sequence=%s", *log_ctx)
            return _unavailable(request.sequence, "translation_llm_timeout")
        except _LlmCallFailed:
            # 실제 원인(429 · 503 · 키 누락)은 gemini_client 가 직전에 남긴 경고 로그에 있다.
            logger.warning("번역 LLM 호출 실패 - ticker=%s call_id=%s sequence=%s", *log_ctx)
            return _unavailable(request.sequence, "translation_llm_failed")
        except Exception:
            logger.exception("번역 처리 중 예기치 못한 오류 - ticker=%s call_id=%s sequence=%s", *log_ctx)
            return _unavailable(request.sequence, "translation_internal_error")

        text_ko = _parse_text_ko(raw)
        if text_ko is None:
            logger.warning("번역 응답 형식 오류 - ticker=%s call_id=%s sequence=%s raw=%.200s", *log_ctx, raw)
            return _unavailable(request.sequence, "translation_invalid_response")
        if _hangul_ratio(text_ko) < MIN_HANGUL_RATIO:
            logger.warning("번역문이 한국어가 아님 - ticker=%s call_id=%s sequence=%s text_ko=%.200s", *log_ctx, text_ko)
            return _unavailable(request.sequence, "translation_not_korean")

        if _numeric_tokens(request.text) != _numeric_tokens(text_ko) or _unit_tokens(request.text) != _unit_tokens(text_ko):
            return _unavailable(request.sequence, "translation_numeric_or_unit_mismatch")
        if _NEGATION.search(request.text) and not _KO_NEGATION.search(text_ko):
            return _unavailable(request.sequence, "translation_negation_mismatch")
        used = _terms_used(terms, text_ko)
        warnings = ["translation_terms_not_applied"] if len(used) < len(terms) else []
        return TranscriptTranslateResponse(
            available=True,
            sequence=request.sequence,
            text_ko=text_ko,
            terms_used=used,
            warnings=warnings,
        )

    async def _generate(self, *, ticker: str, text: str, terms: list[TranslationTerm]) -> str:
        settings = self.settings
        model = settings.gemini_primary_model or settings.gemini_model_fast
        prompt = _build_prompt(ticker=ticker, text=text, terms=terms)
        config = {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "max_output_tokens": TRANSLATION_MAX_OUTPUT_TOKENS,
            "route_profile": "economy",
            "thinking_level": settings.gemini_primary_thinking_level,
            "timeout_seconds": self.timeout_seconds,
        }
        usage = await self.llm_client.generate_content_with_metadata(model=model, contents=prompt, config=config)
        raw = str(usage.text or "")
        if getattr(usage, "is_fallback", False) or _is_gemini_fallback(raw):
            self._forget_cached(model=model, prompt=prompt, config=config)
            raise _LlmCallFailed()
        return raw

    def _forget_cached(self, *, model: str, prompt: str, config: dict) -> None:
        """Compatibility cleanup for injected legacy clients; GeminiClient never caches failures."""
        cache = getattr(self.llm_client, "_response_cache", None)
        cache_key = getattr(self.llm_client, "_cache_key", None)
        if isinstance(cache, dict) and callable(cache_key):
            cache.pop(cache_key(model, prompt, config), None)


#: gemini_client 가 호출 실패(429 · 503 · 키 누락 등) 시 예외 대신 돌려주는 분석용 폴백 JSON 의 표식.
_GEMINI_FALLBACK_RATIONALE = "Gemini fallback response"


class _LlmCallFailed(Exception):
    """gemini_client 가 호출 실패를 폴백 JSON 으로 감춘 경우."""


def _is_gemini_fallback(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("rationale") == _GEMINI_FALLBACK_RATIONALE


def _parse_text_ko(raw: str) -> str | None:
    """응답에서 `text_ko` 를 꺼낸다. 형식이 틀리면 None."""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("text_ko")
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split())


def _hangul_ratio(text: str) -> float:
    hangul = len(_HANGUL.findall(text))
    latin = len(_LATIN.findall(text))
    return hangul / (hangul + latin) if hangul + latin else 0.0


def _terms_used(terms: list[TranslationTerm], text_ko: str) -> list[str]:
    """번역문에 `ko` 가 실제로 들어간 용어. 요청 순서를 유지한다.

    긴 번역어부터 찾아 지운다. "매출" 과 "기존점 매출" 이 함께 오면, "기존점 매출" 만
    쓰인 번역문에서 "매출" 까지 쓰인 것으로 잡히지 않게 하기 위해서다.
    """
    remaining = text_ko
    used: set[str] = set()
    for t in sorted(terms, key=lambda t: len(t.ko), reverse=True):
        if t.ko in remaining:
            used.add(t.term)
            remaining = remaining.replace(t.ko, " ")
    return [t.term for t in terms if t.term in used]


def _dedupe_terms(terms: list[TranslationTerm]) -> list[TranslationTerm]:
    seen: set[str] = set()
    result: list[TranslationTerm] = []
    for t in terms:
        key = t.term.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(t)
    return result


def _build_prompt(*, ticker: str, text: str, terms: list[TranslationTerm]) -> str:
    glossary = "\n".join(f"- {t.term} → {t.ko}" for t in terms) or "- (없음)"
    return f"""당신은 미국 기업 어닝콜을 한국 개인투자자에게 옮기는 금융 번역가입니다.
아래 {ticker} 어닝콜 발언 한 단락을 한국어로 번역하세요.

규칙:
1. 아래 용어 목록에 있는 용어는 반드시 지정된 한국어 표기를 그대로 씁니다. 다른 말로 바꾸거나 풀어 쓰지 않습니다.
2. 숫자와 퍼센트는 원문 값을 그대로 옮깁니다. 반올림하거나 환산하지 않습니다. 통화 금액은 원문 표기를 그대로 둡니다 (예: $2.9 billion). 범위는 "4~5%" 처럼 물결표로 씁니다.
3. 사람 이름, 회사명, 사업부·브랜드·서비스명(예: Walmart U.S., Sam's Club)은 원문 표기를 유지합니다. 국가·지역명과 일반 명사는 한국어로 옮깁니다 (예: China → 중국).
4. 원문에 없는 내용을 덧붙이거나 요약하지 않습니다. 해설이나 의견을 넣지 않습니다.
5. 화자가 회사를 가리키는 "we", "our" 는 "당사" 로 옮기거나 문맥상 자연스러우면 생략합니다.
6. 문체는 "~했습니다", "~입니다" 형태의 자연스러운 한국어 경어체로 씁니다.

용어 목록:
{glossary}

원문:
{text}

JSON 으로만 답하세요: {{"text_ko": "번역문"}}"""


def _unavailable(sequence: int, warning: str) -> TranscriptTranslateResponse:
    return TranscriptTranslateResponse(available=False, sequence=sequence, text_ko=None, warnings=[warning])


__all__ = ["TranscriptTranslationService", "TRANSLATION_TIMEOUT_SECONDS"]
