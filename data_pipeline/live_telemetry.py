"""Bounded, best-effort live evidence with no database or optional dependencies."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_LOCK = threading.Lock()
_SENSITIVE_KEY = re.compile(r"password|passwd|secret|token|authorization|cookie|credential|api[_-]?key|email|first[_-]?name|last[_-]?name|phone|^(?:form_)?values?$", re.I)
_SAFE_QUERY_KEYS = {"eventid", "event_id", "event", "id", "webcastid", "webcast_id", "companyid", "locale", "lang"}
_URL = re.compile(r"https?://[^\s<>\"']+")


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        if parsed.port:
            hostname += ":" + str(parsed.port)
        query = [(key, val if key.lower() in _SAFE_QUERY_KEYS else "[redacted]")
                 for key, val in parse_qsl(parsed.query, keep_blank_values=True)]
        return urlunsplit((parsed.scheme, hostname, parsed.path, urlencode(query), ""))
    except Exception:
        return "[invalid URL]"


def _redact(value, secrets: tuple[str, ...], depth: int = 0, budget=None):
    if budget is None:
        budget = [300, 24000]
    budget[0] -= 1
    if depth > 6 or budget[0] < 0:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(key)[:100]: "[redacted]" if _SENSITIVE_KEY.search(str(key)) else _redact(item, secrets, depth + 1, budget)
                for key, item in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets, depth + 1, budget) for item in value[:100]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)[:max(0, min(6000, budget[1]))]
    budget[1] -= len(text)
    text = _URL.sub(lambda match: _safe_url(match.group()), text)
    text = re.sub(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", text)
    text = re.sub(r"(?i)\b(authorization|password|passwd|secret|token|api[_-]?key|cookie)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", text)
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text


_ENVELOPE_KEYS = {"stage", "event", "status", "timestamp", "timestamp_utc", "call_id", "ticker",
                  "schedule_revision", "attempt_id", "probe_attempt_id", "capture_session_id", "last_progress_at"}


def _bounded_record(record, limit=16000):
    """Keep identity/progress and small counters when a caller supplies bulky DOM."""
    result = dict(record)
    encoded_size = len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode())
    if encoded_size <= limit:
        return result
    candidates = sorted(
        ((len(json.dumps({key: value}, ensure_ascii=True, allow_nan=False).encode()), key)
         for key, value in result.items() if key not in _ENVELOPE_KEYS and key != "truncated_fields"),
        reverse=True,
    )
    for field_size, key in candidates:
        result.pop(key)
        result["truncated_fields"] = int(result.get("truncated_fields", 0)) + 1
        encoded_size -= max(0, field_size - 2)
        if encoded_size + 64 <= limit:
            break
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) > limit:
        # Even malformed, oversized context must not produce unbounded logs.
        result = {key: value[:512] if isinstance(value, str) else value for key, value in result.items()}
    return result


def _atomic_json(path: Path, data: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".progress-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, allow_nan=False)
            handle.flush()
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def emit_live_event(stage, event, status=None, progress=False, *, directory=None, context=None, **payload):
    """Append an event and atomically merge the stage snapshot; never raise.

    WEBCAST_PROGRESS_DIR is one attempt's directory. Unset means disabled.
    A false progress flag preserves last_progress_at and omitted counters.
    Returns the merged snapshot on success, otherwise None (including busy I/O).
    """
    locked = False
    try:
        configured = str(directory if directory is not None else os.getenv("WEBCAST_PROGRESS_DIR", "")).strip()
        if not configured:
            return None
        stage = re.sub(r"[^a-zA-Z0-9_-]", "_", str(stage))[:64] or "unknown"
        directory = Path(configured)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not _LOCK.acquire(timeout=0.2):
            return None
        locked = True
        with (directory / ".progress.lock").open("a") as lock:
            deadline = time.monotonic() + .2
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        return None
                    time.sleep(.005)
            try:
                path = directory / f"{stage}.json"
                try:
                    previous = json.loads(path.read_text(encoding="utf-8")) if path.stat().st_size <= 1024 * 1024 else {}
                    if not isinstance(previous, dict):
                        previous = {}
                except (OSError, ValueError):
                    previous = {}
                secrets = tuple(sorted({value for key, value in os.environ.items()
                                        if _SENSITIVE_KEY.search(key) and len(value) >= 4}, key=len, reverse=True))
                now = datetime.now(timezone.utc).isoformat()
                data = _redact(payload, secrets)
                data.update({"stage": stage, "event": str(event)[:100], "status": str(status)[:100] if status is not None else previous.get("status"),
                             "timestamp": now, "timestamp_utc": now,
                             "call_id": os.getenv("WEBCAST_CALL_DB_ID") or previous.get("call_id", ""),
                             "ticker": os.getenv("TICKER") or os.getenv("WEBCAST_TICKER") or previous.get("ticker", ""),
                             "schedule_revision": os.getenv("WEBCAST_SCHEDULE_REVISION") or previous.get("schedule_revision", ""),
                             "probe_attempt_id": os.getenv("WEBCAST_ATTEMPT_ID") or previous.get("probe_attempt_id", ""),
                             "capture_session_id": os.getenv("STT_CAPTURE_SESSION_ID") or previous.get("capture_session_id", ""),
                             "last_progress_at": now if progress else previous.get("last_progress_at")})
                if isinstance(context, dict):
                    for key in ("call_id", "ticker", "schedule_revision", "attempt_id", "probe_attempt_id", "capture_session_id"):
                        if key in context:
                            value = context[key]
                            data[key] = value if isinstance(value, (str, int, float, bool)) or value is None else str(value)[:512]
                if "attempt_id" not in data:
                    data["attempt_id"] = data["probe_attempt_id"]
                elif isinstance(context, dict) and "probe_attempt_id" not in context:
                    data["probe_attempt_id"] = data["attempt_id"]
                data = _bounded_record({key: _redact(value, secrets) if key in _ENVELOPE_KEYS else value
                                        for key, value in data.items()})
                merged = {**previous, **data}
                # Latest has bounded keys because every payload is bounded and stages
                # use a fixed vocabulary; cap accumulated optional keys as well.
                if len(merged) > 200:
                    merged = {**dict(list(previous.items())[-100:]), **data}
                merged = _bounded_record(merged, limit=64000)
                _atomic_json(path, merged)
                log_path = directory / "events.jsonl"
                try:
                    max_bytes = max(16384, min(16 * 1024 * 1024, int(os.getenv("WEBCAST_PROGRESS_MAX_BYTES", "2097152"))))
                except ValueError:
                    max_bytes = 2097152
                line = json.dumps(data, ensure_ascii=True, allow_nan=False) + "\n"
                if log_path.exists() and log_path.stat().st_size + len(line.encode()) > max_bytes:
                    os.replace(log_path, directory / "events.previous.jsonl")
                descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(line)
                return merged
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except Exception:
        return None
    finally:
        if locked:
            _LOCK.release()


def read_progress_snapshot(directory=None):
    """Return {stage: latest_snapshot}; malformed/missing files are ignored."""
    try:
        configured = str(directory or os.getenv("WEBCAST_PROGRESS_DIR", "")).strip()
        if not configured:
            return {}
        result = {}
        for path in list(Path(configured).glob("*.json"))[:64]:
            try:
                if path.stat().st_size > 1024 * 1024:
                    continue
                row = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(row, dict) and row.get("stage") == path.stem:
                    result[path.stem] = row
            except (OSError, ValueError):
                continue
        return result
    except Exception:
        return {}


def archive_spool_health(path=None):
    """Bounded read-only archive backlog counters; never enumerate old attempts.

    Bytes are exact at stat time; record count is capped at 1,000 and 1 MiB of
    input. This measures durable local records awaiting DB replay, not loss.
    """
    empty = {"archive_spool_bytes": 0, "archive_spool_records": 0,
             "archive_spool_count_capped": 0, "archive_spool_read_error": 0}
    try:
        configured = path or os.getenv("TRANSCRIPT_ARCHIVE_SPOOL_PATH", "").strip()
        spool = Path(configured) if configured else Path(__file__).resolve().parent / ".runtime" / "transcript-archive-spool.jsonl"
        try:
            size = spool.stat().st_size
        except FileNotFoundError:
            return empty
        if size <= 0:
            return empty
        with spool.open("rb") as handle:
            data = handle.read(1024 * 1024)
        complete = data.splitlines()
        if size > len(data) and data and not data.endswith(b"\n"):
            complete = complete[:-1]
        rows = sum(bool(line.strip()) for line in complete[:1000])
        return {**empty, "archive_spool_bytes": size, "archive_spool_records": rows,
                "archive_spool_count_capped": int(size > len(data) or len(complete) > 1000)}
    except Exception:
        return {**empty, "archive_spool_read_error": 1}
