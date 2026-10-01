"""Pure schedule and retry decisions."""

import os
import re
from datetime import date, datetime, timedelta, timezone
from math import ceil
from typing import Any, Dict
from zoneinfo import ZoneInfo

from ..failure_reasons import classify_stream_failure


_PROBE_FUTURE_EVENT_DATE_PATTERN = re.compile(
    r"scheduled\s+event\s+date\s+is\s+in\s+the\s+future:\s*"
    r"(?P<date>"
    r"(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})|"
    r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2})|"
    r"(?:\d{1,2}/\d{1,2}/\d{4})"
    r")",
    re.IGNORECASE,
)

_PROBE_FUTURE_EVENT_TIME_PATTERN = re.compile(
    r"scheduled\s+event\s+time\s+is\s+in\s+the\s+future:\s*"
    r"(?P<datetime>"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})"
    r")",
    re.IGNORECASE,
)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def _normalized_schedule_ticker(value: object) -> str:
    return str(value or "").strip().upper().replace(".", "-")


def _coerce_schedule_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def capture_retry_window(call: Dict[str, Any], *, now: datetime | None = None) -> Dict[str, Any]:
    """Bound *new* captures after an earlier capture, never an active recording.

    Expired clock evidence remains historical evidence: losing freshness must
    not turn a completed day's retry into an unlimited date-only watch. Fresh
    official rescheduling may move the window; we preserve the original data.
    First discovery with an uncertain clock remains eligible for correction.
    """
    attempted = bool(call.get('capture_session_id')) or int(call.get('capture_attempts') or 0) > 0
    if not attempted:
        return {'expired': False, 'reason': None}
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    minutes = _env_int('DATE_STREAM_NEAR_END_MINUTES', 180)
    value = call.get('scheduled_at_utc')
    try:
        start = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
    except (ValueError, TypeError):
        start = None
    if start is not None:
        end = start + timedelta(minutes=minutes)
        expired = now > end
    else:
        day = _coerce_schedule_date(call.get('webcast_date') or call.get('earning_at'))
        if day is None:
            return {'expired': False, 'reason': None}
        zone = ZoneInfo(os.getenv('DATE_STREAM_WATCH_TIMEZONE', 'America/New_York'))
        # Unknown time gets the entire event day plus a midnight continuation
        # allowance. Existing captures may continue beyond it without a limit.
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), zone).astimezone(timezone.utc) + timedelta(minutes=minutes)
        expired = now >= end
    return {'expired': expired, 'reason': 'capture_retry_window_expired' if expired else None,
            'retry_window_end': end.astimezone(timezone.utc).isoformat()}


