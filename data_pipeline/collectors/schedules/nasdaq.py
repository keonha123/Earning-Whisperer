"""Bounded near-term earnings dates from Nasdaq's public calendar."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import requests


NASDAQ_EARNINGS_CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings"
NASDAQ_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def normalize_ticker(value: object) -> str:
    """Normalize the two common share-class spellings before comparing sources."""
    return str(value or "").strip().upper().replace(".", "-")


def _parse_calendar_date(value: object, fallback: date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return fallback


@dataclass
class NasdaqCalendarResult:
    """A partial result is useful: failed calendar days must not imply no event."""

    schedules: list[dict[str, Any]] = field(default_factory=list)
    fetched_dates: set[date] = field(default_factory=set)
    failed_dates: dict[date, str] = field(default_factory=dict)


class NasdaqEarningsCalendar:
    """Fetch a small date window rather than making a request per ticker."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 15,
        base_url: str = NASDAQ_EARNINGS_CALENDAR_URL,
    ) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.base_url = base_url

    def collect(
        self,
        *,
        start_date: date,
        days_ahead: int,
        tickers: Iterable[str],
    ) -> NasdaqCalendarResult:
        known_tickers = {normalize_ticker(ticker) for ticker in tickers if ticker}
        result = NasdaqCalendarResult()
        seen: set[tuple[str, date]] = set()

        for offset in range(max(1, int(days_ahead))):
            calendar_date = start_date + timedelta(days=offset)
            try:
                response = requests.get(
                    self.base_url,
                    params={"date": calendar_date.isoformat()},
                    headers=NASDAQ_HEADERS,
                    timeout=(5, self.timeout_seconds),
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                result.failed_dates[calendar_date] = str(exc)[:500]
                continue

            result.fetched_dates.add(calendar_date)
            rows = (payload.get("data") or {}).get("rows") or []
            for row in rows:
                ticker = normalize_ticker(row.get("symbol") or row.get("ticker"))
                if not ticker or ticker not in known_tickers:
                    continue
                earning_date = _parse_calendar_date(row.get("date"), calendar_date)
                key = (ticker, earning_date)
                if key in seen:
                    continue
                seen.add(key)
                result.schedules.append(
                    {
                        "ticker": ticker,
                        "earning_date": earning_date,
                        "event_type": "earnings_call",
                        "schedule_source": "nasdaq_calendar",
                        "schedule_evidence": {
                            "symbol": str(row.get("symbol") or ""),
                            "calendar_date": calendar_date.isoformat(),
                            "time": str(row.get("time") or ""),
                            "name": str(row.get("name") or ""),
                        },
                    }
                )
        return result
