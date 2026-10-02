"""Structured operational events and daily webcast monitoring reports."""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()
_CATEGORY_PATTERNS = (
    ("not_live_yet", re.compile(r"NOT_LIVE_YET|not yet available|has not started", re.I)),
    ("registration", re.compile(r"REGISTRATION_REQUIRED|registration|Q4", re.I)),
    ("access_blocked", re.compile(r"blocked|forbidden|access denied|captcha|403|429", re.I)),
    ("no_candidate", re.compile(r"no playback control|no candidate|candidate", re.I)),
    ("audio_not_detected", re.compile(r"AUDIO_NOT_DETECTED|audio was not detected|audible", re.I)),
    ("timeout", re.compile(r"timed out|timeout|TIMED_OUT", re.I)),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _log_dir() -> Path:
    configured = os.getenv("OPERATIONS_LOG_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / ".runtime" / "operations"


def _date_value(value: date | str | None = None) -> date:
    if value is None:
        return _utc_now().date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def classify_error(error: str | None) -> str:
    text = str(error or "").strip()
    if not text:
        return "none"
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "other"


def record_event(
    event_type: str,
    *,
    ticker: str | None = None,
    call_id: str | int | None = None,
    status: str | None = None,
    error: str | None = None,
    **details: Any,
) -> Path:
    """Append one redacted, machine-readable event to the current UTC day's log."""
    now = _utc_now()
    payload: dict[str, Any] = {
        "timestamp": now.isoformat(),
        "event_type": event_type,
        "ticker": str(ticker).upper() if ticker else None,
        "call_id": str(call_id) if call_id is not None else None,
        "status": status,
        "error": str(error)[:1000] if error else None,
        "error_category": classify_error(error),
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    directory = _log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"events-{now.date().isoformat()}.jsonl"
    line = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return path


def _read_events(report_date: date) -> list[dict[str, Any]]:
    path = _log_dir() / f"events-{report_date.isoformat()}.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def build_daily_report(report_date: date | str | None = None) -> dict[str, Any]:
    day = _date_value(report_date)
    events = _read_events(day)
    probe_results = [event for event in events if event.get("event_type") == "probe_result"]
    successes = sorted({str(event["ticker"]) for event in probe_results if event.get("status") == "stream_ready" and event.get("ticker")})
    failures = [event for event in probe_results if event.get("status") != "stream_ready"]
    category_counts = Counter(str(event.get("error_category") or "other") for event in failures)
    return {
        "report_date": day.isoformat(),
        "generated_at": _utc_now().isoformat(),
        "event_count": len(events),
        "event_types": dict(Counter(str(event.get("event_type") or "unknown") for event in events)),
        "probe_count": len(probe_results),
        "probe_success_count": len(successes),
        "probe_success_tickers": successes,
        "probe_failure_count": len(failures),
        "probe_failure_categories": dict(sorted(category_counts.items())),
        "probe_failure_tickers": sorted({str(event["ticker"]) for event in failures if event.get("ticker")}),
        "events": events,
    }


def write_daily_report(report_date: date | str | None = None) -> tuple[Path, Path]:
    report = build_daily_report(report_date)
    directory = _log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    day = report["report_date"]
    json_path = directory / f"report-{day}.json"
    markdown_path = directory / f"report-{day}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    lines = [
        f"# Webcast Operations Report {day}",
        "",
        f"- Events: {report['event_count']}",
        f"- Probes: {report['probe_count']}",
        f"- Audio-ready: {report['probe_success_count']}",
        f"- Probe failures: {report['probe_failure_count']}",
        "",
        "## Audio-ready tickers",
        "",
        ", ".join(report["probe_success_tickers"]) or "None",
        "",
        "## Failure categories",
        "",
    ]
    for category, count in report["probe_failure_categories"].items():
        lines.append(f"- `{category}`: {count}")
    lines.extend(["", "## Failure tickers", "", ", ".join(report["probe_failure_tickers"]) or "None", ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a daily webcast operations report.")
    parser.add_argument("--report", default=None, help="UTC date in YYYY-MM-DD format; defaults to today.")
    args = parser.parse_args(argv)
    json_path, markdown_path = write_daily_report(args.report)
    print(f"JSON_REPORT={json_path}")
    print(f"MARKDOWN_REPORT={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
