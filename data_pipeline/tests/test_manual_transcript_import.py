from __future__ import annotations

from datetime import UTC, datetime
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.transcripts import manual_import
from collectors.transcripts.manual_import import (
    ManualTranscriptImportError,
    build_manual_transcript_item,
    import_text_file,
)


class InMemoryTextPath:
    def __init__(self, text: str, path: str = "manual_transcripts/NVDA_Q1_2027.txt") -> None:
        self.text = text
        self.path = path

    def exists(self) -> bool:
        return True

    def read_text(self, *, encoding: str) -> str:
        return self.text

    def __str__(self) -> str:
        return self.path


def _transcript_text() -> str:
    return """
    Sarah, Conference Operator: Good afternoon and welcome to NVIDIA's first quarter earnings call.
    Jensen Huang: Demand for AI infrastructure accelerated again as customers expanded training and inference capacity.
    Colette Kress: Revenue exceeded our outlook, data center growth remained strong, and gross margin improved year over year.
    Analyst: Can you discuss supply constraints and visibility into next quarter?
    Jensen Huang: We continue to improve supply and expect demand to remain above available capacity for several quarters.
    """


def _transcript_text_with_header() -> str:
    return """
    Full transcript - Intel Corporation (INTC) Q1 2026:
    Published 05/20/2026
    Jonathan, Conference Call Operator, Moderator: Thank you for standing by, and welcome to the Intel Corporation first quarter earnings 2026 earnings conference call.
    David Zinsner: Revenue improved sequentially as client demand stabilized and cost discipline remained a priority.
    Lip-Bu Tan: We are focused on execution, product roadmap discipline, and strengthening our foundry customer pipeline.
    Analyst: Can you discuss margin recovery and capital spending priorities for the next several quarters?
    David Zinsner: We expect operating leverage to improve as product mix and spending controls support profitability.
    """


def test_build_manual_transcript_item_from_text_file() -> None:
    text_path = InMemoryTextPath(_transcript_text())

    item = build_manual_transcript_item(
        text_path=text_path,
        ticker="nvda",
        title="NVIDIA Q1 2027 earnings call transcript",
        published_at="2026-05-28T20:00:00Z",
        fiscal_quarter="q1 2027",
    )

    assert item["provider"] == "manual"
    assert item["ticker"] == "NVDA"
    assert item["title"] == "NVIDIA Q1 2027 earnings call transcript"
    assert item["published_at"] == 1779998400
    assert item["fiscal_quarter"] == "Q1_2027"
    assert "url" not in item
    assert "source_page" not in item["metadata"]
    assert "manual_text_path" not in item["metadata"]
    assert "import_method" not in item["metadata"]
    assert item["speaker_turns"]


def test_manual_import_infers_ticker_title_and_quarter_from_full_transcript_header() -> None:
    text_path = InMemoryTextPath(_transcript_text_with_header(), path="manual_transcripts/INTC_Q1_2026.txt")

    item = build_manual_transcript_item(text_path=text_path)

    assert item["ticker"] == "INTC"
    assert item["title"] == "Intel Corporation Q1 2026 earnings call transcript"
    assert item["fiscal_quarter"] == "Q1_2026"
    assert item["published_at"] == int(datetime(2026, 5, 20, tzinfo=UTC).timestamp())


def test_manual_import_extracts_speaker_with_commas() -> None:
    text_path = InMemoryTextPath(_transcript_text_with_header(), path="manual_transcripts/INTC_Q1_2026.txt")

    item = build_manual_transcript_item(text_path=text_path)

    assert item["speaker_turns"][0]["speaker"] == "Jonathan, Conference Call Operator, Moderator"
    assert item["speaker_turns"][0]["text"].startswith("Thank you for standing by")


def test_manual_import_explicit_metadata_overrides_header_inference() -> None:
    text_path = InMemoryTextPath(_transcript_text_with_header(), path="manual_transcripts/INTC_Q1_2026.txt")

    item = build_manual_transcript_item(
        text_path=text_path,
        ticker="INTC",
        title="Custom Intel transcript title",
        fiscal_quarter="Q2_2026",
        published_at="2026-06-01T12:30:00Z",
    )

    assert item["ticker"] == "INTC"
    assert item["title"] == "Custom Intel transcript title"
    assert item["fiscal_quarter"] == "Q2_2026"
    assert item["published_at"] == int(datetime(2026, 6, 1, 12, 30, tzinfo=UTC).timestamp())


