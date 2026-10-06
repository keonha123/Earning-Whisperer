import pytest

from assistant.rules import is_explicit_trade_request


@pytest.mark.parametrize(
    "question",
    ["지금 사야 돼?", "월마트 팔까?", "매수할까요", "매도할까?", "지금 들어가도 돼?", "손절할까",
     "물타기 해도 될까", "Should I buy WMT?", "is it a sell now"],
)
def test_explicit_trade_requests_are_caught(question):
    assert is_explicit_trade_request(question)


@pytest.mark.parametrize(
    "question",
    ["목표주가가 얼마야?", "애널리스트 매수 의견은 몇 명이야?", "가이던스가 바뀌었어?",
     "PER 이 비싼 편이야?", "경영진이 강조한 리스크는?", "buyback 규모는?",
     "is it a buyback program?", "Is it a sell-side estimate?", "should I buy back?",
     "매수 해도 되는 가격대 의견 몇 명이야", "자사주 매도 해야 하나 경영진이 언급했어?"],
)
def test_broad_questions_are_left_to_the_llm(question):
    assert not is_explicit_trade_request(question)