def future_event_date_from_probe_error(error: str | None) -> date | None:
    """Extract the concrete future event date emitted by the browser probe."""
    match = _PROBE_FUTURE_EVENT_DATE_PATTERN.search(str(error or ""))
    if not match:
        return None

    value = re.sub(r"\s+", " ", match.group("date")).strip()
    for date_format in (
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def future_event_time_from_probe_error(error: str | None) -> datetime | None:
    """Extract the exact UTC event start emitted by a live browser probe."""
    match = _PROBE_FUTURE_EVENT_TIME_PATTERN.search(str(error or ""))
    if not match:
        return None
    value = match.group("datetime").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def probe_error_date_mismatch(
    error: str | None,
    expected_date: object,
) -> date | None:
    """Return the observed page date only when it conflicts with the call date."""
    observed_date = future_event_date_from_probe_error(error)
    stored_date = _coerce_schedule_date(expected_date)
    if observed_date is None or stored_date is None or observed_date == stored_date:
        return None
    return observed_date


def stream_probe_retry_policy(
    error: str | None,
    *,
    watch_state: str | None = None,
    expected_date: object | None = None,
) -> Dict[str, Any]:
    """Return a bounded retry policy without making a live window go blind.

    Schedule contradictions should trigger a targeted refresh.  Access barriers
    (CAPTCHA, login links, rate limits) are deliberately cooled down for much
    longer, while a near-live call continues to receive short candidate checks.
    """
    # Browser evidence uses both human-readable text and machine markers such
    # as ``NOT_LIVE_YET``. Normalize separators before classifying it so the
    # live scheduler does not accidentally apply the long generic cooldown.
    value = re.sub(r"[_-]+", " ", str(error or "").lower())
    near_live = str(watch_state or "").lower() in {"near_live", "event_window", "date_only"}
    future_start = future_event_time_from_probe_error(error)
    if future_start is not None:
        early_entry = _nonnegative_env_int(
            "DATE_STREAM_EARLY_ENTRY_MINUTES",
            5,
        )
        retry_at = future_start - timedelta(minutes=early_entry)
        remaining_minutes = ceil(
            (retry_at - datetime.now(timezone.utc)).total_seconds() / 60
        )
        if remaining_minutes > 0:
            return {
                "reason": "scheduled_start_wait",
                "retry_delay_minutes": remaining_minutes,
                "requires_schedule_refresh": False,
            }
    explicit_mismatch_markers = (
        "candidate ticker contradicts target call",
        "candidate year or quarter contradicts",
        "candidate start time contradicts target call",
        "candidate date contradicts",
        "target date mismatch",
        "event date mismatch",
    )
    # A future date in a browser error may belong to the next quarter or an
    # unrelated event. It is not evidence that the stored schedule is wrong.
    if any(marker in value for marker in explicit_mismatch_markers):
        return {
            "reason": "schedule_mismatch",
            "retry_delay_minutes": _env_int(
                "DATE_STREAM_NEAR_LIVE_RETRY_MINUTES", 1
            ) if near_live else _env_int("DATE_STREAM_SCHEDULE_MISMATCH_RETRY_MINUTES", 60),
            "requires_schedule_refresh": True,
        }

    failure_reason = classify_stream_failure(error)
    if failure_reason == 'resource_capacity':
        return {'reason': 'resource_capacity', 'retry_delay_minutes': 1 if near_live else 5,
                'requires_schedule_refresh': False}
    if failure_reason == 'replay_source':
        return {'reason': 'replay_source', 'retry_delay_minutes': 1 if near_live else 30,
                'requires_schedule_refresh': True}
    if failure_reason == "auth_required":
        near_live = str(watch_state or "").lower() in {
            "near_live",
            "event_window",
            "date_only",
        }
        return {
            "reason": "auth_required",
            # The manager separately cools the protected URL itself. Keep the
            # call eligible near its event so newly discovered official URLs
            # can be tried without waiting for the blocked route's 12-hour TTL.
            "retry_delay_minutes": _env_int(
                "DATE_STREAM_AUTH_NEAR_LIVE_RETRY_MINUTES", 1
            ) if near_live else _env_int("DATE_STREAM_AUTH_RETRY_MINUTES", 720),
            "requires_schedule_refresh": True,
        }

    if failure_reason == "access_blocked":
        return {
            "reason": "access_blocked",
            "retry_delay_minutes": _env_int(
                "DATE_STREAM_BLOCKED_NEAR_LIVE_RETRY_MINUTES", 1
            ) if near_live else _env_int("DATE_STREAM_BLOCKED_RETRY_MINUTES", 360),
            "requires_schedule_refresh": False,
        }

    # `_probe_window` names the verified start/end range `event_window`.
    # Keep the older `near_live` spelling for callers outside the scheduler.
    near_live = str(watch_state or "").lower() in {
        "near_live",
        "event_window",
        "date_only",
    }
    near_live_retry = _env_int("DATE_STREAM_NEAR_LIVE_RETRY_MINUTES", 1)
    date_only_retry = _env_int(
        "DATE_STREAM_DATE_ONLY_RETRY_MINUTES",
        near_live_retry,
    )
    watch_state_value = str(watch_state or "").lower()
    low_priority_retry = (
        _env_int("DATE_STREAM_FUTURE_DATE_INTERVAL_MINUTES", 60)
        if watch_state_value == "date_only_future"
        else _env_int("DATE_STREAM_STALE_DATE_INTERVAL_MINUTES", 180)
        if watch_state_value == "date_only_stale"
        else None
    )
    if low_priority_retry is not None:
        retry_delay = low_priority_retry
    elif watch_state_value == "date_only":
        retry_delay = date_only_retry
    elif near_live:
        retry_delay = near_live_retry
    else:
        retry_delay = _env_int("DATE_STREAM_NO_CANDIDATE_RETRY_MINUTES", 15)
    if failure_reason in {"candidate_unavailable", "capacity_wait", "form_automation_failed", "playback_failed", "audio_failed"}:
        return {
            "reason": failure_reason,
            "retry_delay_minutes": retry_delay,
            "requires_schedule_refresh": False,
        }

    if low_priority_retry is None and not near_live and watch_state_value != "date_only":
        retry_delay = _env_int("DATE_STREAM_TRANSIENT_RETRY_MINUTES", 5)
    return {
        "reason": "transient_error",
        "retry_delay_minutes": retry_delay,
        "requires_schedule_refresh": False,
    }


def _nonnegative_env_int(name: str, default: int) -> int:
    """Read an optional retry cap where zero deliberately means unlimited."""
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return max(0, default)


def capture_retry_policy(error: str | None, *, attempts: int) -> Dict[str, Any]:
    """Classify capture retries without repeatedly resubmitting a blocked form.

    A transient browser/audio exit remains retryable through the event window,
    but each retry backs off exponentially. Explicit access and registration
    barriers are stopped after a bounded number of attempts because replaying
    the same form cannot make an email-link, CAPTCHA, or provider block pass.
    """
    value = re.sub(r"[_-]+", " ", str(error or "").lower())
    attempt_count = max(1, int(attempts or 1))
    failure_reason = classify_stream_failure(error)
    if failure_reason == 'resource_capacity':
        return {'reason': 'resource_capacity', 'retry_delay_minutes': 1, 'max_attempts': 0}
    if failure_reason == 'replay_source':
        return {'reason': 'replay_source', 'retry_delay_minutes': 30, 'max_attempts': 0}
    if failure_reason == "auth_required":
        return {
            "reason": "auth_required",
            "retry_delay_minutes": _env_int("DATE_STREAM_CAPTURE_AUTH_RETRY_MINUTES", 720),
            "max_attempts": _nonnegative_env_int(
                "DATE_STREAM_CAPTURE_AUTH_MAX_ATTEMPTS", 1
            ),
        }

    if failure_reason == "access_blocked":
        return {
            "reason": "access_blocked",
            "retry_delay_minutes": _env_int("DATE_STREAM_CAPTURE_BLOCKED_RETRY_MINUTES", 360),
            "max_attempts": _nonnegative_env_int(
                "DATE_STREAM_CAPTURE_BLOCKED_MAX_ATTEMPTS", 1
            ),
        }

    if "live capture incomplete" in value or failure_reason == "live_capture_incomplete":
        if 'live speech idle timeout' in value:
            # After speech was heard, repeated ten-minute speech loss may be
            # an unrecognized event ending. Keep a reconnect opportunity, but
            # never replay that event indefinitely. This is failure/manual
            # review, not evidence of successful completion.
            return {
                'reason': 'speech_idle_retry_limit',
                'retry_delay_minutes': _env_int('DATE_STREAM_CAPTURE_CONTINUATION_RETRY_MINUTES', 1),
                'max_attempts': _env_int('DATE_STREAM_IDLE_CAPTURE_MAX_ATTEMPTS', 3),
            }
        # A live source loss or a safety ceiling is not the end of the event.
        # Reconnect promptly while the ordinary date/time watch window allows
        # it. Do not grow this delay to an hour over repeated disconnections.
        return {
            "reason": "live_capture_incomplete",
            "retry_delay_minutes": _env_int("DATE_STREAM_CAPTURE_CONTINUATION_RETRY_MINUTES", 1),
            "max_attempts": _nonnegative_env_int("DATE_STREAM_CAPTURE_MAX_ATTEMPTS", 0),
        }

    if failure_reason == "form_automation_failed":
        return {
            "reason": "form_automation_failed",
            "retry_delay_minutes": _env_int("DATE_STREAM_CAPTURE_FORM_RETRY_MINUTES", 1),
            "max_attempts": _nonnegative_env_int("DATE_STREAM_CAPTURE_FORM_MAX_ATTEMPTS", 3),
        }

    base_delay = _env_int("DATE_STREAM_CAPTURE_RETRY_MINUTES", 3)
    multiplier = _env_int("DATE_STREAM_CAPTURE_RETRY_BACKOFF_MULTIPLIER", 2)
    maximum_delay = max(
        base_delay,
        _env_int("DATE_STREAM_CAPTURE_MAX_RETRY_MINUTES", 60),
    )
    retry_delay = min(
        maximum_delay,
        base_delay * (multiplier ** min(attempt_count - 1, 12)),
    )
    return {
        "reason": (failure_reason if failure_reason in {"candidate_unavailable", "capacity_wait"}
                   else "transient_capture_error"),
        "retry_delay_minutes": retry_delay,
        "max_attempts": _nonnegative_env_int(
            "DATE_STREAM_CAPTURE_MAX_ATTEMPTS", 0
        ),
    }
