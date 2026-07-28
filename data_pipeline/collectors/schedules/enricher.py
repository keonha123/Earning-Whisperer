"""Verify exact earnings-call times against issuer-owned IR pages."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from dotenv import dotenv_values
from lxml import html

try:
    from ... import database
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import database


DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DATA_PIPELINE_ROOT.parent
MONTH_PATTERN = (
    "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    "Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
TIMEZONE_PATTERN = (
    "ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|"
    "Eastern(?: Daylight| Standard)? Time|Central(?: Daylight| Standard)? Time|"
    "Mountain(?: Daylight| Standard)? Time|Pacific(?: Daylight| Standard)? Time"
)
DATE_TIME_PATTERN = re.compile(
    rf"(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}})"
    rf"(?:,?\s*(?P<year>20\d{{2}}))?"
    rf"[^.\n]{{0,180}}?"
    rf"(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})\s*"
    rf"(?P<meridiem>a\.?m\.?|p\.?m\.?)\s*"
    rf"(?P<timezone>{TIMEZONE_PATTERN})\b",
    re.IGNORECASE,
)
TIME_DATE_PATTERN = re.compile(
    rf"(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})\s*"
    rf"(?P<meridiem>a\.?m\.?|p\.?m\.?)\s*"
    rf"(?P<timezone>{TIMEZONE_PATTERN})\b"
    rf"[^.\n]{{0,180}}?"
    rf"(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}})"
    rf"(?:,?\s*(?P<year>20\d{{2}}))?",
    re.IGNORECASE,
)
TIMEZONE_ALIASES = {
    "ET": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CT": "America/Chicago",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MT": "America/Denver",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "EASTERN TIME": "America/New_York",
    "EASTERN DAYLIGHT TIME": "America/New_York",
    "EASTERN STANDARD TIME": "America/New_York",
    "CENTRAL TIME": "America/Chicago",
    "CENTRAL DAYLIGHT TIME": "America/Chicago",
    "CENTRAL STANDARD TIME": "America/Chicago",
    "MOUNTAIN TIME": "America/Denver",
    "MOUNTAIN DAYLIGHT TIME": "America/Denver",
    "MOUNTAIN STANDARD TIME": "America/Denver",
    "PACIFIC TIME": "America/Los_Angeles",
    "PACIFIC DAYLIGHT TIME": "America/Los_Angeles",
    "PACIFIC STANDARD TIME": "America/Los_Angeles",
}
TRUSTED_WIRE_HOSTS = (
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
)


def _load_env() -> None:
    values = {
        **dotenv_values(REPO_ROOT / ".env"),
        **dotenv_values(DATA_PIPELINE_ROOT / ".env"),
    }
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)


_load_env()


@dataclass(frozen=True)
class VerifiedScheduleTime:
    scheduled_at_utc: datetime
    source_timezone: str
    event_url: str
    webcast_url: str | None
    schedule_source: str
    schedule_evidence: str

    def as_database_values(self) -> dict[str, Any]:
        return {
            "scheduled_at_utc": self.scheduled_at_utc.replace(tzinfo=None),
            "source_timezone": self.source_timezone,
            "event_url": self.event_url,
            "webcast_url": self.webcast_url,
            "schedule_source": self.schedule_source,
            "schedule_evidence": self.schedule_evidence,
        }


@dataclass(frozen=True)
class SearchResult:
    link: str
    title: str
    snippet: str


class OfficialScheduleEnricher:
    """Search and validate event details only on the issuer's IR host."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("SERPER_API_KEY", "")
        self.search_url = "https://google.serper.dev/search"

    def verify_call(self, call: dict[str, Any]) -> VerifiedScheduleTime | None:
        expected_date = call["earning_at"].date()
        results = self._search_event_results(call, expected_date)
        official_result = self._select_official_result(call, results)
        if not official_result:
            return None

        # A date-matched preview is a cheap guard against opening generic IR homepages
        # for calls whose issuer has not yet announced a webcast time.
        indexed_preview = self._parse_verified_time(
            f"{official_result.title} {official_result.snippet}",
            expected_date,
            official_result.link,
            None,
            "official_ir_search_index",
        )
        if not indexed_preview:
            return None

        verified = self._verify_event_page(
            official_result.link,
            expected_date,
            "official_ir_event",
        )
        if not verified:
            verified = self._verify_indexed_official_time_with_wire(
                call,
                expected_date,
                official_result,
                results,
            )
        if not verified:
            return None

        database.update_verified_schedule_time(call["id"], verified.as_database_values())
        return verified

    def _search_event_results(self, call: dict[str, Any], expected_date: date) -> list[SearchResult]:
        if not self.api_key:
            return []
        hostname = (urlparse(str(call.get("ir_url", ""))).hostname or "").removeprefix("www.")
        date_text = expected_date.strftime("%B %-d %Y")
        queries = [
            f'"{call["company_name"]}" ({call["ticker"]}) earnings webcast {date_text}',
        ]
        if hostname:
            queries.append(f'site:{hostname} earnings conference call {date_text}')

        found: dict[str, SearchResult] = {}
        for query in queries:
            try:
                response = requests.post(
                    self.search_url,
                    headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                    data=json.dumps({"q": query}),
                    timeout=20,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                print(f"[{call['ticker']}] official event search failed: {exc}")
                continue

            for result in response.json().get("organic", []):
                link = str(result.get("link", ""))
                if link and link not in found:
                    found[link] = SearchResult(
                        link=link,
                        title=str(result.get("title", "")),
                        snippet=str(result.get("snippet", "")),
                    )
        return list(found.values())

    def _select_official_result(
        self,
        call: dict[str, Any],
        results: list[SearchResult],
    ) -> SearchResult | None:
        fallback = None
        for result in results:
            if self._is_official_result(call, result):
                if self._parse_verified_time(
                    f"{result.title} {result.snippet}",
                    call["earning_at"].date(),
                    result.link,
                    None,
                    "official_ir_search_index",
                ):
                    return result
                fallback = fallback or result
        return fallback

    def _is_official_result(self, call: dict[str, Any], result: SearchResult) -> bool:
        hostname = urlparse(str(call.get("ir_url", ""))).hostname or ""
        hostname = hostname.lower().removeprefix("www.")
        candidate_host = (urlparse(result.link).hostname or "").lower().removeprefix("www.")
        return bool(hostname) and (
            candidate_host == hostname or candidate_host.endswith(f".{hostname}")
        )

    def _verify_event_page(
        self,
        event_url: str,
        expected_date: date,
        source_prefix: str,
    ) -> VerifiedScheduleTime | None:
        page_text, webcast_url = self._fetch_event_page(event_url)
        verified = self._parse_verified_time(
            page_text,
            expected_date,
            event_url,
            webcast_url,
            f"{source_prefix}_http",
        )
        if verified:
            return verified

        browser_text, browser_webcast_url = self._fetch_event_page_with_browser(event_url)
        return self._parse_verified_time(
            browser_text,
            expected_date,
            event_url,
            browser_webcast_url,
            f"{source_prefix}_browser",
        )

    def _verify_indexed_official_time_with_wire(
        self,
        call: dict[str, Any],
        expected_date: date,
        official_result: SearchResult,
        results: list[SearchResult],
    ) -> VerifiedScheduleTime | None:
        official_time = self._parse_verified_time(
            f"{official_result.title} {official_result.snippet}",
            expected_date,
            official_result.link,
            None,
            "official_ir_search_index",
        )
        if not official_time:
            return None

        for result in results:
            if result.link == official_result.link or not self._is_official_result(call, result):
                continue
            second_official_time = self._parse_verified_time(
                f"{result.title} {result.snippet}",
                expected_date,
                result.link,
                None,
                "official_ir_search_index",
            )
            if not second_official_time or second_official_time.scheduled_at_utc != official_time.scheduled_at_utc:
                continue
            return VerifiedScheduleTime(
                scheduled_at_utc=official_time.scheduled_at_utc,
                source_timezone=official_time.source_timezone,
                event_url=official_result.link,
                webcast_url=None,
                schedule_source="official_ir_index_crosscheck",
                schedule_evidence=(
                    f"Official IR event: {official_time.schedule_evidence} | "
                    f"Official IR calendar: {second_official_time.schedule_evidence}"
                ),
            )

        for result in results:
            if not self._is_trusted_wire_result(call, result):
                continue
            wire_time = self._verify_event_page(
                result.link,
                expected_date,
                "trusted_wire",
            )
            if not wire_time or wire_time.scheduled_at_utc != official_time.scheduled_at_utc:
                continue
            return VerifiedScheduleTime(
                scheduled_at_utc=official_time.scheduled_at_utc,
                source_timezone=official_time.source_timezone,
                event_url=official_result.link,
                webcast_url=wire_time.webcast_url,
                schedule_source="official_ir_index_and_trusted_wire",
                schedule_evidence=(
                    f"Official IR index: {official_time.schedule_evidence} | "
                    f"Trusted wire: {wire_time.schedule_evidence}"
                ),
            )
        return None

    def _is_trusted_wire_result(self, call: dict[str, Any], result: SearchResult) -> bool:
        hostname = (urlparse(result.link).hostname or "").lower().removeprefix("www.")
        if not any(hostname == wire_host or hostname.endswith(f".{wire_host}") for wire_host in TRUSTED_WIRE_HOSTS):
            return False

        normalized_text = re.sub(r"[^a-z0-9]", "", f"{result.title} {result.snippet}".lower())
        company_terms = [
            re.sub(r"[^a-z0-9]", "", term.lower())
            for term in str(call["company_name"]).split()
            if len(term) >= 4
        ]
        ticker = str(call["ticker"]).lower()
        return ticker in normalized_text or any(term in normalized_text for term in company_terms)

    def _fetch_event_page(self, event_url: str) -> tuple[str, str | None]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        try:
            response = requests.get(event_url, timeout=(10, 15), headers=headers)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"official event page HTTP fetch unavailable: {exc}")
            return "", None

        return self._extract_page_details(response.content, event_url)

    def _fetch_event_page_with_browser(self, event_url: str) -> tuple[str, str | None]:
        """Read dynamically rendered IR pages inside the Playwright Docker image."""
        try:
            return asyncio.run(self._fetch_event_page_with_browser_async(event_url))
        except Exception as exc:
            print(f"official event browser fetch unavailable: {exc}")
            return "", None

    async def _fetch_event_page_with_browser_async(self, event_url: str) -> tuple[str, str | None]:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 1000},
                    locale="en-US",
                )
                page = await context.new_page()
                await page.goto(event_url, wait_until="domcontentloaded", timeout=45_000)
                await asyncio.sleep(2)
                return self._extract_page_details(await page.content(), event_url)
            finally:
                await browser.close()

    def _extract_page_details(
        self,
        page_content: str | bytes,
        event_url: str,
    ) -> tuple[str, str | None]:
        document = html.fromstring(page_content)
        text_content = " ".join(document.xpath("//text()[normalize-space()]"))
        webcast_url = None
        for anchor in document.xpath("//a[@href]"):
            label = " ".join(anchor.xpath(".//text()[normalize-space()]"))
            if re.search(r"webcast|listen|audio", label, re.IGNORECASE):
                webcast_url = urljoin(event_url, anchor.attrib["href"])
                break
        return re.sub(r"\s+", " ", text_content), webcast_url

    def _parse_verified_time(
        self,
        page_text: str,
        expected_date: date,
        event_url: str,
        webcast_url: str | None,
        schedule_source: str,
    ) -> VerifiedScheduleTime | None:
        matches = [
            *DATE_TIME_PATTERN.finditer(page_text),
            *TIME_DATE_PATTERN.finditer(page_text),
        ]
        for match in matches:
            year = int(match.group("year") or expected_date.year)
            month = MONTH_NUMBERS[match.group("month")[:3].lower()]
            parsed_date = date(year, month, int(match.group("day")))
            if parsed_date != expected_date:
                continue

            hour = int(match.group("hour"))
            minute = int(match.group("minute"))
            if match.group("meridiem").lower().startswith("p") and hour != 12:
                hour += 12
            if match.group("meridiem").lower().startswith("a") and hour == 12:
                hour = 0

            timezone_label = re.sub(r"\s+", " ", match.group("timezone").upper()).strip()
            source_timezone = TIMEZONE_ALIASES[timezone_label]
            local_time = datetime(
                expected_date.year,
                month,
                expected_date.day,
                hour,
                minute,
                tzinfo=ZoneInfo(source_timezone),
            )
            evidence = match.group(0).strip()
            return VerifiedScheduleTime(
                scheduled_at_utc=local_time.astimezone(ZoneInfo("UTC")),
                source_timezone=source_timezone,
                event_url=event_url,
                webcast_url=webcast_url,
                schedule_source=schedule_source,
                schedule_evidence=evidence,
            )
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify earnings call times from official IR pages.")
    parser.add_argument("--ticker", help="Verify one upcoming ticker.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum future calls to verify.")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent verification workers; keep this low to respect issuer sites.",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=None,
        help="Only verify calls scheduled within the next N calendar days.",
    )
    args = parser.parse_args(argv)

    calls = database.get_calls_missing_verified_time(
        limit=args.limit,
        days_ahead=args.days_ahead,
    )
    if args.ticker:
        calls = [call for call in calls if call["ticker"].upper() == args.ticker.upper()]
    if not calls:
        print("No unverified future calls found.")
        return 0

    enricher = OfficialScheduleEnricher()
    def verify_one(call: dict[str, Any]) -> tuple[str, VerifiedScheduleTime | None]:
        print(f"[{call['ticker']}] verifying official event time...", flush=True)
        verified = enricher.verify_call(call)
        return str(call["ticker"]), verified

    verified_count = 0
    workers = max(1, min(args.workers, 5))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(verify_one, call) for call in calls]
        for future in as_completed(futures):
            ticker, verified = future.result()
            if verified:
                verified_count += 1
                print(
                    f"[{ticker}] verified {verified.scheduled_at_utc.isoformat()} "
                    f"from {verified.event_url}",
                    flush=True,
                )
            else:
                print(f"[{ticker}] no date-matched official time found", flush=True)

    print(f"Verified {verified_count}/{len(calls)} official schedule times.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
