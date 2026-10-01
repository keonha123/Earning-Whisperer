"""Discover historical webcast pages by crawling issuer-owned IR pages."""

from __future__ import annotations

import argparse
import os
import re
from collections import deque
from dataclasses import dataclass
from html import unescape
from typing import Any, Iterable
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests
from lxml import etree, html

try:
    from ... import database
    from .replay_discovery import (
        TRUSTED_WEBCAST_HOST_SUFFIXES,
        host_for_url,
        host_matches,
    )
except ImportError:  # Allows direct script execution from data_pipeline.
    from data_pipeline import database
    from data_pipeline.tools.replay.replay_discovery import (
        TRUSTED_WEBCAST_HOST_SUFFIXES,
        host_for_url,
        host_matches,
    )


ARCHIVE_TERMS = {
    "events": 45,
    "event": 35,
    "presentations": 40,
    "presentation": 30,
    "webcasts": 70,
    "webcast": 70,
    "archives": 55,
    "archive": 45,
    "earnings": 55,
    "quarterly": 30,
    "conference call": 75,
    "replay": 90,
    "listen": 75,
    "audio": 65,
    "watch": 45,
    "play": 35,
}
NEGATIVE_TERMS = (
    "careers",
    "job search",
    "privacy",
    "terms of use",
    "cookie",
    "transcript",
    "download",
    "pdf",
)
NON_HTML_SUFFIXES = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpg|jpeg|png|gif|svg|css|js)(?:$|[?#])",
    re.IGNORECASE,
)
SITEMAP_LOCATIONS = ("/sitemap.xml", "/sitemap_index.xml")
YEAR_PATTERN = re.compile(r"\b20\d{2}\b")
TRUSTED_PROVIDER_PATTERN = re.compile(
    r"(?:webcast|replay|listen|audio|conference|earnings|event)",
    re.IGNORECASE,
)
INLINE_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def normalize_url(url: str, *, base_url: str | None = None) -> str | None:
    value = urljoin(base_url or "", str(url or "").strip())
    value, _ = urldefrag(value)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if NON_HTML_SUFFIXES.search(parsed.path):
        return None
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )


def is_trusted_provider(host: str) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in TRUSTED_WEBCAST_HOST_SUFFIXES)


def score_internal_link(
    url: str,
    *,
    label: str = "",
    context: str = "",
    ir_host: str,
    ticker: str,
    call_year: int | None,
) -> int:
    """Score an IR link without treating generic navigation as a candidate."""
    host = host_for_url(url)
    if not host_matches(host, ir_host) and not is_trusted_provider(host):
        return -1
    searchable = f"{url} {label} {context}".lower()
    if any(term in searchable for term in NEGATIVE_TERMS):
        return -1
    path = urlparse(url).path.rstrip("/").lower()
    if path == "/search" or path in {"/investor", "/investors", "/ir"}:
        return -1
    if not TRUSTED_PROVIDER_PATTERN.search(searchable):
        return 0

    score = 0
    for term, points in ARCHIVE_TERMS.items():
        if term in searchable:
            score += points
    if ticker.lower() in searchable:
        score += 15
    if call_year and str(call_year) in searchable:
        score += 30
    if is_trusted_provider(host) and not host_matches(host, ir_host):
        score += 45
    if re.search(r"(?:q[1-4]|[1-4]q|quarter)", searchable, re.IGNORECASE):
        score += 20
    return score


@dataclass(frozen=True)
class CrawlCandidate:
    target_url: str
    score: int
    parent_url: str
    depth: int
    title: str
    snippet: str
    provider_domain: str

    def as_database_candidate(self) -> dict[str, Any]:
        return {
            "target_url": self.target_url,
            "source_kind": "internal_crawl",
            "source_title": self.title[:500],
            "source_snippet": (
                f"depth={self.depth} parent={self.parent_url} {self.snippet}"
            )[:4000],
            "provider_domain": self.provider_domain,
            "score": self.score,
        }


