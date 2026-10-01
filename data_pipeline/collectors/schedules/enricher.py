"""Verify exact earnings-call times against issuer-owned IR pages."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html as html_lib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from dotenv import dotenv_values
from lxml import etree, html

try:
    from ... import database
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import database


try:
    from .event_routes import (normalize_route, fiscal_period, period_mismatch, scoped_candidates,
                               visible_text, scope_text, event_scope, route_proof, PLAYBACK, EARNINGS,
                               is_event_navigation, issuer_listing_fallbacks)
    from .call_times import parse_call_times, schedule_time_text
    from .event_dates import non_event_date_reason
    from .route_retention import retained_route_fields, authenticated_route
    from .event_routes import stored_event_kind_conflict
except ImportError:
    from collectors.schedules.event_routes import (normalize_route, fiscal_period, period_mismatch, scoped_candidates,
                                                  visible_text, scope_text, event_scope, route_proof, PLAYBACK, EARNINGS,
                                                  is_event_navigation, issuer_listing_fallbacks)
    from collectors.schedules.call_times import parse_call_times, schedule_time_text
    from collectors.schedules.event_dates import non_event_date_reason
    from collectors.schedules.route_retention import retained_route_fields, authenticated_route
    from collectors.schedules.event_routes import stored_event_kind_conflict

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
DATE_ONLY_PATTERN = re.compile(
    rf"(?P<month>{MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})(?!\d)"
    rf"(?:,?\s*(?P<year>20\d{{2}}))?",
    re.IGNORECASE,
)
DAY_MONTH_DATE_PATTERN = re.compile(
    rf"(?<!\d)(?P<day>\d{{1,2}})\s+(?P<month>{MONTH_PATTERN})\.?,?\s+(?P<year>20\d{{2}})", re.I
)
EARNINGS_DATE_CONTEXT_PATTERN = re.compile(
    r"earnings?|financial results?|quarter|conference call|webcast|"
    r"investor (?:call|event)|results release",
    re.IGNORECASE,
)
CALL_TIME_CONTEXT_PATTERN = re.compile(
    r"\b(?:earnings\s+call|conference\s+call|results\s+call|teleconference|webcast)\b",
    re.IGNORECASE,
)
NON_CALL_TIME_CONTEXT_PATTERN = re.compile(
    r"\b(?:releas(?:e|ed|ing)|publish(?:ed|ing)?|posted|datePublished|dateModified|"
    r"endDate|expir(?:es|y|ation)|available\s+(?:until|through)|replay\s+(?:until|through))\b",
    re.IGNORECASE,
)
CALL_CLOCK_PATTERN = re.compile(
    rf"(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})\s*"
    rf"(?P<meridiem>a\.?m\.?|p\.?m\.?)\s*"
    rf"(?P<timezone>{TIMEZONE_PATTERN})\b",
    re.IGNORECASE,
)
ISO_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>20\d{2})-(?P<month>0?[1-9]|1[0-2])-(?P<day>0?[1-9]|[12]\d|3[01])(?!\d)"
)
ISO_DATETIME_PATTERN = re.compile(
    r"(?<!\d)(?P<value>20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?"
    r"(?:Z|[+-]\d{2}:?\d{2}))"
)
WEBCAST_ACTION_PATTERN = re.compile(
    r"webcast|listen|watch|audio|join|register|conference call|earnings call|"
    r"results call|live stream|presentation",
    re.IGNORECASE,
)
NON_EVENT_LINK_PATTERN = re.compile(
    r"privacy|terms|cookie|transcript|press release|news release|download|"
    r"\.pdf(?:$|[?#])|\.ics(?:$|[?#])|calendar",
    re.IGNORECASE,
)
URL_VALUE_PATTERN = re.compile(
    r"https?:\\?/\\?/[^\s\"'<>]+",
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
SERPER_CIRCUIT_SCOPE = "schedule_serper"
XML_UNSAFE_TEXT_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)
HTML_MARKUP_PATTERN = re.compile(
    r"<(?:!doctype\s+html|html|head|body|title|div|article|section|p|a|script)\b",
    re.IGNORECASE,
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
    webcast_date: date
    scheduled_at_utc: datetime
    source_timezone: str
    event_url: str
    webcast_url: str | None
    schedule_source: str
    schedule_evidence: str
    event_identity: dict[str, Any] | None = None
    schedule_discovery_fingerprint: str | None = None

    def as_database_values(self) -> dict[str, Any]:
        return {
            "webcast_date": self.webcast_date,
            "scheduled_at_utc": self.scheduled_at_utc.replace(tzinfo=None),
            "source_timezone": self.source_timezone,
            "event_url": self.event_url,
            "webcast_url": self.webcast_url,
            "schedule_source": self.schedule_source,
            "schedule_evidence": self.schedule_evidence,
            **({"event_identity": self.event_identity} if self.event_identity else {}),
            **({"schedule_discovery_fingerprint": self.schedule_discovery_fingerprint} if self.schedule_discovery_fingerprint else {}),
        }


@dataclass(frozen=True)
class SearchResult:
    link: str
    title: str
    snippet: str


@dataclass(frozen=True)
class EnrichmentFailure:
    """A safe, durable category for retry decisions without logging provider bodies."""

    kind: str
    message: str
    retry_minutes: int


@dataclass(frozen=True)
class OfficialEventDiscovery:
    """A date-matched route found inside an issuer-owned IR document."""

    webcast_date: date | None
    event_url: str | None
    webcast_url: str | None
    source: str
    evidence: str
    fingerprint: str
    event_identity: dict[str, Any] | None = None


class OfficialScheduleEnricher:
    """Prefetch event routes and validate details from issuer-linked pages."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("SERPER_API_KEY", "")
        self.search_url = "https://google.serper.dev/search"
        self._issuer_failures: list[EnrichmentFailure] = []
        self._serper_failure: EnrichmentFailure | None = None
        self._page_fetch_succeeded = False
        self._schedule_time_conflicted = False
        self._conflict_details = []
        self._conflicted_clock_dates = set()
        self._clock_conflict_route = None
        self._page_documents: dict[str, str | bytes] = {}
        self._non_html_urls: set[str] = set()
        self._active_call: dict[str, Any] = {}
        self._observed_at: datetime | None = None
        self.last_dry_run: dict[str, Any] = {}
        self._unavailable_statuses: set[str] = set()
        self._official_time_withdrawn = False
        self._http_results: dict[str, tuple[str, str | None]] | None = None
        self._browser_results: dict[str, tuple[str, str | None]] = {}
        self._browser_phase = True
        self._browser_pages = self._batch_browser_pages = 0
        self._browser_seconds = self._batch_browser_seconds = 0.0
        self._provider_urls: set[str] = set()
        self._browser_skipped: set[str] = set()
        self._route_diagnostics: list[dict[str, Any]] = []

    def verify_call(self, call: dict[str, Any], *, dry_run: bool = False) -> VerifiedScheduleTime | None:
        """Compare current issuer index with stored details before committing evidence."""
        self.last_dry_run = {}
        if not dry_run and self._call_cooldown_active(call):
            return None
        self._issuer_failures, self._serper_failure = [], None
        self._page_fetch_succeeded = self._schedule_time_conflicted = False
        self._page_documents, self._non_html_urls = {}, set()
        self._unavailable_statuses = set()
        self._official_time_withdrawn = False
        self._http_results, self._browser_results = {}, {}
        self._browser_pages, self._browser_seconds = 0, 0.0
        self._provider_urls, self._browser_skipped = set(), set()
        self._route_diagnostics = []
        self._conflict_details = []
        self._conflicted_clock_dates = set()
        self._clock_conflict_route = None
        # Cheap issuer/provider HTTP reads run first across every known route.
        # Only unresolved nearby calls may spend the shared browser allowance.
        self._browser_phase = False
        self._active_call, self._observed_at = dict(call), datetime.utcnow()
        expected_date = self._call_expected_date(call)
        if expected_date is None:
            if not dry_run:
                self._record_unverified_outcome(call)
            return None
        verified_values, discoveries, date_evidence = [], [], []
        linked_routes = {}
        provider_verified = set()

        def inspect(url, prefix):
            verified = self._verify_event_page(url, expected_date, prefix)
            if verified:
                verified_values.append(verified)
            discovery = self._discover_cached_event(self._active_call, url, expected_date, prefix)
            if discovery:
                discoveries.append(discovery)
                if discovery.webcast_date != expected_date and discovery.event_identity.get('date_shift_verified'):
                    shifted = self._verify_event_page(url, discovery.webcast_date, prefix)
                    if shifted:
                        verified_values.append(shifted)
                followed = self._follow_discovered_event(self._active_call, discovery, expected_date)
                if isinstance(followed, VerifiedScheduleTime):
                    verified_values.append(followed)
                    # A clock on the detail page must not discard the newly
                    # discovered provider when merging with the index route.
                    detail = self._discover_cached_event(self._active_call,
                        followed.event_url, followed.webcast_date, 'official_ir_discovered_event')
                    if detail:
                        discoveries.append(detail)
                elif followed:
                    discoveries.append(followed)
                route = (detail or discovery) if isinstance(followed, VerifiedScheduleTime) else (
                    followed if isinstance(followed, OfficialEventDiscovery) else discovery)
                if route.webcast_url:
                    linked_routes[route.webcast_url] = route
                # A printed issuer clock must not suppress checking its own
                # linked event provider. Both belong to this exact event and
                # can disagree (for example, a stale standard-time label).
                provider_time = self._verify_linked_provider(route, expected_date)
                if provider_time:
                    verified_values.append(provider_time)
                    provider_verified.add(route.webcast_url)
            elif str(call.get("schedule_revalidation_status") or '').lower() == 'required':
                evidence = self._verify_event_page_date(url, expected_date, prefix)
                if evidence:
                    date_evidence.append((url, prefix, evidence))

        direct_urls = self._direct_official_urls(call)
        for url, prefix in direct_urls:
            inspect(url, prefix)
        # Broken or stale detail URLs often have a usable issuer listing above
        # them. Inspect that bounded route before relying on external search.
        if not any(value.webcast_url for value in discoveries):
            known = {url for url, _ in direct_urls}
            fallbacks = []
            for url, _ in direct_urls:
                for parent in issuer_listing_fallbacks(url):
                    if parent not in known and self._url_matches_issuer(call, parent):
                        known.add(parent)
                        fallbacks.append((parent, 'official_ir_listing_recovery'))
            for url, prefix in fallbacks[:2]:
                self._route_diagnostics.append({'reason': 'issuer_listing_recovery', 'url': url})
                direct_urls.append((url, prefix))
                inspect(url, prefix)
        # A useful date-only route does not stop inspection of other known issuer
        # pages. Search only adds a bounded issuer page, never a snippet as proof.
        if not verified_values and not discoveries and not date_evidence:
            results = self._search_event_results(call, expected_date) if not dry_run else []
            official = self._select_official_result(call, results)
            if official and official.link not in self._page_documents:
                direct_urls.append((official.link, 'official_ir_event'))
                inspect(official.link, 'official_ir_event')
                if not verified_values:
                    fallback = self._verify_indexed_official_time_with_wire(call, expected_date, official, results)
                    if fallback:
                        verified_values.append(fallback)
        # Check the already authenticated provider before repeated issuer
        # rendering consumes the small shared browser budget on an outage.
        # This can disprove a stored clock but never establishes a fresh route.
        retained_provider_clock = None
        if (not linked_routes and self._issuer_failures and not self._unavailable_statuses
                and not self._schedule_time_conflicted):
            retained_provider_clock = self._crosscheck_retained_provider_clock(call, expected_date)
        if not verified_values and self._nearby_browser_allowed():
            self._browser_phase = True
            for url, prefix in direct_urls:
                inspect(url, prefix)
                if verified_values:
                    break
        # Provider times often render only in a browser. Still use the bounded
        # near-call budget when HTTP found an issuer clock, rather than silently
        # choosing that clock without checking the currently linked provider.
        if linked_routes and self._nearby_browser_allowed():
            self._browser_phase = True
            for url, route in linked_routes.items():
                if url in provider_verified:
                    continue
                provider_time = self._verify_linked_provider(route, expected_date)
                if provider_time:
                    verified_values.append(provider_time)
                    provider_verified.add(url)
        if call.get('schedule_revalidation_reason') == 'ambiguous_call_time':
            try:
                prior = json.loads(call.get('schedule_revalidation_evidence') or '{}')
            except (TypeError, ValueError):
                prior = {}
            previous_clocks = prior.get('clock_observations', []) if isinstance(prior, dict) else []
            if not isinstance(previous_clocks, list):
                previous_clocks = []
            observed_clock_sources = {
                value.webcast_url if 'linked_provider' in value.schedule_source else value.event_url
                for value in verified_values}
            if retained_provider_clock:
                observed_clock_sources.add(retained_provider_clock.webcast_url)
            unavailable = [item for item in previous_clocks if isinstance(item, dict)
                and item.get('source') and item['source'] not in observed_clock_sources]
            if unavailable and prior.get('route_identity_verified') is True:
                # An outage or disappearing clock is not corroboration on
                # either side. Re-observe every source of the previous
                # disagreement before allowing one surviving clock to win.
                self._note_conflict('start_time_conflict', previous_clocks +
                    self._current_clock_observations(verified_values + ([retained_provider_clock] if retained_provider_clock else [])),
                    reobserved=False)
                self._route_diagnostics.append({'reason': 'prior_source_clock_conflict_unresolved',
                                                'urls': [item['source'] for item in unavailable]})
        times = {value.scheduled_at_utc for value in verified_values}
        dates = ({value.webcast_date for value in discoveries if value.webcast_date}
                 | {value.webcast_date for value in verified_values}
                 | self._conflicted_clock_dates)
        if len(times) > 1:
            self._note_conflict('start_time_conflict', [
                {'value': v.scheduled_at_utc.isoformat(),
                 'source': v.webcast_url if 'linked_provider' in v.schedule_source else v.event_url,
                 'source_timezone': v.source_timezone,
                 'evidence': v.schedule_evidence[-600:]} for v in verified_values])
        if len(dates) > 1:
            self._note_conflict('event_date_conflict', [
                {'value': str(d.webcast_date), 'source': d.event_url,
                 'evidence': d.evidence[-600:]} for d in discoveries] + [
                {'value': str(v.webcast_date), 'source': v.event_url,
                 'evidence': v.schedule_evidence[-600:]} for v in verified_values])
        best = max(discoveries, key=lambda d: (
            bool(d.webcast_url), d.source.startswith('official_ir_discovered_event'),
            bool(d.event_identity), bool(d.event_url)), default=None)
        if verified_values and self._unavailable_statuses:
            self._note_conflict("event_status_conflict", sorted(self._unavailable_statuses))
        verified = verified_values[0] if len(times) == 1 and not self._schedule_time_conflicted else None
        if verified and best and not self._clock_route_compatible(verified, best):
            # Even individually plausible observations cannot authenticate a
            # route for a different date/period than the selected clock.
            self._note_conflict("clock_route_conflict", [{"clock_date": str(verified.webcast_date), "route_date": str(best.webcast_date), "source": best.event_url}])
            verified = None
        if verified and best:
            verified = replace(verified, webcast_url=best.webcast_url,
                               event_url=best.event_url or verified.event_url,
                               event_identity=best.event_identity,
                               schedule_discovery_fingerprint=best.fingerprint,
                               schedule_evidence=best.evidence + ' | ' + verified.schedule_evidence)
        self._official_time_withdrawn = bool(not verified_values and best
            and best.event_identity.get('identity_verified')
            and best.event_url == call.get('event_url')
            and best.event_url in self._page_documents
            and best.webcast_date == expected_date
            and call.get('scheduled_at_utc')
            # A parent IR card without a clock cannot withdraw a time read on
            # its provider page or by the authenticated capture browser.
            and not str(call.get('schedule_source') or '').startswith('official_browser_')
            and not str(call.get('schedule_source') or '').endswith('_browser')
            and 'linked_provider' not in str(call.get('schedule_source') or ''))
        route_urls = {d.webcast_url for d in discoveries if d.webcast_url}
        if len(route_urls) > 1 and self._schedule_time_conflicted:
            self._note_conflict('event_route_conflict', sorted(route_urls))
        if len(route_urls) > 1:
            self._route_diagnostics.append({'reason': 'multiple_provider_routes', 'urls': sorted(route_urls)})
        clock_only = bool(self._conflict_details and all(
            item['kind'] == 'start_time_conflict' for item in self._conflict_details))
        if (self._schedule_time_conflicted and clock_only and not self._unavailable_statuses
                and best and best.webcast_url and len(route_urls) == 1
                and best.webcast_date == expected_date
                and best.event_identity.get('identity_verified') is True
                and best.event_identity.get('event_type') == 'earnings_call'
                and not stored_event_kind_conflict(best.evidence)):
            self._clock_conflict_route = best
            self._route_diagnostics.append({'reason': 'route_verified_clock_ambiguous', 'url': best.webcast_url})
        if verified:
            retained = retained_route_fields(call, verified.as_database_values(), verified.event_identity)
            self._route_diagnostics.append({'reason': 'retain_previous_route_missing_provider' if retained
                else 'replace_route_from_current_evidence' if verified.webcast_url else 'no_authenticated_provider',
                'url': retained.get('webcast_url') or verified.webcast_url,
                'retained_checked_at': str(retained.get('schedule_discovery_checked_at') or '')})
        elif self._schedule_time_conflicted and not self._clock_conflict_route:
            self._route_diagnostics.append({'reason': 'route_not_refreshed_conflicting_identity_or_unproven'})
        self.last_dry_run = {'verified': verified.as_database_values() if verified else None,
                             'discovery': vars(best) if best else None,
                             'conflicted': self._schedule_time_conflicted,
                             'conflicts': self._conflict_details,
                             'unavailable_statuses': sorted(self._unavailable_statuses),
                             'official_time_withdrawn': self._official_time_withdrawn,
                             'pages_checked': sorted(self._page_documents),
                             'browser_pages': self._browser_pages,
                             'browser_seconds': round(self._browser_seconds, 3),
                             'browser_skipped': sorted(self._browser_skipped),
                             'route_diagnostics': self._route_diagnostics,
                             'failures': [vars(value) for value in self._issuer_failures]}
        if dry_run:
            return verified
        if verified:
            values = verified.as_database_values()
            values['clock_observations'] = self._current_clock_observations(
                verified_values + ([retained_provider_clock] if retained_provider_clock else []))
            values.update(expected_revision=call.get('schedule_revision'), observed_at=self._observed_at)
            revision = database.update_verified_schedule_time(call['id'], values)
            return verified if revision is not None else None
        if best and not self._schedule_time_conflicted and 'cancelled' not in self._unavailable_statuses:
            if self._persist_discovery(call, best) is None:
                return None
        elif date_evidence and not self._schedule_time_conflicted:
            url, prefix, evidence = date_evidence[0]
            database.confirm_schedule_revalidation_from_official_ir(
                call['id'], event_url=url, evidence=f'{prefix}: {evidence}',
                expected_revision=call.get('schedule_revision'), observed_at=self._observed_at,
            )
        self._record_unverified_outcome(call)
        return None

    def _current_clock_observations(self, values):
        from datetime import timezone
        observed = (self._observed_at or datetime.utcnow()).replace(tzinfo=timezone.utc).isoformat()
        return [{'value': value.scheduled_at_utc.isoformat(),
                 'source': value.webcast_url if 'linked_provider' in value.schedule_source else value.event_url,
                 'source_timezone': value.source_timezone, 'evidence': value.schedule_evidence[-1000:],
                 'observed_at': observed} for value in values]

    def _note_conflict(self, kind, candidates, *, reobserved=True):
        self._schedule_time_conflicted = True
        if kind == 'start_time_conflict' and reobserved:
            from datetime import timezone
            observed = (self._observed_at or datetime.utcnow()).replace(tzinfo=timezone.utc).isoformat()
            candidates = [{**item, 'observed_at': item.get('observed_at') or observed}
                          if isinstance(item, dict) and item.get('observation') != 'stored' else item
                          for item in candidates]
        item = {'kind': kind, 'candidates': candidates[:12]}
        if item not in self._conflict_details:
            self._conflict_details.append(item)

    @staticmethod
    def _call_expected_date(call: dict[str, Any]) -> date | None:
        value = call.get("webcast_date") or call.get("earning_at")
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not value:
            return None
        try:
            return date.fromisoformat(str(value).strip()[:10])
        except ValueError:
            return None

    def _persist_discovery(
        self,
        call: dict[str, Any],
        discovery: OfficialEventDiscovery,
    ) -> None:
        revision = database.update_official_schedule_discovery(
            int(call["id"]),
            webcast_date=discovery.webcast_date,
            event_url=discovery.event_url,
            webcast_url=discovery.webcast_url,
            source=discovery.source,
            evidence=discovery.evidence,
            fingerprint=discovery.fingerprint,
            event_identity=discovery.event_identity,
            expected_revision=call.get("schedule_revision"),
            observed_at=self._observed_at,
        )
        if isinstance(revision, int):
            call['schedule_revision'] = revision
        return revision

    def _follow_discovered_event(
        self,
        call: dict[str, Any],
        discovery: OfficialEventDiscovery,
        expected_date: date,
    ) -> VerifiedScheduleTime | OfficialEventDiscovery | None:
        """Follow at most one issuer event-detail link before the live window."""
        event_url = str(discovery.event_url or "")
        internal_action = str(discovery.webcast_url or '')
        if (event_url in self._page_documents and internal_action
                and internal_action not in self._page_documents
                and self._url_matches_issuer(call, internal_action)):
            # An issuer detail link labelled "Earnings Call" also looks like a
            # playback action. Read that one page before treating it as final.
            event_url = internal_action
        if not event_url or (event_url in self._page_documents and not self._browser_phase):
            return discovery
        if not self._url_matches_issuer(call, event_url):
            return discovery

        if discovery.event_identity and discovery.event_identity.get('date_shift_verified'):
            expected_date = discovery.webcast_date or expected_date
        # Carry the identity of the selected card to its destination. A call
        # without a previously stored fiscal period must not accept any other
        # period just because the parent link looked correct.
        target_call = dict(call)
        for source, dest in (('fiscal_year', 'verified_fiscal_year'),
                             ('fiscal_quarter', 'verified_fiscal_quarter')):
            if discovery.event_identity.get(source):
                target_call[dest] = discovery.event_identity[source]
        previous_call = self._active_call
        self._active_call = target_call
        try:
            verified = self._verify_event_page(
                event_url, expected_date, "official_ir_discovered_event")
            detail = self._discover_cached_event(
                target_call, event_url, expected_date, "official_ir_discovered_event")
        finally:
            self._active_call = previous_call
        if verified:
            if not self._clock_route_compatible(verified, detail or discovery):
                self._note_conflict("clock_route_conflict", [{"source": event_url, "clock_date": str(verified.webcast_date), "route_date": str((detail or discovery).webcast_date)}])
                return None
            return verified
        if not detail:
            return discovery
        values = sorted({discovery.fingerprint, detail.fingerprint})
        identity = detail.event_identity or discovery.event_identity or {}
        merged_day = detail.webcast_date or discovery.webcast_date
        merged_event = detail.event_url or discovery.event_url
        merged_webcast = detail.webcast_url or discovery.webcast_url
        proof = route_proof(ticker=call.get('ticker'),day=merged_day,issuer_url=event_url,
                            event_url=merged_event,webcast_url=merged_webcast,
                            fiscal_year=identity.get('fiscal_year'),fiscal_quarter=identity.get('fiscal_quarter'),
                            event_type=identity.get('event_type','earnings_date'))
        human_evidence = detail.evidence.split('] ',1)[-1]
        return OfficialEventDiscovery(
            webcast_date=detail.webcast_date or discovery.webcast_date,
            event_url=detail.event_url or discovery.event_url,
            webcast_url=detail.webcast_url or discovery.webcast_url,
            source=detail.source,
            evidence=f"{proof} {human_evidence}"[:3500],
            fingerprint=hashlib.sha256("|".join(values).encode("utf-8")).hexdigest(),
            event_identity=detail.event_identity or discovery.event_identity,
        )

    @staticmethod
    def _clock_route_compatible(clock, route):
        if clock.webcast_date != route.webcast_date:
            return False
        clock_identity = clock.event_identity or {}
        parsed_year, parsed_quarter = fiscal_period(clock.schedule_evidence)
        for expected, observed in (
            (clock_identity.get('fiscal_year') or parsed_year, route.event_identity.get('fiscal_year')),
            (clock_identity.get('fiscal_quarter') or parsed_quarter, route.event_identity.get('fiscal_quarter')),
        ):
            if expected and observed and str(expected).upper() != str(observed).upper():
                return False
        return True

    def _verify_linked_provider(self, discovery, expected_date):
        """Read one provider landing page linked from this issuer's event card.

        No login, registration, playback or arbitrary stored provider URL is
        used here. Normal callers prove the link in the current issuer DOM.
        The retained-route cross-check caller can only demote an old clock.
        """
        url = str(discovery.webcast_url or '')
        identity = discovery.event_identity or {}
        if (not url or not identity.get('identity_verified') or
                self._url_matches_issuer(self._active_call, url) or
                not self._nearby_browser_allowed()):
            return None
        if self._provider_urls and url not in self._provider_urls:
            return None
        self._provider_urls.add(url)
        provider_text, _ = self._fetch_event_page(url)
        method = 'http'
        day = discovery.webcast_date or expected_date
        parsed = parse_call_times(provider_text, day, grace_days=0,
            expected_fiscal_year=identity.get('fiscal_year'),
            expected_fiscal_quarter=identity.get('fiscal_quarter'))
        if not parsed.selected and self._browser_phase:
            provider_text, _ = self._fetch_event_page_with_browser(url)
            parsed = parse_call_times(provider_text, day, grace_days=0,
                expected_fiscal_year=identity.get('fiscal_year'),
                expected_fiscal_quarter=identity.get('fiscal_quarter'))
            method = 'browser'
        # A shared provider may redirect to a different issuer/event. Require
        # issuer naming and compare printed fiscal periods before using a time.
        candidate_text = parsed.selected.evidence if parsed.selected else provider_text
        content = re.sub(r'[^a-z0-9]', '', candidate_text.lower())
        company_terms = [re.sub(r'[^a-z0-9]', '', term.lower()) for term in
                         str(self._active_call.get('company_name') or '').split()
                         if len(term) >= 4 and term.lower().strip('.,') not in
                         {'corporation', 'company', 'incorporated', 'holdings', 'group', 'corp', 'inc', 'ltd'}]
        if not company_terms or not all(term and term in content for term in company_terms):
            return None
        provider_period = fiscal_period(candidate_text)
        if any(expected and observed and str(expected) != str(observed) for expected, observed in zip(
                (identity.get('fiscal_year'), identity.get('fiscal_quarter')), provider_period)):
            return None
        if parsed.conflicted:
            self._record_parsed_conflict(parsed, url)
        if parsed.unavailable_reason:
            self._unavailable_statuses.add(parsed.unavailable_reason)
        selected = parsed.selected
        if not selected:
            return None
        return VerifiedScheduleTime(selected.webcast_date, selected.scheduled_at_utc,
            selected.source_timezone, discovery.event_url, url,
            'official_ir_linked_provider_' + method,
            discovery.evidence + ' | Provider start: ' + selected.evidence,
            identity, discovery.fingerprint)

    def _crosscheck_retained_provider_clock(self, call, expected_date):
        """Read proven history for contradiction only; never renew its route TTL."""
        proof = authenticated_route(call)
        if not proof or not self._nearby_browser_allowed():
            return None
        identity = {'identity_verified': True, 'event_type': 'earnings_call',
                    'fiscal_year': proof.get('fiscal_year') or call.get('verified_fiscal_year'),
                    'fiscal_quarter': proof.get('fiscal_quarter') or call.get('verified_fiscal_quarter')}
        route = OfficialEventDiscovery(expected_date, call.get('event_url'), call['webcast_url'],
            str(call.get('schedule_source') or ''), str(call.get('schedule_evidence') or ''),
            call['schedule_discovery_fingerprint'], identity)
        self._browser_phase = True
        current = self._verify_linked_provider(route, expected_date)
        if not current:
            return None
        provider_evidence = current.schedule_evidence.rsplit(' | Provider start: ', 1)[-1]
        _, quarter = fiscal_period(provider_evidence)
        if identity.get('fiscal_quarter') and quarter != identity['fiscal_quarter']:
            return None
        self._route_diagnostics.append({'reason': 'retained_provider_clock_crosscheck',
            'url': current.webcast_url, 'route_checked_at': str(call.get('schedule_discovery_checked_at')),
            'route_refreshed': False})
        stored = self._as_naive_datetime(call.get('scheduled_at_utc'))
        if stored and stored != current.scheduled_at_utc.replace(tzinfo=None):
            old_source = (call.get('webcast_url') if 'provider' in str(call.get('schedule_source') or '')
                          else call.get('event_url'))
            self._note_conflict('start_time_conflict', [
                {'value': stored.isoformat() + '+00:00', 'source': old_source,
                 'source_timezone': call.get('source_timezone'),
                 'evidence': str(call.get('schedule_evidence') or '')[-600:], 'observation': 'stored',
                 'observed_at': str(call.get('time_verified_at') or '')},
                {'value': current.scheduled_at_utc.isoformat(), 'source': current.webcast_url,
                 'source_timezone': current.source_timezone, 'evidence': provider_evidence[-600:],
                 'observation': 'current_retained_provider'}])
        return current

    @staticmethod
    def _budget_int(name, default, minimum=1, maximum=300):
        try:
            return min(maximum, max(minimum, int(os.getenv(name, str(default)))))
        except ValueError:
            return default

    def _nearby_browser_allowed(self):
        if not self._active_call:
            return True
        expected = self._call_expected_date(self._active_call)
        now = self._observed_at or datetime.utcnow()
        from datetime import timezone
        today = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(
            os.getenv('DATE_STREAM_WATCH_TIMEZONE', 'America/New_York'))).date()
        ahead = self._budget_int('SCHEDULE_TIME_BROWSER_DAYS_AHEAD', 2, minimum=0, maximum=14)
        allowed = bool(expected and -2 <= (expected - today).days <= ahead)
        if not allowed:
            self._browser_skipped.add('outside_nearby_window')
        return allowed

    @staticmethod
    def _retry_minutes(name: str, default: int) -> int:
        try:
            return max(1, int(os.getenv(name, str(default))))
        except ValueError:
            return max(1, default)

    @staticmethod
    def _as_naive_datetime(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    def _call_cooldown_active(self, call: dict[str, Any]) -> bool:
        retry_not_before = self._as_naive_datetime(
            call.get("schedule_enrichment_retry_not_before")
        )
        return bool(retry_not_before and retry_not_before > datetime.utcnow())

    def _record_issuer_failure(
        self,
        kind: str,
        message: str,
        *,
        retry_env: str,
        retry_default: int,
    ) -> None:
        self._issuer_failures.append(
            EnrichmentFailure(
                kind=kind,
                message=message,
                retry_minutes=self._retry_minutes(retry_env, retry_default),
            )
        )

    def _no_time_retry_minutes(self, call):
        expected = self._call_expected_date(call)
        today = datetime.now(ZoneInfo('America/New_York')).date()
        if expected and abs((expected-today).days) <= 1:
            return self._retry_minutes('SCHEDULE_ENRICH_NEAR_NO_TIME_RETRY_MINUTES', 10)
        return self._retry_minutes('SCHEDULE_ENRICH_NO_TIME_RETRY_MINUTES', 60)

    def _record_unverified_outcome(self, call: dict[str, Any]) -> None:
        call_id = call.get("id")
        if not call_id:
            return
        if self._page_fetch_succeeded and self._unavailable_statuses:
            status = 'cancelled' if 'cancelled' in self._unavailable_statuses else 'postponed' if 'postponed' in self._unavailable_statuses else 'time_tbd'
            failure = EnrichmentFailure(kind='official_'+status,
                message=f'Current official earnings event explicitly reports {status}',
                retry_minutes=self._no_time_retry_minutes(call))
        elif self._page_fetch_succeeded and self._schedule_time_conflicted:
            clock_only = bool(self._conflict_details and all(
                item['kind'] == 'start_time_conflict' for item in self._conflict_details))
            failure = EnrichmentFailure(
                kind="ambiguous_call_time" if clock_only else "ambiguous_event_identity",
                message=json.dumps({'conflicts': self._conflict_details}, default=str)[:3000],
                retry_minutes=self._retry_minutes("SCHEDULE_TIME_NEAR_REVERIFY_MINUTES", 30),
            )
        elif self._page_fetch_succeeded and self._official_time_withdrawn:
            failure = EnrichmentFailure(kind='official_time_withdrawn',
                message='Previously verified issuer event still matches but no longer publishes a start time',
                retry_minutes=self._no_time_retry_minutes(call))
        elif self._page_fetch_succeeded:
            failure = EnrichmentFailure(
                kind="no_official_time",
                message="Issuer pages had no date-matched exact earnings start time",
                retry_minutes=self._no_time_retry_minutes(call),
            )
        elif self._issuer_failures:
            failure = self._issuer_failures[-1]
        elif self._serper_failure:
            failure = self._serper_failure
        else:
            failure = EnrichmentFailure(
                kind="no_official_time",
                message="No issuer event page or exact earnings start time found",
                retry_minutes=self._no_time_retry_minutes(call),
            )
        database.record_schedule_enrichment_outcome(
            int(call_id),
            failure_kind=failure.kind,
            error=failure.message,
            retry_minutes=failure.retry_minutes,
            **({'route_observation': vars(self._clock_conflict_route)} if self._clock_conflict_route else {}),
            **({'clock_observations': [candidate for item in self._conflict_details
                                      if item['kind'] == 'start_time_conflict'
                                      for candidate in item['candidates']]}
               if failure.kind == 'ambiguous_call_time' else {}),
            **({'expected_revision': call.get('schedule_revision'), 'observed_at': self._observed_at}
               if self._observed_at is not None else {}),
        )

    def _direct_official_urls(self, call: dict[str, Any]) -> list[tuple[str, str]]:
        """Return persisted issuer-domain pages that are safe to recheck directly."""
        issuer_host = self._issuer_host(call)
        if not issuer_host:
            return []

        values: list[tuple[str, str]] = []
        seen: set[str] = set()
        for field, source_prefix in (
            ("event_url", "official_ir_stored_event"),
            ("ir_url", "official_ir_page"),
        ):
            value = str(call.get(field) or "").strip()
            if not value or value in seen or not self._url_matches_issuer(call, value):
                continue
            seen.add(value)
            values.append((value, source_prefix))
        return values

    @staticmethod
    def _issuer_host(call: dict[str, Any]) -> str:
        return (
            (urlparse(str(call.get("ir_url") or "")).hostname or "")
            .lower()
            .removeprefix("www.")
        )

    @classmethod
    def _url_matches_issuer(cls, call: dict[str, Any], value: str) -> bool:
        issuer_host = cls._issuer_host(call)
        host = (urlparse(value).hostname or "").lower().removeprefix("www.")
        return bool(issuer_host and host) and (
            host == issuer_host or host.endswith(f".{issuer_host}")
        )

    def _search_event_results(self, call: dict[str, Any], expected_date: date) -> list[SearchResult]:
        if not self.api_key:
            self._serper_failure = EnrichmentFailure(
                kind="serper_unconfigured",
                message="Serper search skipped because no API key is configured",
                retry_minutes=self._retry_minutes(
                    "SCHEDULE_ENRICH_SERPER_UNCONFIGURED_RETRY_MINUTES",
                    720,
                ),
            )
            return []
        circuit = database.get_schedule_enrichment_circuit(SERPER_CIRCUIT_SCOPE)
        if circuit:
            kind = str(circuit.get("failure_kind") or "provider_error")
            self._serper_failure = EnrichmentFailure(
                kind=f"serper_circuit_{kind}"[:64],
                message=(
                    f"Serper circuit open for {kind}; retry after "
                    f"{circuit.get('retry_not_before')}"
                ),
                retry_minutes=self._retry_minutes(
                    "SCHEDULE_ENRICH_SERPER_CIRCUIT_RETRY_MINUTES",
                    60,
                ),
            )
            print(
                f"[{call['ticker']}] Serper search skipped: circuit open "
                f"kind={kind} retry_after={circuit.get('retry_not_before')}",
                flush=True,
            )
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
                    json={"q": query},
                    timeout=20,
                )
            except requests.Timeout:
                failure = EnrichmentFailure(
                    kind="serper_timeout",
                    message="Serper search timed out",
                    retry_minutes=self._retry_minutes(
                        "SCHEDULE_ENRICH_SERPER_TRANSIENT_RETRY_MINUTES",
                        15,
                    ),
                )
                self._open_serper_circuit(failure)
                break
            except requests.RequestException as exc:
                failure = EnrichmentFailure(
                    kind="serper_network_error",
                    message=f"Serper network request failed: {type(exc).__name__}",
                    retry_minutes=self._retry_minutes(
                        "SCHEDULE_ENRICH_SERPER_TRANSIENT_RETRY_MINUTES",
                        15,
                    ),
                )
                self._open_serper_circuit(failure)
                break

            if not response.ok:
                failure = self._classify_serper_response(response)
                self._open_serper_circuit(failure)
                break

            try:
                organic_results = response.json().get("organic", [])
            except ValueError:
                failure = EnrichmentFailure(
                    kind="serper_response_invalid",
                    message="Serper returned an invalid JSON response",
                    retry_minutes=self._retry_minutes(
                        "SCHEDULE_ENRICH_SERPER_TRANSIENT_RETRY_MINUTES",
                        15,
                    ),
                )
                self._open_serper_circuit(failure)
                break
            database.clear_schedule_enrichment_circuit(SERPER_CIRCUIT_SCOPE)

            for result in organic_results:
                link = str(result.get("link", ""))
                if link and link not in found:
                    found[link] = SearchResult(
                        link=link,
                        title=str(result.get("title", "")),
                        snippet=str(result.get("snippet", "")),
                    )
        return list(found.values())

    def _open_serper_circuit(self, failure: EnrichmentFailure) -> None:
        self._serper_failure = failure
        database.open_schedule_enrichment_circuit(
            SERPER_CIRCUIT_SCOPE,
            failure_kind=failure.kind,
            error=failure.message,
            retry_minutes=failure.retry_minutes,
        )
        print(
            f"[ScheduleTime] Serper circuit opened kind={failure.kind} "
            f"retry_minutes={failure.retry_minutes}",
            flush=True,
        )

    def _classify_serper_response(self, response: requests.Response) -> EnrichmentFailure:
        status_code = int(response.status_code)
        body = str(response.text or "").lower()
        if any(
            marker in body
            for marker in (
                "not enough credits",
                "insufficient credits",
                "credits exhausted",
                "credit balance",
            )
        ):
            return EnrichmentFailure(
                kind="serper_credits_exhausted",
                message=f"Serper HTTP {status_code}: credits exhausted",
                retry_minutes=self._retry_minutes(
                    "SCHEDULE_ENRICH_SERPER_CREDITS_COOLDOWN_MINUTES",
                    720,
                ),
            )
        if status_code in {401, 403} or any(
            marker in body
            for marker in (
                "invalid api key",
                "invalid api-key",
                "api key is invalid",
                "unauthorized api key",
            )
        ):
            return EnrichmentFailure(
                kind="serper_api_key_error",
                message=f"Serper HTTP {status_code}: API key rejected",
                retry_minutes=self._retry_minutes(
                    "SCHEDULE_ENRICH_SERPER_KEY_COOLDOWN_MINUTES",
                    1440,
                ),
            )
        if status_code == 429 or "rate limit" in body:
            return EnrichmentFailure(
                kind="serper_rate_limited",
                message=f"Serper HTTP {status_code}: rate limited",
                retry_minutes=self._retry_minutes(
                    "SCHEDULE_ENRICH_SERPER_RATE_LIMIT_COOLDOWN_MINUTES",
                    60,
                ),
            )
        if status_code == 400:
            return EnrichmentFailure(
                kind="serper_request_error",
                message="Serper HTTP 400: request rejected",
                retry_minutes=self._retry_minutes(
                    "SCHEDULE_ENRICH_SERPER_REQUEST_ERROR_COOLDOWN_MINUTES",
                    60,
                ),
            )
        return EnrichmentFailure(
            kind="serper_provider_error",
            message=f"Serper HTTP {status_code}: provider error",
            retry_minutes=self._retry_minutes(
                "SCHEDULE_ENRICH_SERPER_TRANSIENT_RETRY_MINUTES",
                15,
            ),
        )

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
                    self._call_expected_date(call) or datetime.utcnow().date(),
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
        if self._active_call:
            route = self._discover_cached_event(self._active_call, event_url, expected_date, source_prefix)
            webcast_url = route.webcast_url if route else None
        verified = self._parse_verified_time(
            page_text,
            expected_date,
            event_url,
            webcast_url,
            f"{source_prefix}_http",
        )
        if verified:
            return verified

        if not self._browser_phase or not self._nearby_browser_allowed():
            return None
        browser_text, browser_webcast_url = self._fetch_event_page_with_browser(event_url)
        if self._active_call:
            route = self._discover_cached_event(self._active_call, event_url, expected_date, source_prefix)
            browser_webcast_url = route.webcast_url if route else None
        return self._parse_verified_time(
            browser_text,
            expected_date,
            event_url,
            browser_webcast_url,
            f"{source_prefix}_browser",
        )

    def _verify_event_page_date(
        self,
        event_url: str,
        expected_date: date,
        source_prefix: str,
    ) -> str | None:
        """Confirm a day from an official earnings/webcast announcement without a time."""
        page_text, _ = self._fetch_event_page(event_url)
        evidence = self._parse_official_date_evidence(page_text, expected_date)
        if evidence:
            return evidence

        if not self._browser_phase or not self._nearby_browser_allowed():
            return None
        browser_text, _ = self._fetch_event_page_with_browser(event_url)
        return self._parse_official_date_evidence(browser_text, expected_date)

    @staticmethod
    def _parse_official_date_evidence(page_text: str, expected_date: date) -> str | None:
        """Accept an expected date only when nearby text identifies an earnings event."""
        for match in DATE_ONLY_PATTERN.finditer(page_text or ""):
            year = int(match.group("year") or expected_date.year)
            month = MONTH_NUMBERS[match.group("month")[:3].lower()]
            try:
                parsed_date = date(year, month, int(match.group("day")))
            except ValueError:
                continue
            if parsed_date != expected_date:
                continue
            start, end = match.span()
            context = page_text[max(0, start - 220): min(len(page_text), end + 220)]
            if EARNINGS_DATE_CONTEXT_PATTERN.search(context):
                return re.sub(r"\s+", " ", context).strip()[:600]
        return None

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
                webcast_date=official_time.webcast_date,
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
                webcast_date=official_time.webcast_date,
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
        if self._http_results is not None and event_url in self._http_results:
            return self._http_results[event_url]
        result = self._fetch_event_page_uncached(event_url)
        if self._http_results is not None:
            self._http_results[event_url] = result
        return result

    def _fetch_event_page_uncached(self, event_url: str) -> tuple[str, str | None]:
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
            if isinstance(exc, requests.Timeout):
                self._record_issuer_failure(
                    "issuer_http_timeout",
                    "Issuer event page HTTP request timed out",
                    retry_env="SCHEDULE_ENRICH_ISSUER_TIMEOUT_RETRY_MINUTES",
                    retry_default=60,
                )
            else:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                self._record_issuer_failure(
                    (
                        "issuer_http_access_denied"
                        if status_code in {401, 403, 429}
                        else "issuer_http_error"
                    ),
                    (
                        f"Issuer event page HTTP {status_code}"
                        if status_code
                        else f"Issuer event page HTTP request failed: {type(exc).__name__}"
                    ),
                    retry_env=(
                        "SCHEDULE_ENRICH_ISSUER_ACCESS_RETRY_MINUTES"
                        if status_code in {401, 403, 429}
                        else "SCHEDULE_ENRICH_ISSUER_ERROR_RETRY_MINUTES"
                    ),
                    retry_default=360 if status_code in {401, 403, 429} else 60,
                )
            print(
                "official event page HTTP fetch unavailable: "
                f"{type(exc).__name__}",
                flush=True,
            )
            return "", None

        if not self._is_html_payload(
            response.content, response.headers.get("Content-Type", "")
        ):
            self._non_html_urls.add(event_url)
            self._record_issuer_failure(
                "issuer_non_html_document",
                "Issuer event URL returned a non-HTML document",
                retry_env="SCHEDULE_ENRICH_ISSUER_ERROR_RETRY_MINUTES",
                retry_default=60,
            )
            return "", None

        self._page_fetch_succeeded = True
        self._page_documents[event_url] = response.content
        return self._extract_page_details(response.content, event_url)

    def _fetch_event_page_with_browser(self, event_url: str) -> tuple[str, str | None]:
        """Read dynamically rendered IR pages inside the Playwright Docker image."""
        if event_url in self._non_html_urls:
            return "", None
        if not self._browser_phase or not self._nearby_browser_allowed():
            return "", None
        if event_url in self._browser_results:
            return self._browser_results[event_url]
        page_limit = self._budget_int('SCHEDULE_TIME_BROWSER_PAGES_PER_CALL', 2, maximum=5)
        batch_limit = self._budget_int('SCHEDULE_TIME_BROWSER_PAGES_PER_REFRESH', 6, maximum=20)
        remaining = min(
            self._budget_int('SCHEDULE_TIME_BROWSER_SECONDS_PER_CALL', 60) - self._browser_seconds,
            self._budget_int('SCHEDULE_TIME_BROWSER_SECONDS_PER_REFRESH', 120) - self._batch_browser_seconds,
            self._budget_int('SCHEDULE_TIME_BROWSER_PAGE_TIMEOUT_SECONDS', 35, maximum=60))
        if self._browser_pages >= page_limit or self._batch_browser_pages >= batch_limit or remaining < 1:
            self._browser_skipped.add('browser_budget_exhausted')
            return "", None
        self._browser_pages += 1
        self._batch_browser_pages += 1
        started = time.monotonic()
        result = ("", None)
        try:
            async def bounded_read():
                return await asyncio.wait_for(self._fetch_event_page_with_browser_async(event_url), timeout=remaining)
            result = asyncio.run(bounded_read())
            return result
        except Exception as exc:
            is_timeout = isinstance(exc, TimeoutError) or "timeout" in str(exc).lower()
            self._record_issuer_failure(
                "issuer_browser_timeout" if is_timeout else "issuer_browser_error",
                (
                    "Issuer event page browser request timed out"
                    if is_timeout
                    else f"Issuer event page browser request failed: {type(exc).__name__}"
                ),
                retry_env=(
                    "SCHEDULE_ENRICH_ISSUER_TIMEOUT_RETRY_MINUTES"
                    if is_timeout
                    else "SCHEDULE_ENRICH_ISSUER_ERROR_RETRY_MINUTES"
                ),
                retry_default=60,
            )
            print(
                "official event browser fetch unavailable: "
                f"{type(exc).__name__}",
                flush=True,
            )
            return "", None
        finally:
            elapsed = time.monotonic() - started
            self._browser_seconds += elapsed
            self._batch_browser_seconds += elapsed
            self._browser_results[event_url] = result

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
                # This reader never enters registration or starts a player.
                # Discard media assets to keep near-term schedule checks cheap.
                await context.route('**/*', lambda route: route.abort()
                    if route.request.resource_type in {'media', 'font', 'image'} else route.continue_())
                response = await page.goto(event_url, wait_until="domcontentloaded", timeout=25_000)
                if response is not None and response.status >= 400:
                    denied = response.status in {401, 403, 429}
                    self._record_issuer_failure(
                        'issuer_browser_access_denied' if denied else 'issuer_browser_http_error',
                        f'Issuer browser page HTTP {response.status}',
                        retry_env=('SCHEDULE_ENRICH_ISSUER_ACCESS_RETRY_MINUTES' if denied
                                   else 'SCHEDULE_ENRICH_ISSUER_ERROR_RETRY_MINUTES'),
                        retry_default=360 if denied else 60)
                    return '', None
                # A successful HTTP response can still be an empty JS shell.
                # Wait for scoped call evidence, rather than a fixed short sleep.
                expected = self._call_expected_date(self._active_call)
                deadline = time.monotonic() + 8
                while True:
                    page_content = await page.content()
                    text_value, _ = self._extract_page_details(page_content, event_url)
                    if expected and parse_call_times(text_value, expected).selected:
                        break
                    if time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(0.5)
                self._page_fetch_succeeded = True
                self._page_documents[event_url] = page_content
                return self._extract_page_details(page_content, event_url)
            finally:
                await browser.close()

    @staticmethod
    def _is_html_payload(page_content: str | bytes, content_type: str = "") -> bool:
        """Reject documents that a permissive HTML parser would mistake for a page."""
        prefix = (
            page_content[:4096].decode("ascii", errors="ignore")
            if isinstance(page_content, bytes)
            else page_content[:4096]
        ).lstrip("\ufeff \t\r\n")
        if prefix.startswith(("%PDF-", "PK\x03\x04", "GIF87a", "GIF89a", "PNG")):
            return False
        mime = str(content_type).partition(";")[0].strip().lower()
        if mime in {"text/html", "application/xhtml+xml"}:
            return True
        # Some issuer hosts omit or mislabel the MIME type. Keep their real HTML,
        # while excluding JSON, PDF, media and other document types explicitly.
        if mime not in {"", "text/plain", "application/octet-stream", "application/xml", "text/xml"}:
            return False
        return bool(HTML_MARKUP_PATTERN.search(prefix))

    @staticmethod
    def _parse_html_document(page_content: str | bytes):
        """Keep issuer encoding while making recovered HTML safe for DOM edits."""
        if isinstance(page_content, str):
            page_content = XML_UNSAFE_TEXT_PATTERN.sub(" ", page_content)
        try:
            document = html.fromstring(page_content)
        except (TypeError, ValueError, etree.ParserError):
            return None
        # libxml's recovering HTML parser retains some control characters, also
        # when encoded as numeric character references. Reassigning such a tail
        # later raises ValueError. Sanitize the parsed values, not raw bytes, so
        # declared encodings and legitimate non-ASCII issuer names stay intact.
        for node in document.iter():
            for field in ("text", "tail"):
                value = getattr(node, field)
                if value and XML_UNSAFE_TEXT_PATTERN.search(value):
                    setattr(node, field, XML_UNSAFE_TEXT_PATTERN.sub(" ", value))
            for key, value in tuple(node.attrib.items()):
                if XML_UNSAFE_TEXT_PATTERN.search(value):
                    node.set(key, XML_UNSAFE_TEXT_PATTERN.sub(" ", value))
        return document

    def _extract_page_details(self, page_content: str | bytes, event_url: str) -> tuple[str, str | None]:
        document = self._parse_html_document(page_content)
        if document is None:
            return "", None
        candidates = [c for c in self._document_link_candidates(document, event_url) if c.get('playback')]
        # The caller with event/date context selects among multiple cards later.
        scopes = {c['scope'] for c in candidates}
        webcast = candidates[0]['url'] if len(scopes) == 1 and candidates else None
        return self._schedule_time_text(document), webcast

    @staticmethod
    def _document_text(document) -> str:
        return re.sub(
            r"\s+",
            " ",
            " ".join(document.xpath("//text()[normalize-space()]")),
        ).strip()

    @classmethod
    def _schedule_time_text(cls, document) -> str:
        return schedule_time_text(document)

    @staticmethod
    def _normalize_discovered_url(base_url: str, raw_value: object) -> str | None:
        return normalize_route(base_url, raw_value)

    @classmethod
    def _element_context(cls, element) -> str:
        scope = event_scope(element)
        return visible_text(scope) if scope is not None else ''

    @classmethod
    def _document_link_candidates(cls, document, base_url: str) -> list[dict[str, Any]]:
        return scoped_candidates(document, base_url)

    @staticmethod
    def _official_dates_with_evidence(
        text_value: str,
        expected_date: date,
    ) -> list[tuple[date, str]]:
        matches: list[tuple[date, str]] = []
        patterns = (DATE_ONLY_PATTERN, DAY_MONTH_DATE_PATTERN, ISO_DATE_PATTERN)
        for pattern in patterns:
            for match in pattern.finditer(text_value or ""):
                try:
                    if pattern in (DATE_ONLY_PATTERN, DAY_MONTH_DATE_PATTERN):
                        year = int(match.group("year") or expected_date.year)
                        month = MONTH_NUMBERS[match.group("month")[:3].lower()]
                    else:
                        year = int(match.group("year"))
                        month = int(match.group("month"))
                    parsed = date(year, month, int(match.group("day")))
                except (KeyError, TypeError, ValueError):
                    continue
                start, end = match.span()
                if non_event_date_reason(text_value, start, end):
                    continue
                context = re.sub(
                    r"\s+",
                    " ",
                    text_value[max(0, start - 240): min(len(text_value), end + 240)],
                ).strip()
                if EARNINGS_DATE_CONTEXT_PATTERN.search(context):
                    matches.append((parsed, context[:600]))
        return matches

    @classmethod
    def _near_official_date(
        cls,
        text_value: str,
        expected_date: date,
    ) -> tuple[date, str] | None:
        try:
            grace_days = max(0, int(os.getenv("OFFICIAL_EVENT_DATE_GRACE_DAYS", "2")))
        except ValueError:
            grace_days = 2
        eligible = [
            item
            for item in cls._official_dates_with_evidence(text_value, expected_date)
            if abs((item[0] - expected_date).days) <= grace_days
        ]
        return min(
            eligible,
            key=lambda item: (abs((item[0] - expected_date).days), item[0]),
            default=None,
        )

    @staticmethod
    def _identity_allows_shift(call, text_value, page_url):
        if period_mismatch(call, text_value):
            return False
        year, quarter = fiscal_period(text_value)
        return bool(
            (year and quarter and year == call.get('verified_fiscal_year')
             and quarter == call.get('verified_fiscal_quarter'))
            or (call.get('official_event_key') == page_url
                and page_url != call.get('ir_url') and EARNINGS.search(text_value))
        )

    def _discover_cached_event(self, call, page_url, expected_date, source_prefix):
        page_content = self._page_documents.get(page_url)
        document = self._parse_html_document(page_content) if page_content else None
        if document is None or not self._url_matches_issuer(call, page_url):
            return None
        groups = {}
        for candidate in self._document_link_candidates(document, page_url):
            groups.setdefault(candidate['scope'], {'text':candidate['context'], 'links':[]})['links'].append(candidate)
        # Preserve an official date even when the provider link is not published.
        for node in document.xpath('//article|//section|//li|//tr|//p|//div'):
            scope = event_scope(node)
            if scope is not None:
                key = document.getroottree().getpath(scope)
                groups.setdefault(key, {'text':scope_text(scope), 'links':[]})
        eligible = []
        bootstrap = set()
        if not call.get('verified_fiscal_year') and not call.get('official_event_key'):
            for key, group in groups.items():
                year, quarter = fiscal_period(group['text'])
                dates = {day for day, _ in self._official_dates_with_evidence(group['text'], expected_date)}
                if (year and quarter and len(dates) == 1 and any(c.get('playback') for c in group['links'])
                        and abs((next(iter(dates)) - expected_date).days) <= 35
                        and next(iter(dates)) >= datetime.now(ZoneInfo('America/New_York')).date()):
                    bootstrap.add((year, quarter, next(iter(dates))))
        for group in groups.values():
            context = group['text']
            if not EARNINGS.search(context) or period_mismatch(call, context):
                continue
            dates = self._official_dates_with_evidence(context, expected_date)
            fiscal_year, fiscal_quarter = fiscal_period(context)
            observed = {day for day,_ in dates}
            bootstrap_shift = bool(len(bootstrap) == 1 and len(observed) == 1 and
                (fiscal_year,fiscal_quarter,next(iter(observed))) in bootstrap and
                any(c.get('playback') for c in group['links']))
            if self._identity_allows_shift(call, context, page_url) or bootstrap_shift:
                # A known immutable fiscal event or exact official event key may
                # move beyond the ordinary date tolerance. Multiple dates conflict.
                matched = list({day:evidence for day,evidence in dates}.items())
                local = matched[0] if len(matched) == 1 else self._near_official_date(context, expected_date)
            else:
                local = self._near_official_date(context, expected_date)
            if local is None:
                continue
            observed_date, evidence = local
            links = group['links']
            playback = [c for c in links if c.get('playback')]
            events = [c for c in links if self._url_matches_issuer(call,c['url']) and not c.get('playback')
                      and not is_event_navigation(c['url'], c['label'])
                      and (EARNINGS.search(c['label']) or re.search(r'event|earnings|results|conference|detail',c['label']+' '+urlparse(c['url']).path,re.I))]
            webcast_url = playback[0]['url'] if playback else None
            # A title link is stronger than a generic Details link. DOM order
            # does not establish that the first link belongs to the target.
            event = max(events, key=lambda c: (bool(EARNINGS.search(c['label'])),
                        bool(re.search(r'\bdetail', c['label'], re.I))), default=None)
            event_url = event['url'] if event else page_url
            year, quarter = fiscal_period(context)
            event_type = 'earnings_call' if PLAYBACK.search(context) else 'earnings_date'
            identity = {'fiscal_year':year, 'fiscal_quarter':quarter,
                        'event_type':event_type, 'official_event_key':event_url if event_url != call.get('ir_url') else None,
                        'identity_verified':event_type == 'earnings_call',
                        'date_shift_verified':self._identity_allows_shift(call,context,page_url) or bootstrap_shift}
            proof = route_proof(ticker=call.get('ticker'), day=observed_date, issuer_url=page_url,
                                event_url=event_url, webcast_url=webcast_url,
                                fiscal_year=year, fiscal_quarter=quarter, event_type=event_type)
            legacy = f'[target-linked:event_url={observed_date.isoformat()}'
            if webcast_url:
                legacy += f' target-linked:webcast_url={observed_date.isoformat()}'
            evidence = f'{proof} {legacy}] {evidence}'
            fingerprint = hashlib.sha256(json.dumps([observed_date.isoformat(), event_url,webcast_url,year,quarter],sort_keys=True).encode()).hexdigest()
            eligible.append(OfficialEventDiscovery(observed_date,event_url,webcast_url,
                            source_prefix+'_discovery',evidence[:3500],fingerprint,identity))
        if not eligible:
            return None
        # Do not choose randomly between distinct date-matched fiscal calls.
        periods = {(d.event_identity['fiscal_year'],d.event_identity['fiscal_quarter']) for d in eligible
                   if d.event_identity['fiscal_quarter']}
        if len(periods) > 1 or len({d.webcast_date for d in eligible}) > 1:
            self._note_conflict('event_identity_conflict', [
                {'value': str(d.webcast_date), 'source': d.event_url,
                 'identity': d.event_identity, 'evidence': d.evidence[-600:]} for d in eligible])
            return None
        return max(eligible,key=lambda d:(bool(d.webcast_url),d.event_url != page_url))

    @staticmethod
    def _call_time_json_records(page_text: str) -> tuple[list[dict[str, Any]], str]:
        """Read event startDate semantically, excluding publication/end timestamps."""
        records: list[dict[str, Any]] = []
        prose: list[str] = []
        decoder = json.JSONDecoder()

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                raw_type = value.get("@type", "")
                types = raw_type if isinstance(raw_type, list) else [raw_type]
                event_type = any(str(item).rsplit("/", 1)[-1].lower().endswith("event") for item in types)
                title = str(value.get("name") or value.get("headline") or "")
                if (
                    value.get("startDate")
                    and (event_type or (not raw_type and CALL_TIME_CONTEXT_PATTERN.search(title)))
                    and EARNINGS_DATE_CONTEXT_PATTERN.search(title)
                ):
                    records.append(value)
                # API-only articles may still contain an explicit call-start
                # sentence. Keep prose, but never treat datePublished as it.
                for key in ("articleBody", "body", "description"):
                    if isinstance(value.get(key), str):
                        prose.append(value[key])
                for item in value.values():
                    if isinstance(item, (dict, list)):
                        visit(item)

        remaining: list[str] = []
        cursor = 0
        opening_json = re.compile(r"[\[{]")
        while cursor < len(page_text):
            match = opening_json.search(page_text, cursor)
            if match is None:
                remaining.append(page_text[cursor:])
                break
            start = match.start()
            remaining.append(page_text[cursor:start])
            try:
                value, end = decoder.raw_decode(page_text, start)
            except ValueError:
                remaining.append(page_text[start:start + 1])
                cursor = start + 1
                continue
            visit(value)
            remaining.append("\n")
            cursor = end
        return records, "".join(remaining) + "\n" + "\n".join(prose)

    @staticmethod
    def _clock_is_call_start(clause: str, start: int, end: int) -> bool:
        """A clock must be attached to a call label, not a nearer release/expiry label."""
        def distance(match: re.Match[str]) -> int:
            return max(start - match.end(), match.start() - end, 0)

        positive_matches = list(CALL_TIME_CONTEXT_PATTERN.finditer(clause))
        negative_matches = list(NON_CALL_TIME_CONTEXT_PATTERN.finditer(clause))
        preceding = [match for match in positive_matches + negative_matches if match.end() <= start]
        if preceding:
            # A following "replay available until" describes the next clock,
            # not the call-start clock immediately before that phrase.
            latest = max(preceding, key=lambda match: match.end())
            return distance(latest) <= 180 and bool(CALL_TIME_CONTEXT_PATTERN.fullmatch(latest.group(0)))
        positive = [distance(match) for match in positive_matches]
        negative = [distance(match) for match in negative_matches]
        if not positive or min(positive) > 180:
            return False
        return not negative or min(positive) < min(negative)

    def _record_parsed_conflict(self, result, event_url):
        days = {value.webcast_date for value in result.candidates}
        self._conflicted_clock_dates.update(days)
        kind = 'start_time_conflict' if len(days) == 1 else 'event_date_conflict'
        self._note_conflict(kind, [{'value': value.scheduled_at_utc.isoformat(),
            'source': event_url, 'event_date': str(value.webcast_date),
            'evidence': value.evidence[:600]} for value in result.candidates])

    def _parse_verified_time(self, page_text, expected_date, event_url, webcast_url, schedule_source):
        try:
            grace = max(0, int(os.getenv('OFFICIAL_EVENT_DATE_GRACE_DAYS','2')))
        except ValueError:
            grace = 2
        result = parse_call_times(page_text, expected_date,
            allow_date_shift=self._identity_allows_shift(self._active_call,page_text,event_url),
            grace_days=grace,
            expected_fiscal_year=self._active_call.get('verified_fiscal_year'),
            expected_fiscal_quarter=self._active_call.get('verified_fiscal_quarter'))
        if result.conflicted:
            self._record_parsed_conflict(result, event_url)
        if result.unavailable_reason in {"cancelled", "postponed", "time_tbd"}:
            self._unavailable_statuses.add(result.unavailable_reason)
        value = result.selected
        if value is None or period_mismatch(self._active_call,value.evidence):
            return None
        return VerifiedScheduleTime(value.webcast_date,value.scheduled_at_utc,value.source_timezone,
                                    event_url,webcast_url,schedule_source,value.evidence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify earnings call times from official IR pages.")
    parser.add_argument("--ticker", help="Verify one upcoming ticker.")
    parser.add_argument("--dry-run", action="store_true", help="Read official pages without saving changes or using search credits.")
    parser.add_argument("--call-json", help="JSON call/list input; avoids all database reads (requires --dry-run).")
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

    if args.call_json:
        if not args.dry_run:
            parser.error('--call-json requires --dry-run')
        calls = json.loads(Path(args.call_json).read_text())
        calls = calls if isinstance(calls, list) else [calls]
    else:
        calls = database.get_calls_missing_verified_time(limit=args.limit, days_ahead=args.days_ahead)
    if args.ticker:
        calls = [call for call in calls if call["ticker"].upper() == args.ticker.upper()]
    if not calls:
        print("No unverified future calls found.")
        return 0

    def verify_one(call: dict[str, Any]) -> tuple[str, VerifiedScheduleTime | None]:
        print(f"[{call['ticker']}] verifying official event time...", flush=True)
        enricher = OfficialScheduleEnricher()
        verified = enricher.verify_call(call, dry_run=True) if args.dry_run else enricher.verify_call(call)
        if args.dry_run:
            print(json.dumps({'ticker': call['ticker'], **enricher.last_dry_run}, default=str), flush=True)
        return str(call["ticker"]), verified

    verified_count = 0
    failed_count = 0
    workers = max(1, min(args.workers, 5))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(verify_one, call):call for call in calls}
        for future in as_completed(futures):
            try:
                ticker, verified = future.result()
            except Exception as exc:
                failed_count += 1
                print(json.dumps({'ticker':futures[future].get('ticker'), 'failed':True,
                                  'error_type':type(exc).__name__}), flush=True)
                continue
            if verified:
                verified_count += 1
                print(
                    f"[{ticker}] verified {verified.scheduled_at_utc.isoformat()} "
                    f"from {verified.event_url}",
                    flush=True,
                )
            else:
                print(f"[{ticker}] no date-matched official time found", flush=True)

    print(f"Verified {verified_count}/{len(calls)} official schedule times; failed={failed_count}.")
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
