from __future__ import annotations

import argparse
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import dotenv_values

try:
    from ... import database
except ImportError:  # Allows direct script execution from data_pipeline.
    from data_pipeline import database


DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DATA_PIPELINE_ROOT.parent
SERPER_SEARCH_URL = "https://google.serper.dev/search"
TRUSTED_WEBCAST_HOST_SUFFIXES = (
    "on24.com",
    "q4inc.com",
    "media-server.com",
    "webcasts.com",
    "choruscall.com",
    "open-exchange.net",
    "notified.com",
    "irwebcast.com",
)
REPLAY_TERMS = ("webcast", "replay", "conference call", "listen", "audio")
DIRECT_REPLAY_TITLE_PATTERN = re.compile(r"\b(?:webcast|replay|conference call|listen|audio)\b", re.IGNORECASE)
EARNINGS_TERMS = ("earnings", "financial results", "quarter", "quarterly")
ARCHIVE_TITLE_TERMS = ("webcasts", "events", "presentations")
PRESS_RELEASE_TITLE_TERMS = (
    "announces",
    "reports",
    "earnings release",
    "release dates",
    "financial reports",
)
REJECTED_TERMS = ("transcript", "seeking alpha", "motley fool", "stocktwits", "pdf")


def _load_env() -> None:
    values = {
        **dotenv_values(REPO_ROOT / ".env"),
        **dotenv_values(DATA_PIPELINE_ROOT / ".env"),
    }
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)


_load_env()


def host_for_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def host_matches(host: str, parent: str) -> bool:
    return bool(host and parent and (host == parent or host.endswith(f".{parent}")))


def build_replay_query(call: dict[str, Any]) -> str:
    company_name = str(call.get("company_name") or call["ticker"])
    parts = [f'"{company_name}"', str(call["ticker"]).upper()]
    if isinstance(call.get("earning_at"), datetime):
        # The calendar-quarter label is not a reliable fiscal quarter, and an exact
        # month makes recently indexed replays needlessly hard to find.
        parts.append(str(call["earning_at"].year))
    elif call.get("call_year"):
        parts.append(str(call["call_year"]))
    parts.extend(("earnings", "webcast", "replay"))
    return " ".join(parts)


def build_provider_fallback_query(call: dict[str, Any]) -> str | None:
    ir_host = host_for_url(str(call.get("ir_url") or ""))
    if not ir_host:
        return None
    return f"{build_replay_query(call)} -site:{ir_host}"


def replay_search_candidate(
    result: dict[str, Any],
    *,
    ticker: str,
    ir_url: str | None,
    earning_at: datetime | None,
) -> dict[str, Any] | None:
    """Keep only company IR or established webcast-host results with earnings context."""
    target_url = str(result.get("link") or "").strip()
    host = host_for_url(target_url)
    if not target_url or not host or urlparse(target_url).scheme not in {"http", "https"}:
        return None

    title = str(result.get("title") or "").strip()
    snippet = str(result.get("snippet") or "").strip()
    display_text = f"{title} {snippet}".lower()
    searchable = f"{display_text} {target_url}".lower()
    if any(term in searchable for term in REJECTED_TERMS):
        return None
    title_text = title.lower()
    ir_host = host_for_url(str(ir_url or ""))
    official = host_matches(host, ir_host)
    vendor = any(host_matches(host, suffix) for suffix in TRUSTED_WEBCAST_HOST_SUFFIXES)
    direct_replay = bool(DIRECT_REPLAY_TITLE_PATTERN.search(title_text))
    archive_entrypoint = any(term in title_text for term in ARCHIVE_TITLE_TERMS)
    announcement_entrypoint = (
        official
        and any(term in title_text for term in PRESS_RELEASE_TITLE_TERMS)
        and "release dates" not in title_text
        and "earnings release date" not in title_text
        and "earnings releases" not in title_text
        and "financial & earnings reports" not in title_text
        and "earnings" in title_text
    )
    # Generic IR pages often inherit query words in their snippets. Keep only a
    # specific playback page or a dedicated webcast/event archive as an entrypoint.
    if not direct_replay and not archive_entrypoint and not announcement_entrypoint:
        return None
    if not any(term in display_text for term in EARNINGS_TERMS):
        return None
    if earning_at and str(earning_at.year) not in searchable:
        return None

    if not official and not vendor:
        return None

    score = 0
    score += 80 if official else 50
    score += 45 if direct_replay else 30 if announcement_entrypoint else 15
    score += 35 if "replay" in searchable else 0
    score += 30 if "webcast" in searchable else 0
    score += 25 if "earnings" in searchable else 0
    score += 10 if ticker.lower() in searchable else 0
    return {
        "target_url": target_url,
        "source_kind": (
            "serper_direct"
            if direct_replay
            else "serper_announcement"
            if announcement_entrypoint
            else "serper_archive"
        ),
        "source_title": title,
        "source_snippet": snippet,
        "provider_domain": host,
        "score": score,
    }


