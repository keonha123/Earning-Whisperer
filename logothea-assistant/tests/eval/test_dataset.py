from collections import Counter

from eval.dataset import DATASET_PATH, GROUP_MINIMUMS, EvalDataset, EvalItem, load_dataset, validate_dataset
from eval.transcript import SEGMENTS_PATH, EvalSegment, load_segments


def _segments(n=10, end_at=None):
    return [EvalSegment(i, i * 5000, i * 5000 + 4500, "CEO · A", f"t{i}", 1787227200 + i * 5, i == (end_at if end_at is not None else n - 1)) for i in range(n)]


def _item(**overrides):
    data = {"id": "a1", "group": "answerable", "question": "q", "as_of_sequence": 5, "expected_status": "answered",
            "key_points": ["p1", "p2"], "gold_sequences": [3]}
    data.update(overrides)
    return EvalItem(**data)


def _dataset(*items):
    return EvalDataset(name="t", ticker="WMT", call_started_at="2026-08-20T12:00:00Z", items=list(items))


def test_valid_item_has_no_errors():
    assert validate_dataset(_dataset(_item()), _segments()) == []


def test_detects_structural_errors():
    errors = validate_dataset(_dataset(
        _item(id="dup"), _item(id="dup"),
        _item(id="late-gold", gold_sequences=[7]),
        _item(id="beyond", as_of_sequence=99),
        _item(id="anchor", anchor_sequence=8),
        _item(id="few-points", key_points=["only one"]),
        _item(id="no-gold", gold_sequences=[]),
        _item(id="refusal-no-reason", group="refusal", expected_status="refused", key_points=[], gold_sequences=[]),
        _item(id="suggested-no-id", group="suggested"),
        _item(id="follow-no-history", group="follow_up"),
    ), _segments())

    joined = "\n".join(errors)
    for fragment in ["dup", "late-gold", "beyond", "anchor", "few-points", "no-gold", "refusal-no-reason", "suggested-no-id", "follow-no-history"]:
        assert fragment in joined, fragment


def test_no_evidence_and_refusal_items_need_no_points():
    items = [
        _item(id="ne", group="no_evidence", expected_status="no_evidence", key_points=[], gold_sequences=[]),
        _item(id="rf", group="refusal", expected_status="refused", expected_refusal_reason="investment_advice", key_points=[], gold_sequences=[]),
    ]
    assert validate_dataset(_dataset(*items), _segments()) == []


def test_real_dataset_is_valid_and_covers_every_group():
    dataset = load_dataset(DATASET_PATH)
    segments = load_segments(SEGMENTS_PATH)

    assert validate_dataset(dataset, segments) == []
    counts = Counter(item.group for item in dataset.items)
    for group, minimum in GROUP_MINIMUMS.items():
        assert counts[group] >= minimum, (group, counts[group])
    assert 50 <= len(dataset.items) <= 70