def test_manual_import_uses_explicit_provider_id() -> None:
    text_path = InMemoryTextPath(_transcript_text())

    item = build_manual_transcript_item(
        text_path=text_path,
        ticker="NVDA",
        title="NVIDIA Q1 2027 earnings call transcript",
        provider_id="manual-nvda-q1-2027",
    )

    assert item["provider_id"] == "manual-nvda-q1-2027"


def test_manual_import_generates_stable_provider_id() -> None:
    text_path = InMemoryTextPath(_transcript_text())
    kwargs = {
        "text_path": text_path,
        "ticker": "NVDA",
        "title": "NVIDIA Q1 2027 earnings call transcript",
    }

    first = build_manual_transcript_item(**kwargs)
    second = build_manual_transcript_item(**kwargs)

    assert first["provider_id"] == second["provider_id"]
    assert first["provider_id"].startswith("NVDA:nvidia-q1-2027-earnings-call-transcript:")


def test_import_text_file_dry_run_does_not_send_to_ai_engine(monkeypatch) -> None:
    text_path = InMemoryTextPath(_transcript_text())

    class FailingClient:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("client should not be created in dry-run")

    monkeypatch.setattr(manual_import, "AiEngineTranscriptClient", FailingClient)

    result = import_text_file(
        text_path,
        ticker="NVDA",
        title="NVIDIA Q1 2027 earnings call transcript",
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["item"]["ticker"] == "NVDA"
    assert result["item"]["content_chars"] >= 200


def test_import_text_file_sends_to_ai_engine(monkeypatch) -> None:
    sent_items = []
    text_path = InMemoryTextPath(_transcript_text())

    class FakeClient:
        def __init__(self, base_url: str, *, timeout_seconds: float) -> None:
            self.base_url = base_url
            self.timeout_seconds = timeout_seconds

        def ingest_transcripts(self, items: list[dict]) -> dict:
            sent_items.extend(items)
            return {"status": "ok", "accepted_count": len(items)}

    monkeypatch.setattr(manual_import, "AiEngineTranscriptClient", FakeClient)

    result = import_text_file(
        text_path,
        ticker="NVDA",
        title="NVIDIA Q1 2027 earnings call transcript",
        ai_engine_url="http://ai-engine.test",
    )

    assert result["status"] == "sent"
    assert result["response"]["accepted_count"] == 1
    assert sent_items[0]["provider"] == "manual"
    assert sent_items[0]["content"].startswith("Sarah, Conference Operator")


def test_manual_import_rejects_short_text() -> None:
    text_path = InMemoryTextPath("Jensen Huang: Demand is strong.")

    try:
        build_manual_transcript_item(
            text_path=text_path,
            ticker="NVDA",
            title="NVIDIA Q1 2027 earnings call transcript",
        )
    except ManualTranscriptImportError as exc:
        assert "too short" in str(exc)
    else:
        raise AssertionError("Expected ManualTranscriptImportError")


def test_manual_import_rejects_html_or_error_shell_text() -> None:
    text_path = InMemoryTextPath("<html><body>500 something went wrong</body></html>")

    try:
        build_manual_transcript_item(
            text_path=text_path,
            ticker="NVDA",
            title="NVIDIA Q1 2027 earnings call transcript",
        )
    except ManualTranscriptImportError as exc:
        assert "error page or HTML shell" in str(exc)
    else:
        raise AssertionError("Expected ManualTranscriptImportError")


def test_manual_import_requires_title_when_header_is_missing() -> None:
    text_path = InMemoryTextPath(_transcript_text())

    try:
        build_manual_transcript_item(text_path=text_path, ticker="NVDA", title="")
    except ManualTranscriptImportError as exc:
        assert "title is required" in str(exc)
    else:
        raise AssertionError("Expected ManualTranscriptImportError")


def test_manual_import_requires_ticker_when_header_is_missing() -> None:
    text_path = InMemoryTextPath(_transcript_text())

    try:
        build_manual_transcript_item(text_path=text_path, title="NVIDIA Q1 2027 earnings call transcript")
    except ManualTranscriptImportError as exc:
        assert "ticker is required" in str(exc)
    else:
        raise AssertionError("Expected ManualTranscriptImportError")
