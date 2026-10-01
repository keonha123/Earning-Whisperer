from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any

from .ai_engine_client import AiEngineTranscriptClient
from .config import get_transcript_settings


logger = logging.getLogger("manual-transcript-import")

MIN_MANUAL_TRANSCRIPT_CHARS = 200
TEXT_ERROR_MARKERS = (
    "<!doctype",
    "<html",
    "something went wrong",
    "cloudflare",
    "please enable cookies",
    "are you a robot",
    "access denied",
)


class ManualTranscriptImportError(RuntimeError):
    pass


def build_manual_transcript_item(
    *,
    text_path: Path,
    ticker: str = "",
    title: str = "",
    provider_id: str = "",
    published_at: str = "",
    fiscal_quarter: str = "",
) -> dict[str, Any]:
    if not text_path.exists():
        raise ManualTranscriptImportError(f"Transcript text file does not exist: {text_path}")

    content = _normalize_content(text_path.read_text(encoding="utf-8"))
    _validate_manual_text(content)
    inferred = _infer_metadata_from_text(content)
    normalized_ticker = ticker.strip().upper() or inferred.get("ticker", "")
    normalized_title = " ".join((title.strip() or inferred.get("title", "")).split())
    if not normalized_ticker:
        raise ManualTranscriptImportError("ticker is required; pass --ticker or use a 'Full transcript - Company (TICKER) Qn YYYY:' header")
    if not normalized_title:
        raise ManualTranscriptImportError("title is required; pass --title or use a 'Full transcript - Company (TICKER) Qn YYYY:' header")
    document_provider_id = provider_id.strip() or _manual_provider_id(
        ticker=normalized_ticker,
        title=normalized_title,
        content=content,
    )
    published_at_value = published_at.strip() or inferred.get("published_at", "")
    parsed_published_at = _published_at_to_epoch(published_at_value) if published_at_value else None
    normalized_quarter = _normalize_quarter(fiscal_quarter) or inferred.get("fiscal_quarter")

    return {
        "provider": "manual",
        "provider_id": document_provider_id,
        "ticker": normalized_ticker,
        "title": normalized_title,
        "published_at": parsed_published_at,
        "fiscal_quarter": normalized_quarter,
        "content": content,
        "speaker_turns": _extract_speaker_turns(content),
        "metadata": {
            "content_chars": len(content),
        },
    }


def import_text_file(
    text_path: str | Path,
    *,
    ticker: str = "",
    title: str = "",
    provider_id: str = "",
    published_at: str = "",
    fiscal_quarter: str = "",
    ai_engine_url: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    path = text_path if hasattr(text_path, "read_text") else Path(text_path)
    item = build_manual_transcript_item(
        text_path=path,
        ticker=ticker,
        title=title,
        provider_id=provider_id,
        published_at=published_at,
        fiscal_quarter=fiscal_quarter,
    )
    if dry_run:
        return {"status": "dry_run", "accepted_count": 0, "item": _summary(item)}

    settings = get_transcript_settings()
    client = AiEngineTranscriptClient(
        (ai_engine_url or settings.ai_engine_url).rstrip("/"),
        timeout_seconds=settings.request_timeout_seconds,
    )
    response = client.ingest_transcripts([item])
    return {"status": "sent", "item": _summary(item), "response": response}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a manually copied earnings-call transcript text file.")
    parser.add_argument("--text", required=True, help="Path to the transcript text file.")
    parser.add_argument("--ticker", default="", help="Ticker symbol, e.g. NVDA. Inferred from transcript header when omitted.")
    parser.add_argument("--title", default="", help="Transcript title. Inferred from transcript header when omitted.")
    parser.add_argument("--provider-id", default="", help="Stable source id. Defaults to ticker/title/content hash.")
    parser.add_argument("--published-at", default="", help="Published time. Accepts ISO datetime or Unix epoch.")
    parser.add_argument("--fiscal-quarter", default="", help="Fiscal quarter, e.g. Q1_2027.")
    parser.add_argument("--ai-engine-url", default="", help="Override AI_ENGINE_URL.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print a summary without sending to ai-engine.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    args = build_parser().parse_args(argv)
    try:
        result = import_text_file(
            args.text,
            ticker=args.ticker,
            title=args.title,
            provider_id=args.provider_id,
            published_at=args.published_at,
            fiscal_quarter=args.fiscal_quarter,
            ai_engine_url=args.ai_engine_url,
            dry_run=args.dry_run,
        )
    except ManualTranscriptImportError as exc:
        logger.error("%s", exc)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": item.get("provider"),
        "provider_id": item.get("provider_id"),
        "ticker": item.get("ticker"),
        "title": item.get("title"),
        "published_at": item.get("published_at"),
        "fiscal_quarter": item.get("fiscal_quarter"),
        "content_chars": len(str(item.get("content") or "")),
        "speaker_turn_count": len(item.get("speaker_turns") or []),
    }


def _normalize_content(value: str) -> str:
    return "\n".join(line.strip() for line in str(value or "").replace("\r\n", "\n").split("\n") if line.strip())


def _validate_manual_text(content: str) -> None:
    lower = content[:5000].lower()
    for marker in TEXT_ERROR_MARKERS:
        if marker in lower:
            raise ManualTranscriptImportError(
                f"Transcript text looks like an error page or HTML shell; found marker: {marker}"
            )
    if len(content) < MIN_MANUAL_TRANSCRIPT_CHARS:
        raise ManualTranscriptImportError(
            f"Transcript text is too short: {len(content)} chars; minimum is {MIN_MANUAL_TRANSCRIPT_CHARS}"
        )


def _manual_provider_id(*, ticker: str, title: str, content: str) -> str:
    seed = "|".join([ticker.upper(), title, content[:4000]])
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48].strip("-")
    return f"{ticker.upper()}:{slug or 'manual'}:{digest}"


