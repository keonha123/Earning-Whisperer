"""Structured operational events and daily webcast monitoring reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from .operations_progress import probe_outcomes, progress_issues, utc

try:
    from .failure_reasons import classify_stream_failure, classify_live_failure
except ImportError:
    from failure_reasons import classify_stream_failure, classify_live_failure


_WRITE_LOCK = threading.Lock()



def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _log_dir() -> Path:
    configured = os.getenv("OPERATIONS_LOG_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / ".runtime" / "operations"


def _redact_value(value: Any) -> Any:
    """Redact credentials in nested event details before JSON serialization."""
    try:
        from .database import redact_sensitive_text
    except ImportError:
        from database import redact_sensitive_text
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        return {str(key): _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_redact_value(item) for item in value]
    return value


def _date_value(value: date | str | None = None) -> date:
    if value is None:
        return _utc_now().date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def classify_error(error: str | None) -> str:
    return str(classify_failure(error)["category"])


def classify_failure(error: str | dict | None) -> dict[str, str]:
    """Keep the report API while using the same typed failure as retry policy."""
    failure = classify_live_failure(error)
    normalized = re.sub(r"https?://\S+|[0-9a-f]{8,}|\d+", "<value>", str(error or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()[:500]
    signature = "none" if failure["reason"] == "none" else hashlib.sha256(
        f"{failure['category']}|{failure['stage']}|{failure['error_code']}|{normalized}".encode("utf-8")
    ).hexdigest()[:16]
    return {**failure, "action": failure["next_action"], "signature": signature}


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
    failure = classify_failure({"error": error, "stage": details.get("stage"),
                                "error_code": details.get("error_code")}) if details.get("error_code") else classify_failure(error)
    payload: dict[str, Any] = {
        "timestamp": now.isoformat(),
        "event_type": event_type,
        "ticker": str(ticker).upper() if ticker else None,
        "call_id": str(call_id) if call_id is not None else None,
        "status": status,
        "error": _redact_value(str(error)[:1000]) if error else None,
        "error_category": failure["category"],
        "failure_stage": failure["stage"],
        "error_code": failure["error_code"],
        "next_action": failure["next_action"],
        "failure_action": failure["action"],
        "failure_signature": failure["signature"],
        "retry_reason": classify_stream_failure(error) if error else "none",
    }
    payload.update(
        {
            key: _redact_value(value)
            for key, value in details.items()
            if value is not None
        }
    )
    directory = _log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"events-{now.date().isoformat()}.jsonl"
    line = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return path


def purge_operation_logs(
    retention_days: int = 30,
    *,
    max_files: int = 2000,
) -> int:
    """Delete old/bounded JSONL and daily report files from the operations dir."""
    directory = _log_dir()
    if not directory.is_dir():
        return 0
    cutoff = _utc_now().timestamp() - max(1, int(retention_days)) * 86400
    files = [
        path
        for pattern in ("events-*.jsonl", "report-*.json", "report-*.md")
        for path in directory.glob(pattern)
        if path.is_file()
    ]
    removed = 0
    survivors: list[Path] = []
    for path in files:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
            else:
                survivors.append(path)
        except (FileNotFoundError, OSError):
            continue
    limit = max(1, int(max_files))
    if len(survivors) > limit:
        survivors.sort(key=lambda item: item.stat().st_mtime)
        for path in survivors[: len(survivors) - limit]:
            try:
                path.unlink()
                removed += 1
            except (FileNotFoundError, OSError):
                continue
    return removed


def _alert_state_path() -> Path:
    configured = os.getenv("OPERATIONS_ALERT_STATE_FILE", "").strip()
    return Path(configured) if configured else _log_dir() / "alerts-state.json"


def _load_alert_state() -> dict[str, Any]:
    path = _alert_state_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"active": {}, "last_attempt_at": {}}
    return value if isinstance(value, dict) else {"active": {}, "last_attempt_at": {}}


def _save_alert_state(state: dict[str, Any]) -> None:
    path = _alert_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    temporary.replace(path)


def _post_alert(webhook_url: str, payload: dict[str, Any], timeout_seconds: float) -> None:
    body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if not 200 <= int(response.status) < 300:
            raise RuntimeError(f"alert webhook returned HTTP {response.status}")


def check_operational_alerts(snapshot: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Emit deduplicated alerts for stale work, outbox backlog, and blocked sites."""
    try:
        try:
            from . import database
        except ImportError:
            import database
        counters = snapshot if snapshot is not None else database.get_operational_health_snapshot()
    except Exception as exc:
        record_event("operational_alert_check_failed", status="failed", error=str(exc))
        return []

    report = build_daily_report()
    blocked_categories = {"access_blocked", "registration_blocked", "auth_required"}
    blocked_tickers = {
        str(event.get("ticker")).upper()
        for event in report.get("events", [])
        if event.get("ticker") and str(event.get("error_category")) in blocked_categories
    }
    stale_count = int(counters.get("stale_probe_count", 0)) + int(counters.get("stale_capture_count", 0))
    due_outbox = int(counters.get("due_outbox_count", 0))
    blocked_count = len(blocked_tickers)
    issues: list[dict[str, Any]] = []
    if stale_count >= max(1, int(os.getenv("OPERATIONS_ALERT_STALE_COUNT", "1"))):
        issues.append({"key": "stale_operations", "severity": "critical", "count": stale_count})
    if due_outbox >= max(1, int(os.getenv("OPERATIONS_ALERT_OUTBOX_COUNT", "10"))):
        issues.append({
            "key": "transcript_outbox_backlog",
            "severity": "warning",
            "count": due_outbox,
            "total": int(counters.get("total_outbox_count", 0)),
            "failed": int(counters.get("failed_outbox_count", 0)),
        })
    archive_records = int(counters.get("archive_spool_records", 0))
    archive_bytes = int(counters.get("archive_spool_bytes", 0))
    if archive_records >= max(1, int(os.getenv("OPERATIONS_ALERT_ARCHIVE_SPOOL_RECORDS", "1"))) or (
        archive_bytes > 0 and counters.get("archive_spool_count_capped")
    ):
        issues.append({"key": "transcript_archive_backlog", "severity": "warning",
                       "count": archive_records, "bytes": archive_bytes,
                       "count_capped": int(counters.get("archive_spool_count_capped", 0))})
    if blocked_count >= max(1, int(os.getenv("OPERATIONS_ALERT_BLOCKED_SITE_COUNT", "3"))):
        issues.append({"key": "external_site_blocked", "severity": "warning", "count": blocked_count})

    now = _utc_now()
    # Include recent attempts across UTC midnight; history alone is never an
    # active alert without the current call/revision in the DB snapshot.
    recent_events = _read_events(now.date() - timedelta(days=1)) + report['events']
    results = probe_outcomes(recent_events)
    calls = counters.get('live_calls', [])
    from .operations_progress import annotate_waiting_observation
    calls = [annotate_waiting_observation(dict(call), now=now) for call in calls]
    issues.extend(progress_issues(results, calls, now=now,
        repeat_threshold=max(2, int(os.getenv('OPERATIONS_ALERT_REPEAT_COUNT', '3'))),
        no_text_seconds=max(60, int(os.getenv('OPERATIONS_ALERT_NO_TEXT_SECONDS', '300'))),
        waiting_grace_seconds=max(300, int(os.getenv('OPERATIONS_ALERT_WAITING_GRACE_SECONDS', '900')))))
    try:
        from .stt_worker.audio_rescue import rescue_health_snapshot
        capacity = rescue_health_snapshot()
        counters['audio_rescue'] = capacity
        if capacity.get('available_for_next_recording') is False:
            issues.append({'key': 'audio_rescue_capacity', 'severity': 'critical', 'count': 1,
                'error_code': 'AUDIO_RESCUE_BUDGET_UNAVAILABLE',
                'failure_stage': 'audio_storage', 'next_action': 'reclaim_closed_audio',
                'state': 'next_recording_allocation_blocked', **capacity})
    except (ImportError, OSError, ValueError):
        counters['audio_rescue_health_unavailable'] = 1
        # Still surface a typed allocation failure when capacity cannot be read.
        for row in results:
            stamp = utc(row.get('timestamp'))
            if (row.get('error_code') == 'AUDIO_RESCUE_BUDGET_UNAVAILABLE' and stamp
                    and 0 <= (now-stamp).total_seconds() <= 600):
                issues.append({'key': 'audio_rescue_capacity', 'severity': 'critical', 'count': 1,
                    'error_code': row['error_code'], 'next_action': 'reclaim_closed_audio',
                    'state': 'recent_allocation_failed_capacity_unknown'})
                break
    cooldown = max(60, int(os.getenv("OPERATIONS_ALERT_COOLDOWN_SECONDS", "1800")))
    state = _load_alert_state()
    active = state.setdefault("active", {})
    last_attempt = state.setdefault("last_attempt_at", {})
    current = {str(issue["key"]): issue for issue in issues}
    webhook_url = os.getenv("OPERATIONS_ALERT_WEBHOOK_URL", "").strip()
    state['notification_mode'] = 'webhook' if webhook_url else 'local_only'
    state['checked_at'] = now.isoformat()
    try:
        timeout = max(1.0, float(os.getenv("OPERATIONS_ALERT_TIMEOUT_SECONDS", "5")))
    except ValueError:
        timeout = 5.0
    notified: list[dict[str, Any]] = []

    for key, issue in current.items():
        previous_issue = active.get(key)
        active[key] = {**issue, 'notification_mode': state['notification_mode']}
        previous_attempt = last_attempt.get(key)
        try:
            elapsed = (now - datetime.fromisoformat(previous_attempt)).total_seconds() if previous_attempt else None
        except (TypeError, ValueError):
            elapsed = None
        issue_cooldown = min(cooldown, max(60, int(os.getenv('OPERATIONS_ALERT_LIVE_COOLDOWN_SECONDS', '300')))) if key.startswith(('repeated_live_failure:', 'live_text_progress:', 'audio_rescue_capacity')) else cooldown
        if elapsed is not None and elapsed < issue_cooldown and (
                not previous_issue or previous_issue.get('failure_signature') == issue.get('failure_signature')):
            continue
        payload = {
            "source": "earning-whisperer-data-pipeline",
            "type": "operational_alert",
            "timestamp": now.isoformat(),
            "issue": issue,
            "counters": counters,
        }
        try:
            if webhook_url:
                _post_alert(webhook_url, payload, timeout)
            last_attempt[key] = now.isoformat()
            issue = {**issue, 'notification_mode': state['notification_mode'],
                     'external_notification_sent': bool(webhook_url)}
            active[key] = issue
            notified.append(issue)
            record_event("operational_alert", status="active", alert_key=key, **issue)
            print(f"[OperationsAlert] {key} count={issue.get('count')}", flush=True)
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            last_attempt[key] = now.isoformat()
            record_event("operational_alert_delivery_failed", status="failed", alert_key=key, error=str(exc))

    for key in set(active) - set(current):
        recovered = active.pop(key)
        record_event("operational_alert_recovered", status="recovered", alert_key=key, previous=recovered)

    try:
        _save_alert_state(state)
    except OSError as exc:
        record_event("operational_alert_state_write_failed", status="failed", error=str(exc))
    return notified


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