def select_replay_candidates(
    call: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    prefer_external_provider: bool,
) -> list[dict[str, Any]]:
    """Keep a provider URL when fallback search found one below higher-scored IR results."""
    selected = candidates[: max(1, limit)]
    if not prefer_external_provider:
        return selected

    ir_host = host_for_url(str(call.get("ir_url") or ""))
    provider_candidate = next(
        (
            candidate
            for candidate in candidates
            if not host_matches(host_for_url(str(candidate["target_url"])), ir_host)
        ),
        None,
    )
    if not provider_candidate:
        return selected
    return [
        provider_candidate,
        *(candidate for candidate in selected if candidate != provider_candidate),
    ][: max(1, limit)]


class HistoricalReplayDiscovery:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("SERPER_API_KEY") or "").strip()

    def _search(self, query: str, *, max_results: int) -> list[dict[str, Any]]:
        response = requests.post(
            SERPER_SEARCH_URL,
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max(1, min(max_results, 10))},
            timeout=20,
        )
        if not response.ok:
            raise RuntimeError(
                f"Serper search failed status={response.status_code} "
                f"body={response.text[:300]}"
            )
        return list(response.json().get("organic", []))

    def search_call(
        self,
        call: dict[str, Any],
        *,
        max_results: int = 10,
        provider_fallback: bool = False,
        provider_fallback_only: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("SERPER_API_KEY is required to discover historical replay URLs")

        results: list[dict[str, Any]] = []
        if not provider_fallback_only:
            results.extend(self._search(build_replay_query(call), max_results=max_results))
        if provider_fallback or provider_fallback_only:
            fallback_query = build_provider_fallback_query(call)
            if fallback_query:
                results.extend(self._search(fallback_query, max_results=max_results))

        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for result in results:
            candidate = replay_search_candidate(
                result,
                ticker=str(call["ticker"]),
                ir_url=call.get("ir_url"),
                earning_at=call.get("earning_at"),
            )
            if not candidate or candidate["target_url"] in seen_urls:
                continue
            seen_urls.add(candidate["target_url"])
            candidates.append(candidate)
        return sorted(candidates, key=lambda candidate: int(candidate["score"]), reverse=True)

    def discover(
        self,
        *,
        limit: int | None = None,
        max_results: int = 10,
        candidates_per_call: int = 3,
        provider_fallback: bool = False,
        provider_fallback_only: bool = False,
        tickers: set[str] | None = None,
        discovery_statuses: set[str] | None = None,
        cooldown_minutes: int = 10080,
        force: bool = False,
    ) -> tuple[int, int]:
        calls = database.get_historical_replay_calls()
        if discovery_statuses:
            status_tickers = database.get_historical_replay_discovery_tickers(
                discovery_statuses
            )
            calls = [
                call
                for call in calls
                if str(call["ticker"]).upper() in status_tickers
            ]
        if tickers:
            calls = [call for call in calls if str(call["ticker"]).upper() in tickers]
        found = 0
        searched = 0
        for call in calls:
            if limit is not None and searched >= max(1, limit):
                break
            if not database.claim_historical_replay_discovery(
                call,
                cooldown_minutes=0 if force else cooldown_minutes,
                force=force,
            ):
                continue
            searched += 1
            ticker = str(call["ticker"]).upper()
            try:
                candidates = self.search_call(
                    call,
                    max_results=max_results,
                    provider_fallback=provider_fallback,
                    provider_fallback_only=provider_fallback_only,
                )
                candidates = select_replay_candidates(
                    call,
                    candidates,
                    limit=candidates_per_call,
                    prefer_external_provider=provider_fallback or provider_fallback_only,
                )
            except Exception as exc:
                database.record_historical_replay_discovery(
                    ticker,
                    status="error",
                    error=str(exc),
                )
                print(f"[ReplayDiscovery] {ticker} search failed: {str(exc)[:180]}", flush=True)
                continue
            saved = database.save_historical_replay_targets(call, candidates)
            database.record_historical_replay_discovery(
                ticker,
                status="discovered" if saved else "no_candidate",
                candidate_count=saved,
            )
            found += saved
            print(
                f"[ReplayDiscovery] {ticker} candidates={saved} query={build_replay_query(call)}",
                flush=True,
            )
        print(f"[ReplayDiscovery] searched={searched} saved_candidates={found}", flush=True)
        print(
            f"[ReplayDiscovery] persisted summary: "
            f"{database.get_historical_replay_discovery_summary()}",
            flush=True,
        )
        return searched, found

    def seed_ir_entrypoints(
        self,
        *,
        limit: int | None = None,
        tickers: set[str] | None = None,
        discovery_statuses: set[str] | None = None,
    ) -> tuple[int, int]:
        """Use known company IR pages as browser-discovery entrypoints without Serper."""
        calls = database.get_historical_replay_calls()
        if discovery_statuses:
            status_tickers = database.get_historical_replay_discovery_tickers(
                discovery_statuses
            )
            calls = [
                call
                for call in calls
                if str(call["ticker"]).upper() in status_tickers
            ]
        if tickers:
            calls = [call for call in calls if str(call["ticker"]).upper() in tickers]
        if limit is not None:
            calls = calls[: max(1, limit)]

        seeded = 0
        for call in calls:
            ticker = str(call["ticker"]).upper()
            ir_url = str(call.get("ir_url") or "").strip()
            if not ir_url:
                print(f"[ReplayDiscovery] {ticker} missing IR entrypoint", flush=True)
                continue
            candidates = [
                {
                    "target_url": ir_url,
                    "source_kind": "ir_entrypoint",
                    "source_title": f"{ticker} investor relations entrypoint",
                    "source_snippet": "Known company IR page for browser replay discovery.",
                    "provider_domain": host_for_url(ir_url),
                }
            ]
            saved = database.save_historical_replay_targets(call, candidates)
            database.record_historical_replay_discovery(
                ticker,
                status="discovered" if saved else "no_candidate",
                candidate_count=saved,
            )
            seeded += saved
            print(f"[ReplayDiscovery] {ticker} IR entrypoints={saved}", flush=True)
        print(
            f"[ReplayDiscovery] IR entrypoints searched={len(calls)} seeded={seeded}",
            flush=True,
        )
        return len(calls), seeded


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find official historical earnings-webcast replay candidates.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--candidates-per-call", type=int, default=3)
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=int(os.getenv("WEBCAST_REPLAY_DISCOVERY_COOLDOWN_MINUTES", "10080")),
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--provider-fallback",
        action="store_true",
        help="Also search outside the company IR domain for trusted webcast-provider URLs.",
    )
    parser.add_argument(
        "--provider-fallback-only",
        action="store_true",
        help="Search only outside the company IR domain without repeating the primary query.",
    )
    parser.add_argument(
        "--discovery-statuses",
        default="",
        help="Comma-separated persisted discovery states to retry, such as no_candidate,error.",
    )
    parser.add_argument(
        "--seed-ir-entrypoints",
        action="store_true",
        help="Seed known company IR pages as browser-discovery targets without using Serper.",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated historical tickers to search instead of the full recent set.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        tickers = {ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()}
        discovery_statuses = {
            status.strip().lower()
            for status in args.discovery_statuses.split(",")
            if status.strip()
        }
        discovery = HistoricalReplayDiscovery()
        if args.seed_ir_entrypoints:
            discovery.seed_ir_entrypoints(
                limit=args.limit,
                tickers=tickers or None,
                discovery_statuses=discovery_statuses or None,
            )
        else:
            discovery.discover(
                limit=args.limit,
                max_results=args.max_results,
                candidates_per_call=args.candidates_per_call,
                provider_fallback=args.provider_fallback,
                provider_fallback_only=args.provider_fallback_only,
                tickers=tickers or None,
                discovery_statuses=discovery_statuses or None,
                cooldown_minutes=args.cooldown_minutes,
                force=args.force,
            )
    except RuntimeError as exc:
        print(f"[ReplayDiscovery] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