class InternalIRDiscovery:
    def __init__(
        self,
        *,
        max_depth: int = 2,
        max_pages: int = 6,
        candidates_per_call: int = 5,
        timeout_seconds: float = 6,
    ) -> None:
        self.max_depth = max(1, max_depth)
        self.max_pages = max(1, max_pages)
        self.candidates_per_call = max(1, candidates_per_call)
        self.timeout_seconds = max(3.0, timeout_seconds)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Earning-Whisperer-IR-Crawler/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def _fetch(self, url: str) -> tuple[str, str] | None:
        try:
            response = self.session.get(
                url,
                timeout=(min(2.0, self.timeout_seconds / 2), self.timeout_seconds),
                allow_redirects=True,
            )
            if not response.ok or not response.content:
                return None
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                kind in content_type for kind in ("html", "xml", "text")
            ):
                return None
            return response.url, response.text
        except requests.RequestException:
            return None

    def _sitemap_urls(self, ir_url: str) -> list[str]:
        parsed = urlparse(ir_url)
        root = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        locations = list(SITEMAP_LOCATIONS)
        robots = self._fetch(urljoin(root, "/robots.txt"))
        if robots:
            _, text = robots
            locations.extend(
                line.split(":", 1)[1].strip()
                for line in text.splitlines()
                if line.lower().startswith("sitemap:") and ":" in line
            )

        urls: list[str] = []
        seen: set[str] = set()
        for location in locations:
            sitemap_url = normalize_url(location, base_url=root)
            if not sitemap_url or sitemap_url in seen:
                continue
            seen.add(sitemap_url)
            fetched = self._fetch(sitemap_url)
            if not fetched:
                continue
            _, body = fetched
            try:
                document = etree.fromstring(body.encode("utf-8", errors="ignore"))
                values = document.xpath(
                    "//*[local-name()='loc']/text()"
                )
            except (etree.XMLSyntaxError, ValueError):
                continue
            for value in values:
                candidate = normalize_url(str(value), base_url=sitemap_url)
                if candidate and host_matches(host_for_url(candidate), host_for_url(ir_url)):
                    urls.append(candidate)
        return urls[: self.max_pages * 12]

    def discover_provider_links_from_page(
        self,
        page_url: str,
        *,
        ir_url: str | None = None,
        ticker: str = "",
        call_year: int | None = None,
    ) -> list[CrawlCandidate]:
        """Extract trusted provider links from a known issuer event-detail page.

        This is intentionally a one-page static lookup. Some issuer event
        templates hang in Chromium but still expose their provider's replay
        URL in normal public HTML, which avoids treating a browser-navigation
        problem as a missing training surface.
        """
        normalized_page_url = normalize_url(page_url)
        normalized_ir_url = normalize_url(ir_url or page_url)
        if not normalized_page_url or not normalized_ir_url:
            return []
        fetched = self._fetch(normalized_page_url)
        if not fetched:
            return []

        final_url, body = fetched
        ir_host = host_for_url(normalized_ir_url)
        candidates: dict[str, CrawlCandidate] = {}
        for link_url, label, context in self._page_links(final_url, body):
            host = host_for_url(link_url)
            if host_matches(host, ir_host) or not is_trusted_provider(host):
                continue
            score = score_internal_link(
                link_url,
                label=label,
                context=context,
                ir_host=ir_host,
                ticker=ticker,
                call_year=call_year,
            )
            if score < 70 or link_url in candidates:
                continue
            candidates[link_url] = CrawlCandidate(
                target_url=link_url,
                score=score,
                parent_url=final_url,
                depth=1,
                title=label or link_url,
                snippet=context,
                provider_domain=host,
            )
        return sorted(
            candidates.values(),
            key=lambda candidate: (-candidate.score, candidate.target_url),
        )[: self.candidates_per_call]

    @staticmethod
    def _page_links(page_url: str, body: str) -> Iterable[tuple[str, str, str]]:
        try:
            document = html.fromstring(body, base_url=page_url)
        except (etree.ParserError, ValueError):
            return []
        links: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add_element_url(element: Any, raw_url: str, label: str, context: str) -> None:
            normalized = normalize_url(raw_url, base_url=page_url)
            if normalized:
                key = (normalized, label[:500])
                if key not in seen:
                    seen.add(key)
                    links.append((normalized, label[:500], context[:1000]))

        def element_context(element: Any) -> tuple[str, str]:
            label = " ".join(element.itertext()).strip()
            parent = element.getparent()
            context = (
                " ".join(parent.itertext()).strip() if parent is not None else label
            )
            return label, context

        for anchor in document.xpath("//a[@href]"):
            label, context = element_context(anchor)
            raw_href = str(anchor.get("href") or "")
            inline_urls = INLINE_URL_PATTERN.findall(raw_href)
            if inline_urls:
                for inline_url in inline_urls:
                    add_element_url(anchor, inline_url, label, context)
            else:
                add_element_url(anchor, raw_href, label, context)

        # Modern IR pages frequently keep the provider URL on a disclosure
        # button, iframe, or card and let JavaScript open it. Requests cannot
        # execute that JavaScript, but the destination is still present in
        # these attributes and is valuable for downstream browser probing.
        for element in document.xpath(
            "//*[@data-webcast-url or @data-href or @data-url or "
            "@data-event-url or @data-iframe-src or @data-src or @src or @onclick]"
        ):
            label, context = element_context(element)
            raw_values = [
                element.get("data-webcast-url"),
                element.get("data-href"),
                element.get("data-url"),
                element.get("data-event-url"),
                element.get("data-iframe-src"),
                element.get("data-src"),
                element.get("src"),
                element.get("onclick"),
            ]
            for raw_value in raw_values:
                if not raw_value:
                    continue
                inline_urls = INLINE_URL_PATTERN.findall(str(raw_value))
                values = inline_urls or [str(raw_value)]
                for value in values:
                    add_element_url(element, value, label, context)

        # Some investor-relations templates render the webcast URL only in a
        # JSON blob or inline script. Keep a short context around each URL so
        # unrelated words elsewhere in a large bundle cannot poison scoring.
        for script in document.xpath("//script"):
            script_text = " ".join(script.itertext()).strip()
            if not script_text:
                continue
            decoded_script = unescape(script_text).replace("\\/", "/")
            for match in INLINE_URL_PATTERN.finditer(decoded_script):
                start = max(0, match.start() - 220)
                end = min(len(decoded_script), match.end() + 220)
                add_element_url(
                    script,
                    match.group(0),
                    "embedded webcast URL",
                    decoded_script[start:end],
                )
        return links

    def discover_call(self, call: dict[str, Any]) -> list[CrawlCandidate]:
        ir_url = normalize_url(str(call.get("ir_url") or ""))
        if not ir_url:
            return []
        ticker = str(call.get("ticker") or "").upper()
        call_year = call.get("call_year")
        try:
            call_year = int(call_year) if call_year else None
        except (TypeError, ValueError):
            call_year = None
        ir_host = host_for_url(ir_url)
        queue: deque[tuple[str, int]] = deque([(ir_url, 0)])
        visited: set[str] = set()
        candidates: dict[str, CrawlCandidate] = {}

        for sitemap_url in self._sitemap_urls(ir_url):
            score = score_internal_link(
                sitemap_url,
                ir_host=ir_host,
                ticker=ticker,
                call_year=call_year,
            )
            if score >= 70:
                candidates[sitemap_url] = CrawlCandidate(
                    target_url=sitemap_url,
                    score=score,
                    parent_url=ir_url,
                    depth=1,
                    title="IR sitemap webcast candidate",
                    snippet="Discovered from robots.txt or sitemap.xml.",
                    provider_domain=host_for_url(sitemap_url),
                )

        while queue and len(visited) < self.max_pages:
            page_url, depth = queue.popleft()
            if page_url in visited:
                continue
            visited.add(page_url)
            fetched = self._fetch(page_url)
            if not fetched:
                continue
            final_url, body = fetched
            for link_url, label, context in self._page_links(final_url, body):
                host = host_for_url(link_url)
                score = score_internal_link(
                    link_url,
                    label=label,
                    context=context,
                    ir_host=ir_host,
                    ticker=ticker,
                    call_year=call_year,
                )
                if score >= 70 and link_url not in candidates:
                    candidates[link_url] = CrawlCandidate(
                        target_url=link_url,
                        score=score,
                        parent_url=final_url,
                        depth=depth + 1,
                        title=label or link_url,
                        snippet=context,
                        provider_domain=host,
                    )
                if depth >= self.max_depth or not host_matches(host, ir_host):
                    continue
                if score >= 35 or depth == 0:
                    queue.append((link_url, depth + 1))

        return sorted(
            candidates.values(),
            key=lambda candidate: (-candidate.score, candidate.depth, candidate.target_url),
        )[: self.candidates_per_call]

    def discover(
        self,
        *,
        limit: int | None = None,
        tickers: set[str] | None = None,
        discovery_statuses: set[str] | None = None,
        force: bool = False,
    ) -> tuple[int, int]:
        calls = database.get_historical_replay_calls()
        if discovery_statuses:
            selected = database.get_historical_replay_discovery_tickers(discovery_statuses)
            calls = [call for call in calls if str(call["ticker"]).upper() in selected]
        if tickers:
            calls = [call for call in calls if str(call["ticker"]).upper() in tickers]

        searched = 0
        found = 0
        for call in calls:
            if limit is not None and searched >= max(1, limit):
                break
            if not database.claim_historical_replay_discovery(
                call,
                cooldown_minutes=0 if force else 10080,
                force=force,
            ):
                continue
            searched += 1
            ticker = str(call["ticker"]).upper()
            try:
                candidates = self.discover_call(call)
                saved = database.save_historical_replay_targets(
                    call,
                    [candidate.as_database_candidate() for candidate in candidates],
                )
                database.record_historical_replay_discovery(
                    ticker,
                    status="discovered" if saved else "no_candidate",
                    candidate_count=saved,
                )
                found += saved
                print(f"[InternalIRDiscovery] {ticker} candidates={saved}", flush=True)
            except Exception as exc:
                database.record_historical_replay_discovery(
                    ticker,
                    status="error",
                    error=str(exc),
                )
                print(f"[InternalIRDiscovery] {ticker} failed: {str(exc)[:180]}", flush=True)
        print(
            f"[InternalIRDiscovery] searched={searched} saved_candidates={found}",
            flush=True,
        )
        return searched, found


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover earnings webcast URLs by crawling company IR pages."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--discovery-statuses", default="")
    parser.add_argument("--depth", type=int, default=int(os.getenv("IR_CRAWL_MAX_DEPTH", "2")))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("IR_CRAWL_MAX_PAGES", "6")))
    parser.add_argument("--candidates-per-call", type=int, default=5)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("IR_CRAWL_TIMEOUT_SECONDS", "6")),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    discovery = InternalIRDiscovery(
        max_depth=args.depth,
        max_pages=args.max_pages,
        candidates_per_call=args.candidates_per_call,
        timeout_seconds=args.timeout_seconds,
    )
    tickers = {ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()}
    statuses = {
        status.strip().lower()
        for status in args.discovery_statuses.split(",")
        if status.strip()
    }
    discovery.discover(
        limit=args.limit,
        tickers=tickers or None,
        discovery_statuses=statuses or None,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
