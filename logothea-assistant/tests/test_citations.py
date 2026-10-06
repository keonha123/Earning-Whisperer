import pytest

from assistant.citations import Quantity, extract_quantities, split_sentences, verify_citations
from assistant.context import Evidence

EVIDENCE = {
    "S3": Evidence("S3", "segment", "3", "Comp sales for Walmart U.S. were up 4.5%, and revenue reached $176 billion.",
                   speaker="John Furner", start_ms=198000, published_at=1787227218),
    "S12": Evidence("S12", "segment", "12", "Operating income grew 50 basis points faster than sales.",
                    speaker="John David Rainey", start_ms=754000),
    "E1": Evidence("E1", "estimate", "upcoming", "이번 실적 발표 시장 예상(예정 2026-08-20): EPS 추정 $0.74, 매출 추정 $176.00 billion",
                   title="이번 실적 발표 시장 예상"),
    "N1": Evidence("N1", "news", "d1", "Walmart stock trades at 3x book", title="t", source="Reuters", published_at=1),
}


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("$176 billion", "usd", 176e9),
        ("$1.2B", "usd", 1.2e9),
        ("$0.74", "usd", 0.74),
        ("1,760억 달러", "usd", 1760e8),
        ("26억달러", "usd", 26e8),
        ("4.5%", "pct", 4.5),
        ("4.5 퍼센트", "pct", 4.5),
        ("4.5 percent", "pct", 4.5),
        ("50 basis points", "pct", 0.5),
        ("50bp", "pct", 0.5),
        ("3x", "mult", 3.0),
        ("1.5배", "mult", 1.5),
        ("USD 1.2 billion", "usd", 1.2e9),
        ("1.2 billion dollars", "usd", 1.2e9),
        ("2.6 percentage points", "pct", 2.6),
        ("2.6%p", "pct", 2.6),
        ("2.6%포인트", "pct", 2.6),
        ("2.6 points", "pct", 2.6),
        ("2.5 times", "mult", 2.5),
    ],
)
def test_extract_quantities_normalizes_units(text, kind, value):
    [quantity] = extract_quantities(text)
    assert quantity.kind == kind
    assert quantity.value == pytest.approx(value)


def test_extract_quantities_ignores_bare_numbers_markers_and_dividends():
    assert extract_quantities("2026년 2분기 [S12] 3배당 Q2") == []


def test_extract_quantities_tolerance_follows_written_precision():
    [quantity] = extract_quantities("2.6%")
    assert quantity == Quantity("pct", 2.6, pytest.approx(0.05))


def test_split_sentences_attaches_leading_markers_to_previous_sentence():
    answer = "기존점 매출은 4.5% 늘었습니다. [S3] 가이던스는 올렸습니다 [S12].\n- 매출 $176 billion [S3]"
    assert split_sentences(answer) == [
        "기존점 매출은 4.5% 늘었습니다. [S3]",
        "가이던스는 올렸습니다 [S12].",
        "- 매출 $176 billion [S3]",
    ]


def test_split_sentences_handles_marker_glued_to_period():
    # 실제 모델 출력에서 나온 형태: 마침표 바로 뒤에 공백 없이 표시가 붙는다.
    assert split_sentences("750bp 기여했다고 밝혔습니다.[S20] 다만 17.4% 는 따로 없습니다.") == [
        "750bp 기여했다고 밝혔습니다. [S20]", "다만 17.4% 는 따로 없습니다."]


def test_marker_glued_to_period_is_verified_against_its_own_sentence():
    evidence = {"S20": Evidence("S20", "segment", "20",
                                "Operating income growth included a net benefit of approximately 750 basis points.")}
    result = verify_citations("관세 환급이 약 750bp 기여했다고 밝혔습니다.[S20] 다만 17.4%에서 뺀 수치는 없습니다.", evidence)
    assert result.citations[0]["verified"] is True
    assert "number_mismatch" not in result.warnings


def test_split_sentences_attaches_comma_separated_leading_markers():
    assert split_sentences("기존점 매출은 늘었습니다. [S3, S12] 다음 문장입니다.") == [
        "기존점 매출은 늘었습니다. [S3, S12]", "다음 문장입니다."]


