import json

from eval.transcript import (
    CALL_STARTED_AT, SEGMENT_MS, SEGMENTS_PATH, TRANSCRIPT_PATH,
    build_segments, load_segments, split_sentences, write_segments,
)


def test_split_sentences_keeps_numbers_and_abbreviations_inside():
    text = "Comp sales were 2.6%. Sam's Club grew 4.4%! Is that good? $2.9 billion came back."
    assert split_sentences(text) == ["Comp sales were 2.6%.", "Sam's Club grew 4.4%!", "Is that good?", "$2.9 billion came back."]
    assert split_sentences("Walmart U.S. comp sales grew.") == ["Walmart U.S. comp sales grew."]


def test_build_segments_numbers_from_zero_and_labels_speakers():
    transcript = {"turns": [
        {"speaker": "Operator", "role": "Operator", "text": "Welcome. Please hold."},
        {"speaker": "John Furner", "role": "CEO", "text": "Good morning."},
        {"speaker": "Someone", "role": "", "text": "Thanks."},
    ]}
    segments = build_segments(transcript, "2026-08-20T12:00:00Z")

    assert [s.sequence for s in segments] == [0, 1, 2, 3]
    assert [s.speaker for s in segments] == ["Operator", "Operator", "CEO · John Furner", "Someone"]
    assert segments[1].start_ms == SEGMENT_MS and segments[1].end_ms == 2 * SEGMENT_MS - 500
    assert segments[0].timestamp == 1787227200
    assert segments[3].timestamp == 1787227200 + 15
    assert [s.is_session_end for s in segments] == [False, False, False, True]


def test_committed_segments_match_the_transcript(tmp_path):
    transcript = json.loads(TRANSCRIPT_PATH.read_text(encoding="utf-8"))
    built = build_segments(transcript, CALL_STARTED_AT)
    assert load_segments(SEGMENTS_PATH) == built
    assert len(built) == 649


def test_write_and_load_round_trip(tmp_path):
    segments = build_segments({"turns": [{"speaker": "A", "role": "CEO", "text": "Hi. Bye."}]}, CALL_STARTED_AT)
    path = tmp_path / "s.json"
    write_segments(path, segments)
    assert load_segments(path) == segments
