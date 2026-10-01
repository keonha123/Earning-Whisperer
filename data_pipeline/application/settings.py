"""Watch-window and environment policy with no I/O."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


_CAPTURE_ENVIRONMENT_PREFIXES = (
    "DATE_STREAM_",
    "Q4_",
    "STT_",
    "TRANSCRIPT_",
    "WEBCAST_",
)

_CAPTURE_ENVIRONMENT_KEYS = {
    "AI_ENGINE_URL",
    "BACKEND_INTERNAL_SECRET",
    "BACKEND_URL",
    "DB_URL",
    "FFMPEG_BIN",
    "INTERNAL_SECRET",
    "OPENAI_API_KEY",
    "SEND_TO_AI_ENGINE",
    "SEND_TO_BACKEND",
}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def capture_runtime_environment(
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Copy all browser/STT settings needed by an isolated capture process."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in _CAPTURE_ENVIRONMENT_KEYS
        or key.startswith(_CAPTURE_ENVIRONMENT_PREFIXES)
    }
    environment.update(overrides or {})
    return environment


def maintenance_window_active() -> bool:
    start_text = os.getenv("DATE_STREAM_MAINTENANCE_START", "").strip()
    end_text = os.getenv("DATE_STREAM_MAINTENANCE_END", "").strip()
    if not start_text or not end_text:
        return False
    try:
        start = datetime.strptime(start_text, "%H:%M").time()
        end = datetime.strptime(end_text, "%H:%M").time()
    except ValueError:
        return False
    current = datetime.now().time()
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def probe_window(call: dict[str, Any], base_cooldown_minutes: int) -> tuple[str, int]:
    """Return a watch state and cooldown, tightening probes around verified times."""
    from ..storage.policies import capture_retry_window
    if capture_retry_window(call, now=datetime.now(timezone.utc))['expired']:
        return 'capture_retry_window_expired', max(1, base_cooldown_minutes)
    scheduled = None if call.get("schedule_time_stale") else call.get("scheduled_at_utc")
    if not scheduled:
        raw_date = call.get("webcast_date") or call.get("earning_at")
        event_date: date | None = None
        if isinstance(raw_date, datetime):
            event_date = raw_date.date()
        elif isinstance(raw_date, date):
            event_date = raw_date
        elif raw_date:
            try:
                event_date = date.fromisoformat(str(raw_date).strip()[:10])
            except ValueError:
                event_date = None
        watch_timezone = ZoneInfo(
            os.getenv("DATE_STREAM_WATCH_TIMEZONE", "America/New_York")
        )
        today = datetime.now(watch_timezone).date()
        if event_date is not None and event_date > today:
            return "date_only_future", max(
                1,
                int(os.getenv("DATE_STREAM_FUTURE_DATE_INTERVAL_MINUTES", "60")),
            )
        if event_date is not None and event_date < today:
            return "date_only_stale", max(
                1,
                int(os.getenv("DATE_STREAM_STALE_DATE_INTERVAL_MINUTES", "180")),
            )
        return "date_only", max(1, base_cooldown_minutes)
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    before_minutes = max(0, int(os.getenv("DATE_STREAM_NEAR_START_MINUTES", "20")))
    after_minutes = max(0, int(os.getenv("DATE_STREAM_NEAR_END_MINUTES", "180")))
    start = scheduled - timedelta(minutes=before_minutes)
    end = scheduled + timedelta(minutes=after_minutes)
    if now < start:
        return "scheduled", max(1, base_cooldown_minutes)
    if now <= end:
        return "event_window", max(1, int(os.getenv("DATE_STREAM_NEAR_INTERVAL_MINUTES", "1")))
    return "post_event", max(1, base_cooldown_minutes)