def _latest_probe_per_ticker(probe_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse repeated scheduler probes to one comparable result per ticker."""
    latest: dict[str, dict[str, Any]] = {}
    for event in probe_results:
        ticker = str(event.get("ticker") or "").upper()
        if not ticker:
            continue
        previous = latest.get(ticker)
        if previous is None or str(event.get("timestamp") or "") >= str(previous.get("timestamp") or ""):
            latest[ticker] = event
    return latest


def build_daily_report(report_date: date | str | None = None) -> dict[str, Any]:
    day = _date_value(report_date)
    events = _read_events(day)
    # Reclassify older JSONL entries so the report improves without rewriting
    # historical logs or waiting for the scheduler to restart.
    for event in events:
        if event.get("error"):
            typed = event.get("error_code") not in {None, "", "UNCLASSIFIED_FAILURE"}
            failure = classify_failure({"error": event.get("error"),
                "stage": event.get("failure_stage"), "error_code": event.get("error_code")}
                if typed else event.get("error"))
            event["error_category"] = failure["category"]
            event["failure_stage"] = failure["stage"]
            event["failure_action"] = failure["action"]
            event["failure_signature"] = failure["signature"]
            event['error_code'] = failure['error_code']
            event['next_action'] = failure['next_action']
    probe_results = probe_outcomes(events)
    latest_probes = _latest_probe_per_ticker(probe_results)
    latest_probe_values = list(latest_probes.values())
    successes = sorted({str(event["ticker"]) for event in probe_results if event['outcome'] == 'audio_ready' and event.get("ticker")})
    failures = [event for event in probe_results if event['outcome'] == 'failed']
    latest_successes = sorted(
        ticker for ticker, event in latest_probes.items() if event['outcome'] == 'audio_ready'
    )
    latest_failures = [event for event in latest_probe_values if event['outcome'] == 'failed']
    latest_category_counts = Counter(
        str(event.get("error_category") or "other") for event in latest_failures
    )
    category_counts = Counter(str(event.get("error_category") or "other") for event in failures)
    action_counts = Counter(str(event.get("failure_action") or "manual_triage") for event in failures)
    signature_counts = Counter(str(event.get("failure_signature") or "unknown") for event in failures)
    return {
        "report_date": day.isoformat(),
        "generated_at": _utc_now().isoformat(),
        "event_count": len(events),
        "event_types": dict(Counter(str(event.get("event_type") or "unknown") for event in events)),
        "probe_count": len(probe_results),
        'probe_outcome_counts': dict(Counter(row['outcome'] for row in probe_results)),
        'probe_waiting_count': sum(row['outcome'] == 'waiting' for row in probe_results),
        'probe_deferred_count': sum(row['outcome'] == 'deferred' for row in probe_results),
        'probe_unknown_count': sum(row['outcome'] == 'unknown' for row in probe_results),
        'probe_outcomes': probe_results,
        'live_capture_success_assessed': False,
        'alert_status': _load_alert_state(),
        "probe_success_count": len(successes),
        "probe_success_tickers": successes,
        "probe_failure_count": len(failures),
        "probe_failure_categories": dict(sorted(category_counts.items())),
        "probe_failure_actions": dict(sorted(action_counts.items())),
        "probe_failure_signatures": dict(signature_counts.most_common(20)),
        "probe_failure_tickers": sorted({str(event["ticker"]) for event in failures if event.get("ticker")}),
        "latest_probe_ticker_count": len(latest_probes),
        "latest_probe_success_count": len(latest_successes),
        "latest_probe_success_tickers": latest_successes,
        "latest_probe_failure_count": len(latest_failures),
        "latest_probe_failure_categories": dict(sorted(latest_category_counts.items())),
        "latest_probe_failure_tickers": sorted(latest_probes[ticker]["ticker"] for ticker in latest_probes if latest_probes[ticker]['outcome'] == 'failed'),
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
        f"- Waiting for event: {report['probe_waiting_count']}",
        f"- Deferred handoff: {report['probe_deferred_count']}",
        f"- Unknown outcome (missing evidence): {report['probe_unknown_count']}",
        '- Audio-ready is not proof of live speech or saved text.',
        f"- Alert delivery: {report['alert_status'].get('notification_mode', 'not_checked')}",
        f"- Latest unique tickers: {report['latest_probe_ticker_count']}",
        f"- Latest unique audio-ready: {report['latest_probe_success_count']}",
        f"- Latest unique failures: {report['latest_probe_failure_count']}",
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
    lines.extend(["", "## Suggested follow-up actions", ""])
    for action, count in report["probe_failure_actions"].items():
        lines.append(f"- `{action}`: {count}")
    lines.extend(["", "## Latest unique failure categories", ""])
    for category, count in report["latest_probe_failure_categories"].items():
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