def test_comma_separated_markers_are_expanded_in_order():
    result = verify_citations("매출은 4.5% 늘었습니다 [S3, S12].", EVIDENCE)
    assert [c["marker"] for c in result.citations] == ["S3", "S12"]


def test_verified_citations_in_order_of_first_use_with_metadata():
    result = verify_citations("기존점 매출은 4.5% 늘었습니다 [S3]. 영업이익은 매출보다 0.5%p 더 빨리 늘었습니다 [S12][S3].", EVIDENCE)

    assert [c["marker"] for c in result.citations] == ["S3", "S12"]
    assert all(c["verified"] for c in result.citations)
    assert result.warnings == []
    first = result.citations[0]
    assert first["type"] == "segment" and first["ref"] == "3" and first["start_ms"] == 198000
    assert first["speaker"] == "John Furner"
    assert first["quote"].startswith("Comp sales")


def test_korean_units_match_english_source():
    assert verify_citations("매출은 1,760억 달러였습니다 [S3].", EVIDENCE).citations[0]["verified"]
    mismatch = verify_citations("매출은 1,800억 달러였습니다 [S3].", EVIDENCE)
    assert not mismatch.citations[0]["verified"]
    assert mismatch.warnings == ["number_mismatch"]


def test_rounded_numbers_match_within_written_precision():
    evidence = {"S1": Evidence("S1", "segment", "1", "Comp sales grew 2.63%.")}
    assert verify_citations("기존점 매출은 2.6% 늘었습니다 [S1].", evidence).citations[0]["verified"]
    assert not verify_citations("기존점 매출은 2.7% 늘었습니다 [S1].", evidence).citations[0]["verified"]


def test_unknown_marker_is_unverified_and_warned():
    result = verify_citations("근거 없는 주장입니다 [S99].", EVIDENCE)
    assert result.citations == [{"marker": "S99", "type": None, "ref": None, "title": None, "source": None,
                                 "published_at": None, "start_ms": None, "speaker": None, "quote": None,
                                 "verified": False}]
    assert result.warnings == ["unknown_marker:S99"]


def test_uncited_number_is_warned_without_citations():
    result = verify_citations("매출이 4.5% 늘었습니다.", EVIDENCE)
    assert result.citations == []
    assert result.warnings == ["uncited_number"]


def test_marker_failing_in_any_sentence_is_unverified():
    result = verify_citations("기존점 매출은 4.5% 늘었습니다 [S3]. 영업이익률은 9% 입니다 [S3].", EVIDENCE)
    assert result.citations[0]["verified"] is False


def test_sentence_without_numbers_keeps_known_marker_verified():
    assert verify_citations("가이던스를 올렸습니다 [S12].", EVIDENCE).citations[0]["verified"]


def test_quote_is_truncated_to_300_chars():
    evidence = {"S1": Evidence("S1", "segment", "1", "a" * 500)}
    assert len(verify_citations("요약입니다 [S1].", evidence).citations[0]["quote"]) == 300


def test_estimate_and_news_citations():
    result = verify_citations("시장은 EPS 0.74달러를 예상했습니다 [E1]. 주가는 장부가의 3배입니다 [N1].", EVIDENCE)
    assert [(c["marker"], c["type"], c["verified"]) for c in result.citations] == [
        ("E1", "estimate", True), ("N1", "news", True)]


def test_percentage_point_claim_matches_source_wording():
    evidence = {"S1": Evidence("S1", "segment", "1", "Operating margin expanded 2.6 percentage points.")}
    assert verify_citations("영업이익률이 2.6%p 개선됐습니다 [S1].", evidence).citations[0]["verified"]


def test_dollar_wording_variants_match():
    evidence = {"S1": Evidence("S1", "segment", "1", "We reported revenue of 1.2 billion dollars.")}
    assert verify_citations("매출은 $1.2B 입니다 [S1].", evidence).citations[0]["verified"]


def test_integer_claim_rounds_within_half_unit():
    evidence = {"S1": Evidence("S1", "segment", "1", "Comp sales grew 2.6%.")}
    assert verify_citations("기존점 매출은 3% 늘었습니다 [S1].", evidence).citations[0]["verified"]
