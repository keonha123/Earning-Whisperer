from assistant.context import Evidence
from assistant.segment_search import SegmentIndex, tokenize


def _seg(seq, text):
    return Evidence(marker=f"S{seq}", type="segment", ref=str(seq), text=text)


def test_tokenize_lowercases_keeps_numbers_and_drops_stopwords():
    assert tokenize("The comp sales grew 4.5% in the U.S.") == ["comp", "sales", "grew", "4.5", "u", "s"]


def test_search_ranks_by_relevance_and_excludes_zero_scores():
    index = SegmentIndex([_seg(0, "Welcome to the call."), _seg(1, "Comp sales grew 4.5%."),
                          _seg(2, "eCommerce grew 20%, comp sales strong."), _seg(3, "Thank you.")])
    hits = index.search("comp sales growth", top_k=8)
    assert [h.marker for h in hits][:2] in (["S1", "S2"], ["S2", "S1"])
    assert all(h.marker not in {"S0", "S3"} for h in hits)


def test_search_respects_top_k_and_breaks_ties_by_sequence():
    index = SegmentIndex([_seg(i, "tariff refund") for i in range(5)])
    assert [h.marker for h in index.search("tariff", top_k=3)] == ["S0", "S1", "S2"]


def test_search_with_no_usable_tokens_returns_nothing():
    index = SegmentIndex([_seg(0, "Comp sales grew.")])
    assert index.search("기존점 매출", top_k=8) == []
    assert SegmentIndex([]).search("comp", top_k=8) == []