def _infer_metadata_from_text(content: str) -> dict[str, str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    first_line = lines[0] if lines else ""
    published_at = _infer_published_at(lines[:4])
    match = re.search(
        r"full\s+transcript\s*[-:]\s*(?P<company>.+?)\s+\((?P<ticker>[A-Z][A-Z0-9.\-]{0,9})\)\s+(?P<quarter>Q[1-4]\s+\d{4}(?:/\d{4})?)\s*:?",
        first_line,
        flags=re.I,
    )
    if not match:
        return {"published_at": published_at} if published_at else {}
    company = " ".join(match.group("company").split())
    ticker = match.group("ticker").upper()
    fiscal_quarter = _normalize_quarter(match.group("quarter"))
    title_parts = [company, fiscal_quarter.replace("_", " ") if fiscal_quarter else "", "earnings call transcript"]
    title = " ".join(part for part in title_parts if part)
    inferred = {
        "ticker": ticker,
        "fiscal_quarter": fiscal_quarter or "",
        "title": title,
    }
    if published_at:
        inferred["published_at"] = published_at
    return inferred


def _infer_published_at(lines: list[str]) -> str | None:
    for line in lines:
        match = re.fullmatch(
            r"published(?:\s+at)?\s*:?[ \t]*(?P<date>\d{1,2}/\d{1,2}/\d{4})",
            line,
            flags=re.I,
        )
        if match:
            return match.group("date")
    return None


def _normalize_quarter(value: str) -> str | None:
    raw = value.strip()
    return raw.upper().replace(" ", "_") if raw else None


def _published_at_to_epoch(value: str) -> int:
    raw = value.strip()
    if not raw:
        raise ManualTranscriptImportError("published-at must not be empty")
    try:
        return int(float(raw))
    except ValueError:
        pass
    try:
        parsed = datetime.strptime(raw, "%m/%d/%Y").replace(tzinfo=UTC)
        return int(parsed.timestamp())
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManualTranscriptImportError(f"Invalid published-at value: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _extract_speaker_turns(text: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    speaker_line = r"[A-Z][^\n:]{1,100}"
    pattern = re.compile(
        rf"^(?P<speaker>{speaker_line}):[ \t]+(?P<text>\S.*?)"
        rf"(?=^(?:{speaker_line}):[ \t]+\S|\Z)",
        re.M | re.S,
    )
    for match in pattern.finditer(text):
        content = " ".join(match.group("text").split())
        if len(content) < 20:
            continue
        turns.append({"speaker": match.group("speaker").strip(), "text": content[:2000]})
        if len(turns) >= 120:
            break
    return turns


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ManualTranscriptImportError",
    "build_manual_transcript_item",
    "build_parser",
    "import_text_file",
    "main",
]
