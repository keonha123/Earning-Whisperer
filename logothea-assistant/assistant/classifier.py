"""질문 분류: 추천 질문 → 규칙 → LLM 구조화 출력 순서로 판단한다."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel

from assistant.llm import LLMClient, Message, Usage
from assistant.rules import is_explicit_trade_request
from assistant.schemas import AskRequest

logger = logging.getLogger(__name__)

Category = Literal["answer", "facts_only", "investment_advice", "price_prediction", "out_of_scope", "glossary"]


class Classification(BaseModel):
    category: Category
    # 구조화 출력의 strict 스키마는 모든 필드가 필수라 기본값을 두지 않고 null 을 허용한다.
    glossary_term: str | None
    search_query: str


# 추천 질문은 문구가 고정이라 분류 호출 없이 정해진 검색어를 쓴다.
SUGGESTED_SEARCH_QUERIES: dict[str, str] = {
    "summary": "earnings call key highlights results",
    "vs_last_quarter": "changes versus prior quarter results guidance",
    "guidance": "full year guidance outlook raised lowered reiterated",
    "vs_expectations": "results versus analyst consensus estimates",
    "risks": "risks headwinds concerns uncertainty",
}

CLASSIFY_SYSTEM_PROMPT = """너는 어닝콜 질의응답 서비스의 질문 분류기다. 사용자는 {ticker} 의 실적 발표 콜을 듣는 개인투자자다.
마지막 사용자 질문을 아래 분류 중 하나로 정한다. 앞선 대화는 맥락으로만 쓴다.
- answer: 콜 발언, 실적 수치, 가이던스, 경영진 화법, 관련 뉴스, 지난 분기 비교처럼 자료로 답할 수 있는 질문
- facts_only: 주가가 비싼지, 목표주가처럼 판단을 묻지만 수치와 애널리스트 의견 인용 같은 사실로만 답할 질문
- investment_advice: 사거나 팔거나 들고 있어야 하는지 묻는 질문
- price_prediction: 주가가 오를지 내릴지, 얼마가 될지 예측을 요구하는 질문
- out_of_scope: 이 종목, 이 콜과 관련 없는 질문
- glossary: 금융 용어의 뜻만 묻는 질문
glossary_term: glossary 일 때 그 용어의 영어 원형(예: comp sales). 아니면 null.
search_query: 앞선 대화를 반영해, 질문을 혼자 읽어도 뜻이 통하는 영어 뉴스 검색어로 다시 쓴다. 어느 분류든 채운다."""


def history_messages(request: AskRequest) -> list[Message]:
    return [Message(turn.role, turn.text) for turn in request.history]


async def classify(llm: LLMClient, request: AskRequest) -> tuple[Classification, Usage]:
    if request.suggested_question_id is not None:
        query = SUGGESTED_SEARCH_QUERIES[request.suggested_question_id]
        return Classification(category="answer", glossary_term=None, search_query=query), Usage()
    if is_explicit_trade_request(request.question):
        return Classification(category="investment_advice", glossary_term=None, search_query=""), Usage()
    messages = [
        Message("system", CLASSIFY_SYSTEM_PROMPT.format(ticker=request.ticker)),
        *history_messages(request),
        Message("user", request.question),
    ]
    return await llm.parse(messages, Classification)


def _normalize(name: str) -> str:
    return " ".join(name.lower().split())


class Glossary:
    """backend 용어 사전(api-spec 7.9 형식). 정의가 있는 용어만 바로 답한다."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._index: dict[str, dict[str, Any]] = {}
        for entry in payload.get("terms", []):
            for name in [entry.get("term", ""), *entry.get("aliases", [])]:
                key = _normalize(name)
                if key:
                    self._index.setdefault(key, entry)

    def lookup(self, term: str | None) -> dict[str, Any] | None:
        if not term:
            return None
        entry = self._index.get(_normalize(term))
        if entry is None or not entry.get("definition_ko"):
            return None
        return entry


def glossary_answer(entry: dict[str, Any]) -> str:
    text = f"{entry['term']}({entry['ko']}): {entry['definition_ko']}"
    if entry.get("why_ko"):
        text += f" {entry['why_ko']}"
    return text


class GlossaryProvider:
    """용어 사전을 처음 필요할 때 한 번 읽어 둔다. backend 는 기동 시 읽은 사전을 바꾸지 않는다."""

    def __init__(self, loader: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        self._loader = loader
        self._glossary: Glossary | None = None

    async def get(self) -> Glossary | None:
        if self._glossary is None:
            try:
                self._glossary = Glossary(await self._loader())
            except Exception:
                # 사전을 못 읽어도 질문은 생성 경로로 답할 수 있다. 다음 질문에서 다시 읽는다.
                logger.warning("용어 사전을 읽지 못했습니다", exc_info=True)
                return None
        return self._glossary
