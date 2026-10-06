"""어닝콜 세그먼트 번역 (#110) — 서비스 분기와 엔드포인트 계약."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from config import Settings
from core.gemini_client import GeminiClient
from models.transcript_translation_models import TranscriptTranslateRequest
from services.transcript_translation_service import TranscriptTranslationService


class FakeLlmClient:
    def __init__(self, *payloads, delay: float = 0.0) -> None:
        self.payloads = list(payloads)
        self.delay = delay
        self.calls = []

    async def generate_content_with_metadata(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return SimpleNamespace(text=text)


def _service(llm: FakeLlmClient, timeout: float = 2.0) -> TranscriptTranslationService:
    return TranscriptTranslationService(llm_client=llm, settings=Settings(), timeout_seconds=timeout)


def _request(**overrides) -> TranscriptTranslateRequest:
    data = {
        "ticker": "wmt",
        "sequence": 3,
        "text": "Comp sales for Walmart U.S. were 2.6%, led by transactions.",
        "terms": [{"term": "comp sales", "ko": "기존점 매출"}, {"term": "transactions", "ko": "거래 건수"}],
    }
    data.update(overrides)
    return TranscriptTranslateRequest.model_validate(data)


def test_번역_성공시_용어_반영_여부를_코드로_판정한다():
    llm = FakeLlmClient({"text_ko": "월마트 미국 부문 기존점 매출은 거래 건수 증가에 힘입어 2.6% 늘었습니다."})

    result = asyncio.run(_service(llm).translate(_request()))

    assert result.available is True
    assert result.sequence == 3
    assert result.text_ko.startswith("월마트 미국 부문 기존점 매출")
    assert result.terms_used == ["comp sales", "transactions"]
    assert result.warnings == []


def test_프롬프트에_용어_목록과_원문이_들어간다():
    llm = FakeLlmClient({"text_ko": "기존점 매출은 2.6% 늘었습니다."})

    asyncio.run(_service(llm).translate(_request()))

    prompt = llm.calls[0]["contents"]
    assert "- comp sales → 기존점 매출" in prompt
    assert "- transactions → 거래 건수" in prompt
    assert "Comp sales for Walmart U.S. were 2.6%" in prompt
    assert "WMT" in prompt


def test_지정한_번역어가_빠지면_경고를_붙인다():
    llm = FakeLlmClient({"text_ko": "월마트 미국 비교 판매는 거래 건수 덕분에 2.6% 늘었습니다."})

    result = asyncio.run(_service(llm).translate(_request()))

    assert result.available is True
    assert result.terms_used == ["transactions"]
    assert result.warnings == ["translation_terms_not_applied"]


def test_용어가_없으면_일반_번역으로_동작한다():
    llm = FakeLlmClient({"text_ko": "좋은 아침입니다. 함께해 주셔서 감사합니다."})

    result = asyncio.run(_service(llm).translate(_request(text="Good morning and thanks for joining us.", terms=[])))

    assert result.available is True
    assert result.terms_used == []
    assert result.warnings == []
    assert "- (없음)" in llm.calls[0]["contents"]


def test_같은_용어가_중복으로_오면_한_번만_싣는다():
    llm = FakeLlmClient({"text_ko": "기존점 매출은 2.6% 늘었습니다."})
    terms = [{"term": "comp sales", "ko": "기존점 매출"}, {"term": "Comp Sales ", "ko": "기존점 매출"}]

    result = asyncio.run(_service(llm).translate(_request(terms=terms)))

    assert llm.calls[0]["contents"].count("→ 기존점 매출") == 1
    assert result.terms_used == ["comp sales"]


def test_gemini_client_폴백_JSON은_호출_실패로_처리한다():
    # gemini_client 는 호출 실패 시 예외 대신 분석용 폴백 JSON 을 돌려준다.
    fallback = {"direction": "NEUTRAL", "magnitude": 0.0, "confidence": 0.0, "rationale": "Gemini fallback response"}
    llm = FakeLlmClient(fallback)

    result = asyncio.run(_service(llm).translate(_request()))

    assert result.available is False
    assert result.text_ko is None
    assert result.warnings == ["translation_llm_failed"]


@pytest.mark.parametrize("raw", ["not json", "[]", '{"text_ko": ""}', '{"text_ko": 3}'])
def test_형식이_틀린_응답은_실패로_처리한다(raw):
    result = asyncio.run(_service(FakeLlmClient(raw)).translate(_request()))

    assert result.available is False
    assert result.warnings == ["translation_invalid_response"]


def test_영어를_그대로_돌려주면_한국어인_척하지_않는다():
    llm = FakeLlmClient({"text_ko": "Comp sales for Walmart U.S. were 2.6%, led by transactions."})

    result = asyncio.run(_service(llm).translate(_request()))

    assert result.available is False
    assert result.text_ko is None
    assert result.warnings == ["translation_not_korean"]


def test_시간_초과():
    llm = FakeLlmClient({"text_ko": "늦은 응답입니다."}, delay=0.5)

    result = asyncio.run(_service(llm, timeout=0.05).translate(_request()))

    assert result.available is False
    assert result.warnings == ["translation_llm_timeout"]


def test_예기치_못한_예외는_LLM_실패와_구분한다():
    result = asyncio.run(_service(FakeLlmClient(RuntimeError("boom"))).translate(_request()))

    assert result.available is False
    assert result.warnings == ["translation_internal_error"]


def test_용어만_끼워_넣은_영어_원문은_한국어로_보지_않는다():
    llm = FakeLlmClient({"text_ko": "기존점 매출 for Walmart U.S. were 2.6%, led by transactions, and Sam's Club delivered comps."})

    result = asyncio.run(_service(llm).translate(_request()))

    assert result.available is False
    assert result.warnings == ["translation_not_korean"]


def test_영문_고유명사가_섞인_정상_번역은_통과한다():
    # 실측 번역문. 회사명 · 사업부명은 원문 표기를 유지하라고 지시하므로 영문이 섞인다.
    text_ko = "Walmart U.S.의 기존점 매출은 2.6%였으며 거래 건수가 이를 견인했고, Sam's Club U.S.는 4.4%의 기존점 매출을 기록했습니다."

    result = asyncio.run(_service(FakeLlmClient({"text_ko": text_ko})).translate(_request(
        text="Comp sales for Walmart U.S. were 2.6%, led by transactions, and Sam's Club U.S. comp sales were 4.4%.")))

    assert result.available is True


def test_짧은_번역어가_긴_번역어의_일부여도_쓰인_것으로_잡지_않는다():
    llm = FakeLlmClient({"text_ko": "기존점 매출은 2.6% 늘었습니다."})
    terms = [{"term": "net sales", "ko": "매출"}, {"term": "comp sales", "ko": "기존점 매출"}]

    result = asyncio.run(_service(llm).translate(_request(terms=terms)))

    assert result.terms_used == ["comp sales"]
    assert result.warnings == ["translation_terms_not_applied"]


def _real_client_failing_then(*outcomes):
    """실제 GeminiClient 에서 SDK 호출만 바꿔 끼운다. 폴백 JSON 생성과 응답 캐시는 실제 코드를 탄다."""
    client = GeminiClient()
    calls = []

    def fake_sdk(model, prompt, config):
        calls.append(model)
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return json.dumps(outcome, ensure_ascii=False), {"prompt_tokens": 1, "output_tokens": 1, "total_tokens": 2}

    client._generate_with_modern_sdk = fake_sdk
    return client, calls


def test_실제_gemini_client_폴백을_호출_실패로_분류한다():
    client, _ = _real_client_failing_then(RuntimeError("429 RESOURCE_EXHAUSTED"))
    service = TranscriptTranslationService(llm_client=client, settings=Settings(), timeout_seconds=5)

    result = asyncio.run(service.translate(_request()))

    assert result.available is False
    assert result.warnings == ["translation_llm_failed"]


def test_폴백_응답이_캐시에_남지_않아_재시도하면_다시_호출한다():
    client, calls = _real_client_failing_then(
        RuntimeError("429 RESOURCE_EXHAUSTED"),
        {"text_ko": "월마트 미국 부문 기존점 매출은 2.6% 늘었습니다."},
    )
    service = TranscriptTranslationService(llm_client=client, settings=Settings(), timeout_seconds=5)

    first = asyncio.run(service.translate(_request()))
    second = asyncio.run(service.translate(_request()))

    assert first.available is False
    assert second.available is True
    assert len(calls) == 2


def test_엔드포인트가_등록되고_계약대로_직렬화된다():
    app = main.create_app()
    app.state.transcript_translation_service = _service(
        FakeLlmClient({"text_ko": "월마트 미국 부문 기존점 매출은 2.6% 늘었습니다."})
    )
    client = TestClient(app)

    response = client.post(
        "/v1/engine/transcript/translate",
        json={
            "ticker": "WMT",
            "call_id": "demo-wmt-1",
            "sequence": 3,
            "text": "Comp sales for Walmart U.S. were 2.6%.",
            "terms": [{"term": "comp sales", "ko": "기존점 매출"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "sequence": 3,
        "text_ko": "월마트 미국 부문 기존점 매출은 2.6% 늘었습니다.",
        "terms_used": ["comp sales"],
        "warnings": [],
    }


@pytest.mark.parametrize(
    "body",
    [
        {"ticker": "WMT", "sequence": 0, "text": ""},
        {"ticker": "WMT", "sequence": 0, "text": "   "},
        {"ticker": "WMT", "sequence": 0, "text": "Comp sales rose.", "terms": [{"term": " ", "ko": "매출"}]},
        {"ticker": "WMT", "sequence": 0, "text": "Comp sales rose.", "terms": [{"term": "comp sales", "ko": " "}]},
    ],
)
def test_공백뿐인_값은_422(body):
    client = TestClient(main.create_app())

    response = client.post("/v1/engine/transcript/translate", json=body)

    assert response.status_code == 422


def test_실패도_200_으로_계약대로_직렬화된다():
    app = main.create_app()
    app.state.transcript_translation_service = _service(FakeLlmClient(
        {"direction": "NEUTRAL", "rationale": "Gemini fallback response"}
    ))
    client = TestClient(app)

    response = client.post("/v1/engine/transcript/translate", json={"ticker": "WMT", "sequence": 5, "text": "Comp sales rose."})

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "sequence": 5,
        "text_ko": None,
        "terms_used": [],
        "warnings": ["translation_llm_failed"],
    }

@pytest.mark.parametrize("text_ko", ["매출은 26% 늘었습니다.", "매출은 2.6퍼센트포인트 늘었습니다."])
def test_changed_numeric_value_or_unit_is_rejected(text_ko):
    result = asyncio.run(_service(FakeLlmClient({"text_ko": text_ko})).translate(_request()))
    assert not result.available and result.text_ko is None
    assert result.warnings == ["translation_numeric_or_unit_mismatch"]


def test_translation_route_has_one_authoritative_handler():
    routes = [r for r in main.app.routes if getattr(r, "path", None) == "/v1/engine/transcript/translate"]
    assert len(routes) == 1
    assert routes[0].endpoint.__module__ == "api.routers.transcript_translation"

@pytest.mark.parametrize("translation,accepted", [
    ("매출은 전년 대비 20% 증가했습니다. 매출총이익률은 5%포인트 개선되었습니다. 당사는 다음 분기에 20%의 매출 성장을 예상합니다.", True),
    ("매출은 전년 대비 20% 증가했습니다. 매출총이익률은 5% 개선되었습니다. 당사는 다음 분기에 20%의 매출 성장을 예상합니다.", False),
    ("매출은 전년 대비 20% 증가했습니다. 매출총이익률은 6%포인트 개선되었습니다. 당사는 다음 분기에 20%의 매출 성장을 예상합니다.", False),
])
def test_joined_spoken_segments_korean_percentage_points(translation, accepted):
    source = "Revenue increased twenty percent year over year. Gross margin improved five percentage points. We expect revenue growth of twenty percent next quarter."
    result = asyncio.run(_service(FakeLlmClient({"text_ko": translation})).translate(_request(text=source, terms=[])))
    assert result.available is accepted
    if not accepted:
        assert result.warnings == ["translation_numeric_or_unit_mismatch"]
