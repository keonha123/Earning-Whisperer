from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlparse

import httpx


WEBCAST_TERMS = (
    ("webcast", 70),
    ("listen live", 60),
    ("earnings call", 55),
    ("earnings", 35),
    ("conference call", 35),
    ("audio", 30),
    ("listen", 25),
    ("live", 20),
    ("replay", 10),
    ("presentation", 8),
    ("event", 6),
)
STRONG_WEBCAST_TERMS = ("webcast", "listen", "audio", "conference call", "live")
EVENT_DETAIL_PATH_PATTERN = re.compile(r"/events?(?:[-/]|$)|/event-details?(?:[-/]|$)", re.IGNORECASE)
EVENT_DETAIL_CONTEXT_TERMS = ("earnings", "results", "quarter", "financial")
MEDIA_LINK_PATH_PATTERN = re.compile(
    r"/(?:mediaframe|webcasts?|replay|attendee|static-files|wcc|mmc)(?:/|$)|"
    r"\.(?:m3u8|mpd|mp4|m4a|mp3|aac|wav)(?:$|[?#])",
    re.IGNORECASE,
)
DIRECT_PROVIDER_PATH_PATTERN = re.compile(
    r"/(?:mediaframe|webcasts?|wcc|mmc)(?:/|$)",
    re.IGNORECASE,
)
AUDIO_LINK_PATH_PATTERN = re.compile(
    r"\.(?:m4a|mp3|aac|wav)(?:$|[?#])",
    re.IGNORECASE,
)
NON_PLAYBACK_TERMS = (
    "skip to main",
    "skip to content",
    "calendar",
    "configuration",
    "system test",
    "help",
    "download",
    "copyright",
    "slide",
    "investor presentation",
    "prepared remarks",
    "transcript",
    "press release",
    "event announcement",
    "subscribe",
    "email alert",
    "notify me",
    "add to calendar",
    "privacy preferences",
    "cookie preferences",
    "consent management",
    "open event link",
    "pdf file",
    "financial tables",
    "read more",
    "back to top",
    "presentation mode",
    "investor relations email",
    "podcast",
    "zoom in",
    "zoom out",
)
REPLAY_PROXY_DOCUMENT_PATTERN = re.compile(
    r"\b(?:legal\s+disclaimer|disclaimer|transcript|prepared\s+remarks|"
    r"press\s+release|financial\s+tables?|slides?)\b",
    re.IGNORECASE,
)
REPLAY_AUDIO_DOCUMENT_LABEL_PATTERN = re.compile(
    r"\b(?:listen|replay|on[-\s]?demand|audio\s+recording|stream)\b",
    re.IGNORECASE,
)
NON_PLAYBACK_PATH_SUFFIXES = (".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx")
NON_PLAYBACK_PATH_PATTERN = re.compile(
    r"/news-releases(?:/|$)",
    re.IGNORECASE,
)
EARNINGS_CONTEXT_TERMS = (
    "earnings",
    "financial results",
    "quarterly results",
    "quarterly corporate performance",
    "quarter",
)
QUARTER_RESULTS_PATTERN = re.compile(
    r"\b(?:q[1-4]|[1-4]q|first|second|third|fourth)\b"
    r"[\s\w-]{0,40}\bresults\b",
    re.IGNORECASE,
)
GENERALIZED_ACTION_TERMS = frozenset(
    {"play", "listen", "watch", "start", "unmute", "replay", "webcast", "audio", "join"}
)
GENERALIZED_PATH_TERMS = (
    "/webcast",
    "/webcasts",
    "/replay",
    "/events",
    "/media",
    "/mmc/",
)
REPLAY_TRAINING_TERMS = (
    "webcast",
    "listen",
    "audio",
    "replay",
    "watch",
    "play",
    "webinar",
    "conference",
    "event",
    "presentation",
    "call",
)
REPLAY_NAVIGATION_LABELS = frozenset(
    {
        "events & presentations",
        "events and presentations",
        "news & events",
        "news and events",
        "investor relations",
        "financial information",
        "financial info",
    }
)
GENERALIZED_NON_PLAYBACK_TERMS = (
    "join our team",
    "join us",
    "careers",
    "shop watch",
    "overview",
    "subscribe",
    "email alert",
    "notify me",
    "add to calendar",
    "privacy preferences",
    "cookie preferences",
    "consent management",
    "read more",
    "back to top",
)
HOME_NAVIGATION_LABEL_PATTERN = re.compile(
    r"\b(?:home(?:\s+page)?|link\s+to\s+home|company\s+home)\b",
    re.IGNORECASE,
)
NEWS_ARTICLE_PATH_PATTERN = re.compile(
    r"/(?:news|media|newsroom)/(?:20\d{2}(?:/\d{1,2}){0,2}/)?|"
    r"/regulatory-news/news-details/",
    re.IGNORECASE,
)
REPLAY_LOGIN_PATH_PATTERN = re.compile(
    r"/(?:login|sign[-_]?in|authenticate|authentication|auth)(?:[/?:#]|$)",
    re.IGNORECASE,
)
SEARCH_NAVIGATION_PATH_PATTERN = re.compile(
    r"/(?:search|site[-_]search|search-results?)(?:[/?:#]|$)",
    re.IGNORECASE,
)
SEARCH_NAVIGATION_LABEL_PATTERN = re.compile(
    r"^(?:open\s+)?(?:site\s+)?search(?:\s+(?:this\s+site|form|input|results?))?$",
    re.IGNORECASE,
)
SOCIAL_SHARE_HOST_PATTERN = re.compile(
    r"(?:^|\.)(?:x|twitter|facebook|linkedin)\.com$",
    re.IGNORECASE,
)
SOCIAL_SHARE_PATH_PATTERN = re.compile(
    r"/(?:intent/(?:tweet|post)|share(?:article|this)?|sharer(?:/|$))",
    re.IGNORECASE,
)
SEC_FILING_HOST_PATTERN = re.compile(
    r"(?:^|\.)sec\.gov$",
    re.IGNORECASE,
)
SEC_FILING_PATH_PATTERN = re.compile(
    r"/(?:cgi-bin/(?:browse-edgar|viewer)|archives/|ixviewer/|edgar/)",
    re.IGNORECASE,
)
GENERIC_INFO_PATH_PATTERN = re.compile(
    r"/(?:stock(?:[-_/]quote)?|quote|share[-_/]price|portfolio)(?:[./_?-]|$)",
    re.IGNORECASE,
)
GENERIC_INFO_LABEL_PATTERN = re.compile(
    r"^(?:see here|click here|learn more|more)$",
    re.IGNORECASE,
)
UPCOMING_SCHEDULE_PATH_PATTERN = re.compile(
    r"/(?:upcoming|future)(?:[-_/](?:earnings|events?|webcasts?|calls?))?"
    r"(?:[/?:#]|$)|/(?:earnings|events?)[-_/](?:calendar|upcoming)(?:[/?:#]|$)",
    re.IGNORECASE,
)
UPCOMING_SCHEDULE_LABEL_PATTERN = re.compile(
    r"\b(?:upcoming|future)\s+(?:earnings|events?|webcasts?|conference\s+calls?)\b",
    re.IGNORECASE,
)
REPLAY_ARCHIVE_PRESENTATIONS_PATH_PATTERN = re.compile(
    r"/(?:news[-/]events/presentations|events?[-/]and[-/]presentations|"
    r"events?[-/]presentations)"
    r"(?:[/?:#]|$)",
    re.IGNORECASE,
)
REPLAY_INDEX_PATH_PATTERN = re.compile(
    r"/(?:rss|feed)(?:/|$)|"
    r"/(?:news[-/]events/events|events?[-/]and[-/]presentations|"
    r"events?[-/]presentations|event[-/]and[-/]presentations|"
    r"events?|event[-/]calendar|calendar[-/]of[-/]events|"
    r"ir[-/]calendar|resources?(?:/contacts?)?|"
    r"contact(?:-us)?|about(?:-us)?|company(?:/information)?|"
    r"investor[-/]relations)(?:/)?$",
    re.IGNORECASE,
)
NON_REPLAY_CONTENT_PATH_PATTERN = re.compile(
    r"/(?:what[-_]we[-_]do|insights?/podcasts?|podcasts?|"
    r"client[-_]success(?:[-_]stories)?|careers?|about(?:-us)?|"
    r"corporate[-_]governance|governance|board[-_]of[-_]directors|"
    r"disclaimers?)(?:[/?:#]|$)",
    re.IGNORECASE,
)
REPLAY_NAVIGATION_LABEL_PATTERN = re.compile(
    r"^(?:events?|rss(?:\s+news\s+feed)?|news(?:\s+and\s+events)?|"
    r"events?\s*(?:&|and)\s*presentations|investor relations)$",
    re.IGNORECASE,
)
NON_REPLAY_UTILITY_LABEL_PATTERN = re.compile(
    r"^(?:advertising\s+opportunities?|media\s+kit|"
    r"(?:investor\s+)?contact(?:\s+us)?|email\s+alerts?|"
    r"analyst\s+coverage|stock\s+quote|audio\s+and\s+radio)$",
    re.IGNORECASE,
)
REPLAY_EXPLICIT_PLAYBACK_LABEL_PATTERN = re.compile(
    r"\b(?:webcast|replay|listen|watch|play|audio|video|webinar|podcast|stream)\b",
    re.IGNORECASE,
)
EVENT_ANNOUNCEMENT_PATTERN = re.compile(
    r"\b(?:to|will)\s+(?:host|hold|conduct|present)\b|"
    r"\b(?:announces?|announced|schedules?|scheduled)\b[\s\S]{0,100}"
    r"\b(?:earnings|conference\s+call|webcast)\b|"
    r"\b(?:invites?|invited)\b[\s\S]{0,80}\b(?:join|listen|view|webcast)\b",
    re.IGNORECASE,
)
REPLAY_COMPLETION_EVIDENCE_PATTERN = re.compile(
    r"\b(?:replay|transcript|audio(?:\s+recording)?)\b",
    re.IGNORECASE,
)
EXPLICIT_PLAYBACK_LABEL_PATTERN = re.compile(
    r"\b(?:webcast|listen|audio|replay|watch|play|video)\b",
    re.IGNORECASE,
)
QUARTER_ALIASES = {
    "q1": ("q1", "1q", "first quarter", "1st quarter"),
    "q2": ("q2", "2q", "second quarter", "2nd quarter"),
    "q3": ("q3", "3q", "third quarter", "3rd quarter"),
    "q4": ("q4", "4q", "fourth quarter", "4th quarter"),
}
EVENT_DATE_PATTERN = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(20\d{2})\b",
    re.IGNORECASE,
)
DAY_FIRST_EVENT_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
    r"January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    r")\.?,?\s+(20\d{2})\b",
    re.IGNORECASE,
)
NUMERIC_EVENT_DATE_PATTERN = re.compile(
    r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](20\d{2})\b"
)
SHORT_NUMERIC_EVENT_DATE_PATTERN = re.compile(
    r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](\d{2})\b"
)
ISO_EVENT_DATE_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])(?!\d)"
)
COMPACT_EVENT_DATE_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"
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


@dataclass(frozen=True)
class WebcastCandidate:
    candidate_id: str
    selectors: tuple[str, ...]
    frame_hostname: str | None
    text: str
    aria_label: str
    title: str
    href_path: str | None
    tag_name: str
    rect: dict[str, float]
    in_navigation: bool = False
    context_text: str = ""
    metadata_text: str = ""
    href: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WebcastCandidate":
        return cls(
            candidate_id=str(value["candidate_id"]),
            selectors=tuple(str(selector) for selector in value.get("selectors", []) if selector),
            frame_hostname=value.get("frame_hostname") or None,
            text=str(value.get("text") or ""),
            aria_label=str(value.get("aria_label") or ""),
            title=str(value.get("title") or ""),
            href_path=value.get("href_path") or None,
            tag_name=str(value.get("tag_name") or ""),
            rect={key: float(number) for key, number in (value.get("rect") or {}).items()},
            in_navigation=bool(value.get("in_navigation")),
            context_text=str(value.get("context_text") or ""),
            metadata_text=str(value.get("metadata_text") or ""),
            href=str(value.get("href") or "") or None,
        )

    def prompt_value(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "selectors": list(self.selectors),
            "text": self.text,
            "aria_label": self.aria_label,
            "title": self.title,
            "href_path": self.href_path,
            "href": self.href,
            "tag_name": self.tag_name,
            "rect": self.rect,
            "in_navigation": self.in_navigation,
            "context_text": self.context_text,
            "metadata_text": self.metadata_text,
        }


FRESHNESS_METADATA_PATTERN = re.compile(
    r"\bdata-(?:updated|published|last-modified)=([^\s]+)",
    re.IGNORECASE,
)


def candidate_evidence(candidate: WebcastCandidate, *, include_selectors: bool = False) -> str:
    """Build the date/status evidence used for live candidate ranking."""
    values = (
        candidate.text,
        candidate.aria_label,
        candidate.title,
        candidate.href_path or "",
        candidate.context_text,
        candidate.metadata_text,
        " ".join(candidate.selectors) if include_selectors else "",
    )
    return " ".join(value for value in values if value)


def candidate_event_evidence(
    candidate: WebcastCandidate,
    *,
    include_selectors: bool = False,
) -> str:
    """Return event identity evidence without unrelated page freshness dates."""
    metadata = FRESHNESS_METADATA_PATTERN.sub("", candidate.metadata_text)
    values = (
        candidate.text,
        candidate.aria_label,
        candidate.title,
        candidate.href_path or "",
        candidate.context_text,
        metadata,
        " ".join(candidate.selectors) if include_selectors else "",
    )
    return " ".join(value for value in values if value)


@dataclass
class WebcastRecipe:
    domain: str
    selectors: tuple[str, ...]
    frame_hostname: str | None
    target_text: str
    target_href_path: str | None
    strategy: str
    lifecycle: str
    confidence: float
    evidence: dict[str, Any]
    stage: str = "playback"
    recipe_id: int | None = None

    @property
    def recipe_key(self) -> str:
        return recipe_key(
            self.domain,
            self.selectors,
            self.frame_hostname,
            self.lifecycle,
            self.stage,
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "WebcastRecipe":
        selectors = _json_list(record.get("selector_json"))
        evidence = _json_object(record.get("evidence_json"))
        stage = str(evidence.get("workflow_stage") or evidence.get("stage") or "playback")
        return cls(
            recipe_id=int(record["id"]),
            domain=str(record["domain"]),
            selectors=tuple(selectors),
            frame_hostname=record.get("frame_hostname") or None,
            target_text=str(record.get("target_text") or ""),
            target_href_path=record.get("target_href_path") or None,
            strategy=str(record.get("strategy") or "recipe"),
            lifecycle=str(record.get("lifecycle") or "unknown"),
            confidence=float(record.get("confidence") or 0),
            evidence=evidence,
            stage=stage,
        )

    def database_value(self) -> dict[str, Any]:
        return {
            "recipe_key": self.recipe_key,
            "domain": self.domain,
            "selector_json": json.dumps(list(self.selectors), ensure_ascii=True),
            "frame_hostname": self.frame_hostname,
            "target_text": self.target_text[:500],
            "target_href_path": self.target_href_path,
            "strategy": self.strategy,
            "lifecycle": self.lifecycle,
            "confidence": self.confidence,
            "evidence_json": json.dumps(self.evidence, ensure_ascii=True),
        }


@dataclass(frozen=True)
class VisionSelection:
    candidate_id: str
    confidence: float
    reason: str
    x: float = 0
    y: float = 0


@dataclass(frozen=True)
class LearningSnapshot:
    screenshot_path: Path
    candidates_path: Path
    candidates: tuple[WebcastCandidate, ...]


@dataclass(frozen=True)
class GeneralizedWebcastPattern:
    """Cross-domain evidence extracted from an audio-verified recipe."""

    action_tokens: frozenset[str]
    href_tokens: frozenset[str]
    success_count: int = 1


def _generalized_tokens(value: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (value or "").lower())
    return frozenset(word for word in words if len(word) > 2)


def make_generalized_patterns(records: Iterable[dict[str, Any]]) -> tuple[GeneralizedWebcastPattern, ...]:
    patterns: list[GeneralizedWebcastPattern] = []
    for record in records:
        target_text = str(record.get("target_text") or "")
        target_href = str(record.get("target_href_path") or "")
        action_tokens = _generalized_tokens(target_text) & GENERALIZED_ACTION_TERMS
        if not action_tokens:
            continue
        patterns.append(
            GeneralizedWebcastPattern(
                action_tokens=action_tokens,
                href_tokens=_generalized_tokens(target_href),
                success_count=max(1, int(record.get("success_count") or 1)),
            )
        )
    return tuple(patterns)


def generalized_candidate_bonus(
    candidate: WebcastCandidate,
    patterns: Iterable[GeneralizedWebcastPattern],
) -> int:
    """Score reusable action evidence without copying another site's selectors."""
    candidate_label = " ".join(
        value for value in (candidate.text, candidate.aria_label, candidate.title) if value
    )
    candidate_actions = _generalized_tokens(candidate_label) & GENERALIZED_ACTION_TERMS
    if not candidate_actions:
        return 0

    candidate_href = (candidate.href_path or "").lower()
    best_bonus = 0
    for pattern in patterns:
        overlap = len(candidate_actions & pattern.action_tokens)
        if overlap == 0 and not candidate_actions.intersection(GENERALIZED_ACTION_TERMS):
            continue
        bonus = (12 if overlap else 8) + min(12, pattern.success_count * 2)
        if candidate_actions == pattern.action_tokens:
            bonus += 10
        if any(term in candidate_href for term in GENERALIZED_PATH_TERMS):
            bonus += 4
        best_bonus = max(best_bonus, bonus)
    return best_bonus


def has_earnings_context(text: str) -> bool:
    normalized = (text or "").lower()
    return any(term in normalized for term in EARNINGS_CONTEXT_TERMS) or bool(
        QUARTER_RESULTS_PATTERN.search(normalized)
    )


def _candidate_period_mismatch(
    candidate: WebcastCandidate,
    *,
    target_year: int | None,
    target_quarter: str | None,
) -> bool:
    """Reject an explicitly different quarter while keeping generic replay links."""
    if target_year is None and not target_quarter:
        return False
    label = candidate_event_evidence(candidate).lower()
    years = set(re.findall(r"\b20\d{2}\b", label))
    if target_year is not None and years and str(target_year) not in years:
        return True
    normalized_quarter = (target_quarter or "").lower().replace(" ", "")
    target_key = next(
        (key for key, aliases in QUARTER_ALIASES.items() if normalized_quarter in aliases),
        normalized_quarter if normalized_quarter in QUARTER_ALIASES else "",
    )
    if not target_key:
        return False
    explicit_quarters = {
        key
        for key, aliases in QUARTER_ALIASES.items()
        if any(alias in label for alias in aliases)
    }
    return bool(explicit_quarters and target_key not in explicit_quarters)


def candidate_identity_mismatch(
    candidate: WebcastCandidate,
    *,
    target_ticker: str | None = None,
    target_year: int | None = None,
    target_quarter: str | None = None,
    target_date: date | None = None,
    target_time_utc: datetime | None = None,
) -> str | None:
    """Explain why explicit candidate evidence contradicts the target call.

    Generic archive links are intentionally allowed because many IR pages omit
    the date or period from the link itself. Only explicit contradictory
    evidence causes rejection.
    """
    evidence = event_identity_text(candidate_event_evidence(candidate))
    from ..schedules.call_times import parse_call_times
    call_clock = parse_call_times(evidence, target_date, grace_days=0) if target_date else None
    if target_ticker:
        explicit_tickers = {
            match.group(1).upper()
            for match in re.finditer(
                r"\b(?:(?:ticker|symbol)\s*[:#]?|stock\s+ticker\s*[:#]?)\s*"
                r"\$?([A-Z][A-Z0-9.-]{0,5})\b",
                evidence,
                re.IGNORECASE,
            )
        }
        if explicit_tickers and target_ticker.upper() not in explicit_tickers:
            return "candidate ticker contradicts target call"
    if target_date is not None:
        event_date = (call_clock.selected.webcast_date if call_clock.selected
                      else event_date_from_text(event_identity_text(evidence)))
        if event_date and event_date != target_date:
            return (
                f"candidate date {event_date.isoformat()} != "
                f"target {target_date.isoformat()}"
            )
    if target_time_utc is not None:
        if call_clock and (call_clock.conflicted or call_clock.unavailable_reason):
            return "candidate call start time is ambiguous or unavailable"
        # Only a scoped call clock may contradict an exact live schedule.
        # The first printed clock may instead publish a release/prepared remarks.
        # Replay callers without an event day retain their legacy behaviour.
        event_datetime = (call_clock.selected.scheduled_at_utc if call_clock and call_clock.selected
                          else None if target_date else event_datetime_from_text(evidence))
        if event_datetime is not None:
            comparison_target = (
                target_time_utc.replace(tzinfo=timezone.utc)
                if target_time_utc.tzinfo is None
                else target_time_utc.astimezone(timezone.utc)
            )
            if abs(event_datetime.astimezone(timezone.utc) - comparison_target) > timedelta(
                hours=2
            ):
                return "candidate start time contradicts target call"
    if _candidate_period_mismatch(
        candidate,
        target_year=target_year,
        target_quarter=target_quarter,
    ):
        return "candidate year or quarter contradicts target call"
    return None


LIVE_EVENT_IDENTITY_PATTERN = re.compile(
    r"\b(?:earnings(?:\s+(?:call|conference|webcast|release))?|"
    r"financial\s+(?:results?|(?:conference\s+)?call)|quarter(?:ly)?\s+results?|"
    r"results?\s+(?:call|conference|webcast)|conference\s+call|"
    r"(?:live\s+)?(?:Q\s*&\s*A|questions?[-\s]+and[-\s]+answers?)\s+(?:session|call))\b",
    re.IGNORECASE,
)


def non_primary_live_event_reason(evidence: str) -> str | None:
    """Classify an event-local title using the schedule's shared event types."""
    from ..schedules.call_times import NON_EARNINGS_EVENT_RE
    match = NON_EARNINGS_EVENT_RE.search(event_identity_text(str(evidence or "")))
    return f"non-primary event: {match.group(0)}" if match else None


def live_candidate_event_type_mismatch(candidate: WebcastCandidate) -> str | None:
    """An analyst-only follow-up cannot inherit the main call's nearby title."""
    label = " ".join(value for value in (
        candidate.text, candidate.aria_label, candidate.title,
    ) if value)
    rejection = non_primary_live_event_reason(label)
    if rejection:
        return rejection
    # A generic Play/Webcast control gets its event type from its own card.
    # An explicit primary title need not inherit an adjacent event mention.
    if not LIVE_EVENT_IDENTITY_PATTERN.search(label):
        return non_primary_live_event_reason(candidate.context_text)
    return None


def live_event_identity_confirmation(
    evidence: str,
    *,
    target_date: date | None,
    target_time_utc: datetime | None = None,
) -> str | None:
    """Return positive evidence that a live surface belongs to the target call.

    Absence of a contradiction is not confirmation. Live monitoring must see
    the scheduled date beside earnings/call context before it may enter an
    otherwise generic player route. A pre-resolved official URL can be trusted
    separately by the caller.
    """
    if target_date is None:
        return None
    normalized = event_identity_text(" ".join(str(evidence or "").split()))
    if not normalized or not LIVE_EVENT_IDENTITY_PATTERN.search(normalized):
        return None
    from ..schedules.call_times import parse_call_times, _non_earnings_event
    if _non_earnings_event(normalized):
        return None
    call_clock = parse_call_times(normalized, target_date, grace_days=0)
    if call_clock.conflicted or call_clock.unavailable_reason:
        return None
    event_date = (call_clock.selected.webcast_date if call_clock.selected
                  else event_date_from_text(normalized))
    if event_date != target_date:
        return None

    if target_time_utc is not None:
        event_datetime = call_clock.selected.scheduled_at_utc if call_clock.selected else None
        if event_datetime is not None:
            comparison_target = (
                target_time_utc.replace(tzinfo=timezone.utc)
                if target_time_utc.tzinfo is None
                else target_time_utc.astimezone(timezone.utc)
            )
            if abs(
                event_datetime.astimezone(timezone.utc) - comparison_target
            ) > timedelta(hours=2):
                return None
            return "target date and start time matched"
    return "target date and earnings context matched"


def live_candidate_identity_confirmation(
    candidate: WebcastCandidate,
    *,
    target_ticker: str | None = None,
    target_date: date | None,
    target_time_utc: datetime | None = None,
) -> str | None:
    """Confirm a live candidate using positive, event-local identity evidence."""
    if live_candidate_event_type_mismatch(candidate):
        return None
    mismatch = candidate_identity_mismatch(
        candidate,
        target_ticker=target_ticker,
        # ``call_year`` and ``quarter`` are calendar values in our schedule
        # table, while issuer labels commonly use a different fiscal period.
        # The exact issuer-local date is the reliable live identity here.
        target_year=None,
        target_quarter=None,
        target_date=target_date,
        target_time_utc=target_time_utc,
    )
    if mismatch:
        return None
    return live_event_identity_confirmation(
        candidate_event_evidence(candidate, include_selectors=True),
        target_date=target_date,
        target_time_utc=target_time_utc,
    )


_EVENT_TIME_PATTERN = re.compile(
    r"\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<ampm>a\.?m\.?|p\.?m\.?)\s*(?P<zone>ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|UTC|GMT)?\b",
    re.IGNORECASE,
)
_EVENT_TIME_ZONES = {
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "utc": "UTC",
    "gmt": "UTC",
}


def event_datetime_from_text(
    text: str,
    *,
    default_date: date | None = None,
) -> datetime | None:
    """Parse the first timezone-qualified event start time from evidence."""
    match = _EVENT_TIME_PATTERN.search(text or "")
    if not match or not match.group("zone"):
        return None
    try:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        ampm = match.group("ampm").lower().replace(".", "")
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        parsed_time = time(hour, minute)
    except ValueError:
        return None
    event_date = event_date_from_text(text) or default_date
    if event_date is None:
        return None
    zone_name = _EVENT_TIME_ZONES.get(match.group("zone").lower())
    if not zone_name:
        return None
    from zoneinfo import ZoneInfo

    return datetime.combine(event_date, parsed_time, tzinfo=ZoneInfo(zone_name))


def future_event_start_utc(
    text: str,
    *,
    reference_time_utc: datetime | None = None,
    early_entry_minutes: int = 5,
    default_date: date | None = None,
) -> datetime | None:
    """Return a timezone-qualified event start that is still outside its entry window."""
    event_start = event_datetime_from_text(text, default_date=default_date)
    if event_start is None:
        return None
    event_start_utc = event_start.astimezone(timezone.utc)
    reference = reference_time_utc or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    else:
        reference = reference.astimezone(timezone.utc)
    entry_time = event_start_utc - timedelta(minutes=max(0, int(early_entry_minutes)))
    return event_start_utc if reference < entry_time else None


def event_identity_text(text: str) -> str:
    """Exclude labelled financial/publication/expiry dates from live identity.

    Historical archive ranking still uses the latest date; live identity must not
    mistake a quarter end, recording expiry or article update for the call.
    Ambiguous, unlabelled dates remain strict rather than guessing a target.
    """
    from ..schedules.event_dates import mask_non_event_dates
    return mask_non_event_dates(text)


def event_date_from_text(text: str) -> date | None:
    """Extract the latest explicit date from event text or a dated URL."""
    dates: list[date] = []

    for match in EVENT_DATE_PATTERN.finditer(text):
        try:
            dates.append(
                date(
                    int(match.group(3)),
                    MONTH_NUMBERS[match.group(1)[:3].lower()],
                    int(match.group(2)),
                )
            )
        except (KeyError, ValueError):
            continue

    for match in DAY_FIRST_EVENT_DATE_PATTERN.finditer(text):
        try:
            dates.append(
                date(
                    int(match.group(3)),
                    MONTH_NUMBERS[match.group(2)[:3].lower()],
                    int(match.group(1)),
                )
            )
        except (KeyError, ValueError):
            continue

    for pattern, year_index, month_index, day_index, short_year in (
        (NUMERIC_EVENT_DATE_PATTERN, 3, 1, 2, False),
        (SHORT_NUMERIC_EVENT_DATE_PATTERN, 3, 1, 2, True),
        (ISO_EVENT_DATE_PATTERN, 1, 2, 3, False),
        (COMPACT_EVENT_DATE_PATTERN, 1, 2, 3, False),
    ):
        for match in pattern.finditer(text):
            try:
                year = int(match.group(year_index))
                if short_year:
                    year += 2000
                dates.append(
                    date(
                        year,
                        int(match.group(month_index)),
                        int(match.group(day_index)),
                    )
                )
            except ValueError:
                continue

    return max(dates) if dates else None


def replay_candidate_rejection_reason(
    text: str,
    href_path: str | None,
    *,
    reference_date: date | None = None,
    minimum_age_days: int = 2,
) -> str | None:
    """Reject future, stale-auth, and announcement-only replay candidates."""
    reference_date = reference_date or datetime.now(timezone.utc).date()
    evidence = " ".join(value for value in (text, href_path or "") if value)
    normalized_href = (href_path or "").lower()
    if REPLAY_LOGIN_PATH_PATTERN.search(normalized_href):
        return "replay candidate points to an authentication surface"

    # A scheduled/tentative row is useful for live monitoring, but it is not a
    # replay training surface. This also catches providers that omit the date
    # from the anchor context and expose only a label such as "(tentative)".
    if re.search(
        r"\b(?:tentative|preliminary|estimated|subject\s+to\s+change|tba)\b",
        evidence,
        re.IGNORECASE,
    ) and re.search(
        r"\b(?:earnings|conference\s+call|webcast|financial\s+results)\b",
        evidence,
        re.IGNORECASE,
    ):
        return "event is tentative and cannot train replay playback"

    future_years = {
        int(value)
        for value in re.findall(r"\b20\d{2}\b", evidence)
        if int(value) > reference_date.year
    }
    direct_provider_playback = bool(
        DIRECT_PROVIDER_PATH_PATTERN.search(normalized_href)
        and REPLAY_EXPLICIT_PLAYBACK_LABEL_PATTERN.search(evidence)
    )
    if future_years and re.search(
        r"\b(?:earnings|conference\s+call|webcast|financial\s+results)\b",
        evidence,
        re.IGNORECASE,
    ) and not direct_provider_playback:
        return f"event year {min(future_years)} is in the future"

    event_date = event_date_from_text(evidence)
    cutoff = reference_date - timedelta(days=max(0, minimum_age_days))
    if event_date and event_date > cutoff and not direct_provider_playback:
        return (
            f"event date {event_date.isoformat()} is newer than "
            f"replay cutoff {cutoff.isoformat()}"
        )

    if (
        NEWS_ARTICLE_PATH_PATTERN.search(normalized_href)
        and EVENT_ANNOUNCEMENT_PATTERN.search(text)
        and not MEDIA_LINK_PATH_PATTERN.search(normalized_href)
    ):
        return "event announcement is not a playback surface"
    if (
        EVENT_ANNOUNCEMENT_PATTERN.search(text)
        and not MEDIA_LINK_PATH_PATTERN.search(normalized_href)
        and not EVENT_DETAIL_PATH_PATTERN.search(normalized_href)
    ):
        return "event announcement is not a playback surface"
    return None


def is_news_article_without_playback_label(label: str, href: str | None) -> bool:
    """Keep generic news articles out unless their own label is playable."""
    return bool(
        NEWS_ARTICLE_PATH_PATTERN.search(str(href or ""))
        and not EXPLICIT_PLAYBACK_LABEL_PATTERN.search(str(label or ""))
    )


def _redirect_target_url(url: str) -> str | None:
    """Read a safe, explicit target from common tracking redirect parameters."""
    parsed = urlparse(str(url or ""))
    if not parsed.query:
        return None
    values = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("url", "u", "target", "dest", "destination", "redirect", "redirect_url"):
        for value in values.get(key, ()):
            target = unquote(str(value or "")).strip()
            target_parsed = urlparse(target)
            if target_parsed.scheme in {"http", "https"} and target_parsed.netloc:
                return target
    return None


def is_non_replay_navigation_link(url: str, label: str = "") -> bool:
    """Reject navigation/redirect links that cannot be a replay surface.

    Historical training may use an arbitrary webcast-like event, but it still
    needs an event detail page, provider page, or media URL. RSS feeds, archive
    index tabs, company home links, and tracking redirects to those pages are
    not useful downstream surfaces and should not shadow a real event link.
    """
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return False
    parsed = urlparse(normalized_url)
    path = parsed.path.rstrip("/")
    normalized_label = " ".join(str(label or "").split())
    explicit_playback = bool(REPLAY_EXPLICIT_PLAYBACK_LABEL_PATTERN.search(normalized_label))

    redirect_target = _redirect_target_url(normalized_url)
    if redirect_target and redirect_target != normalized_url:
        # Keep a tracking URL only when it explicitly wraps a usable playback
        # surface. This avoids following Business Wire smartlinks to a company
        # homepage while preserving a smartlink that really targets a player.
        return is_non_replay_navigation_link(redirect_target, normalized_label)
    host = (parsed.hostname or "").lower()
    decoded_query = unquote(parsed.query).lower()
    if SEARCH_NAVIGATION_LABEL_PATTERN.fullmatch(normalized_label):
        return True
    if NON_REPLAY_UTILITY_LABEL_PATTERN.fullmatch(normalized_label):
        return True
    if SEARCH_NAVIGATION_PATH_PATTERN.search(path) and not explicit_playback:
        return True
    if SOCIAL_SHARE_PATH_PATTERN.search(path) or re.search(
        r"(?:intent/tweet|sharearticle|sharer)", decoded_query
    ):
        return True
    # SEC filing/search pages are useful source material for the data layer,
    # but they are never a browser playback surface. Without this guard a
    # generic "SEC filings" link can outrank an actual event link on IR pages.
    if SEC_FILING_HOST_PATTERN.search(host) and SEC_FILING_PATH_PATTERN.search(path):
        return True
    if GENERIC_INFO_PATH_PATTERN.search(path) and (
        not explicit_playback or GENERIC_INFO_LABEL_PATTERN.fullmatch(normalized_label)
    ):
        return True
    # "Listen" is a valid webcast action, but company podcast hubs are
    # ordinary content navigation and do not provide a replay surface for
    # this pipeline. Keep an explicit earnings/webcast label eligible.
    if re.search(r"\bpodcasts?\b", normalized_label, re.IGNORECASE) and not re.search(
        r"\b(?:earnings|webcast|replay|conference\s+call)\b",
        normalized_label,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"/(?:podcasts?|audio-series)(?:[/?:#]|$)", path, re.IGNORECASE) and not re.search(
        r"\b(?:earnings|webcast|replay|conference\s+call)\b",
        normalized_label,
        re.IGNORECASE,
    ):
        return True
    # A schedule/index page is useful to the live monitor, but it cannot feed
    # replay training. Do not let a phrase such as "Upcoming Earnings" become
    # the downstream player candidate after an archive fallback.
    if not explicit_playback and (
        UPCOMING_SCHEDULE_PATH_PATTERN.search(path)
        or UPCOMING_SCHEDULE_LABEL_PATTERN.search(normalized_label)
    ):
        return True
    if host == "cts.businesswire.com" or host.endswith(".cts.businesswire.com"):
        return True
    if NON_REPLAY_CONTENT_PATH_PATTERN.search(path) and not re.search(
        r"\b(?:earnings|webcast|replay|conference\s+call)\b",
        normalized_label,
        re.IGNORECASE,
    ):
        return True
    if (
        re.search(r"/(?:tools?/)?viewpdf(?:\.aspx)?(?:/|$)", path, re.IGNORECASE)
        or path.endswith(NON_PLAYBACK_PATH_SUFFIXES)
    ) and not explicit_playback:
        return True
    query_keys = set(parse_qs(parsed.query, keep_blank_values=False))
    dated_event_query = bool(
        query_keys.intersection(
            {"item", "event", "eventid", "event_id", "session", "sessionid", "id"}
        )
    )
    if REPLAY_INDEX_PATH_PATTERN.search(path) and not explicit_playback and not dated_event_query:
        return True
    if not path and not explicit_playback:
        return True
    if REPLAY_NAVIGATION_LABEL_PATTERN.fullmatch(normalized_label) and not explicit_playback:
        return True
    return False


def is_dated_earnings_news_article(
    candidate: WebcastCandidate,
    *,
    reference_date: date | None = None,
    minimum_age_days: int = 2,
) -> bool:
    """Allow an old earnings article to act as a discovery page.

    Some IR sites publish the historical webcast link only inside a dated
    earnings article. The article is not itself a playback surface, but it is
    a valid intermediate page for replay training when it is old enough and
    clearly tied to earnings/results.
    """
    reference_date = reference_date or datetime.now(timezone.utc).date()
    href = str(candidate.href_path or "").lower()
    if candidate.tag_name != "a" or not NEWS_ARTICLE_PATH_PATTERN.search(href):
        return False
    evidence = " ".join(
        value
        for value in (
            candidate.text,
            candidate.aria_label,
            candidate.title,
            candidate.context_text,
            href,
        )
        if value
    )
    event_date = event_date_from_text(evidence)
    cutoff = reference_date - timedelta(days=max(0, minimum_age_days))
    return bool(
        event_date
        and event_date <= cutoff
        and has_earnings_context(evidence)
        and not EVENT_ANNOUNCEMENT_PATTERN.search(evidence)
        and re.search(
            r"\b(?:earnings|results|financial\s+results|conference\s+call)\b",
            evidence,
            re.IGNORECASE,
        )
    )


def candidate_event_date(candidate: WebcastCandidate, *, live_identity: bool = False) -> date | None:
    """Extract a calendar date, excluding labelled non-event dates for live use."""
    evidence = candidate_event_evidence(candidate, include_selectors=True)
    return event_date_from_text(event_identity_text(evidence) if live_identity else evidence)


def domain_for_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def recipe_key(
    domain: str,
    selectors: tuple[str, ...],
    frame_hostname: str | None,
    lifecycle: str = "unknown",
    stage: str = "playback",
) -> str:
    parts = [domain.lower(), lifecycle.lower()]
    # Preserve keys written by older playback-only versions. Stage identity is
    # only needed for the new independently verified workflow segments.
    if stage.lower() != "playback":
        parts.append(stage.lower())
    parts.extend([frame_hostname or "", *selectors])
    source = "\n".join(parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def live_candidate_match_score(
    candidate: WebcastCandidate,
    *,
    target_date: date | None = None,
    target_time_utc: datetime | None = None,
) -> int:
    """Score dated and newly activated webcast evidence for a live probe.

    A live IR page can expose several old replays, an upcoming call, and a
    generic event index at the same time. The score intentionally rewards
    issuer-provided date/time/status metadata while keeping generic webcast
    links usable until a more specific candidate appears.
    """
    evidence = event_identity_text(candidate_event_evidence(candidate, include_selectors=True))
    normalized = evidence.lower()
    metadata = candidate.metadata_text.lower()
    score = 0

    event_date = event_date_from_text(evidence)
    if target_date and event_date:
        if event_date == target_date:
            score += 90
        else:
            score -= 180

    if target_time_utc is not None:
        event_time = event_datetime_from_text(evidence, default_date=target_date)
        if event_time is not None:
            expected = (
                target_time_utc.replace(tzinfo=timezone.utc)
                if target_time_utc.tzinfo is None
                else target_time_utc.astimezone(timezone.utc)
            )
            difference_minutes = abs(
                (event_time.astimezone(timezone.utc) - expected).total_seconds()
            ) / 60
            if difference_minutes <= 10:
                score += 70
            elif difference_minutes <= 30:
                score += 55
            elif difference_minutes <= 90:
                score += 35
            elif difference_minutes <= 120:
                score += 15
            else:
                score -= 140

    if re.search(
        r"(?:data-(?:live|status|state)|aria-live|status|state)\s*[:=]\s*"
        r"(?:true|live|upcoming|scheduled|open|active)",
        metadata,
    ):
        score += 45
    if re.search(r"\b(?:live\s+(?:webcast|event|audio)|join\s+live|watch\s+live)\b", normalized):
        score += 35
    if re.search(r"\b(?:upcoming|scheduled|registration\s+open|register\s+now)\b", normalized):
        score += 16
    freshness_matches = FRESHNESS_METADATA_PATTERN.findall(metadata)
    freshness_dates: list[date] = []
    for raw_value in freshness_matches:
        raw_value = raw_value.strip().rstrip(".,;)")
        try:
            freshness_dates.append(
                datetime.fromisoformat(raw_value.replace("Z", "+00:00")).date()
            )
        except ValueError:
            try:
                freshness_dates.append(date.fromisoformat(raw_value[:10]))
            except ValueError:
                continue
    if freshness_dates:
        freshest = max(freshness_dates)
        if target_date is not None:
            days_before_target = (target_date - freshest).days
            if -1 <= days_before_target <= 14:
                score += 14
            elif -14 <= days_before_target <= 30:
                score += 6
        else:
            age_days = (datetime.now(timezone.utc).date() - freshest).days
            if 0 <= age_days <= 2:
                score += 12
            elif 0 <= age_days <= 7:
                score += 6
    elif re.search(r"(?:data-(?:updated|published|modified)|datetime)\s*[:=]", metadata):
        score += 4
    if has_earnings_context(evidence):
        score += 18
    if DIRECT_PROVIDER_PATH_PATTERN.search(candidate.href_path or ""):
        score += 12
    return score


def choose_heuristic_candidate(
    candidates: list[WebcastCandidate],
    generalized_patterns: Iterable[GeneralizedWebcastPattern] = (),
    *,
    lifecycle: str = "unknown",
    target_year: int | None = None,
    target_quarter: str | None = None,
    target_date: date | None = None,
    target_time_utc: datetime | None = None,
    reference_date: date | None = None,
    replay_minimum_age_days: int = 2,
) -> WebcastCandidate | None:
    generalized_patterns = tuple(generalized_patterns)
    reference_date = reference_date or datetime.now(timezone.utc).date()
    # Schedule rows store calendar year/quarter, while an issuer can label the
    # same exact date as a different fiscal year or quarter. Date/time evidence
    # is authoritative in live mode; period labels remain useful for replay.
    period_target_year = None if lifecycle == "live" else target_year
    period_target_quarter = None if lifecycle == "live" else target_quarter
    scored: list[tuple[int, int, int, int, WebcastCandidate]] = []
    for index, candidate in enumerate(candidates):
        if not candidate.selectors:
            continue
        if lifecycle == "live" and live_candidate_event_type_mismatch(candidate):
            continue
        action_haystack = " ".join(
            value
            for value in (
                candidate.text,
                candidate.aria_label,
                candidate.title,
                candidate.href_path or "",
            )
            if value
        ).lower()
        haystack = " ".join(
            value
            for value in (
                action_haystack,
                candidate.context_text,
                " ".join(candidate.selectors),
            )
            if value
        ).lower()
        visible_label = " ".join(
            value for value in (candidate.text, candidate.aria_label, candidate.title) if value
        ).lower()
        label_has_strong_term = any(
            term in visible_label for term in STRONG_WEBCAST_TERMS
        )
        if _candidate_period_mismatch(
            candidate,
            target_year=period_target_year,
            target_quarter=period_target_quarter,
        ):
            continue
        if lifecycle == "replay" and replay_candidate_rejection_reason(
            haystack,
            candidate.href_path,
            reference_date=reference_date,
            minimum_age_days=replay_minimum_age_days,
        ):
            continue
        event_date = candidate_event_date(candidate, live_identity=lifecycle == "live")
        href_path = (candidate.href_path or "").lower()
        if NEWS_ARTICLE_PATH_PATTERN.search(href_path) and not label_has_strong_term:
            continue
        event_detail_link = bool(EVENT_DETAIL_PATH_PATTERN.search(href_path)) and any(
            term in haystack for term in EVENT_DETAIL_CONTEXT_TERMS
        )
        if any(term in visible_label for term in NON_PLAYBACK_TERMS):
            continue
        if lifecycle == "replay" and any(
            term in visible_label for term in ("register", "registration")
        ):
            continue
        if href_path.split("?", maxsplit=1)[0].endswith(NON_PLAYBACK_PATH_SUFFIXES):
            continue
        if NON_PLAYBACK_PATH_PATTERN.search(href_path):
            continue
        media_link = bool(MEDIA_LINK_PATH_PATTERN.search(href_path))
        audio_link = bool(AUDIO_LINK_PATH_PATTERN.search(href_path))
        event_context = has_earnings_context(haystack)
        nearby_context_score = _nearby_earnings_context_score(candidates, index)
        icon_event_control = bool(
            candidate.tag_name in {"button", "summary"}
            and not visible_label
            and event_context
            and event_date
            and re.search(r"\b(?:webcast|conference\s+call|earnings|results)\b", haystack)
        )
        # Several IR providers render the actual player as an icon-only link
        # (for example /mediaframe/webcast.html) or publish the call as an MP3.
        # The surrounding event row is the evidence that makes these safe to
        # consider; a bare media-looking URL is not enough.
        event_media_link = media_link and bool(event_context or nearby_context_score)
        score = sum(points for term, points in WEBCAST_TERMS if term in haystack)
        direct_webcast_action = bool(lifecycle == 'live' and re.fullmatch(
                r'(?:(?:watch|listen|join|view)(?:\s+the)?\s+)?(?:live\s+)?webcast(?:\s+(?:live|now))?',
                visible_label.strip(), re.I))
        if direct_webcast_action:
            # A real Webcast control must outrank an intermediate detail link
            # that borrows a long page-wide earnings/date context (MKC).
            score += 70
        if event_detail_link:
            score += 18
        if event_media_link:
            score += 42 if audio_link else 32
            if nearby_context_score:
                # A provider/player URL directly beneath a dated earnings
                # title is the actionable control. Prefer it over reopening
                # the title's intermediate event-detail page.
                score += 24
        if lifecycle == "live":
            score += live_candidate_match_score(
                candidate,
                target_date=target_date,
                target_time_utc=target_time_utc,
            )
        if lifecycle == "replay" and REPLAY_COMPLETION_EVIDENCE_PATTERN.search(
            candidate.context_text
        ):
            score += 24
        if (
            not label_has_strong_term
            and not (
                not media_link
                and any(term in action_haystack for term in STRONG_WEBCAST_TERMS)
            )
            and not event_detail_link
            and not event_media_link
            and not icon_event_control
        ):
            continue
        score += nearby_context_score
        if icon_event_control:
            # Some IR templates render the event action as an icon-only button;
            # its surrounding dated event row is the only useful label.
            score += 24
        if candidate.in_navigation:
            if lifecycle == "replay" and any(
                term in visible_label
                for term in (
                    "webcast replay",
                    "listen to webcast",
                    "watch replay",
                    "click here for webcast",
                )
            ):
                score -= 10
            elif lifecycle == "replay" and "/attendee/" in href_path:
                score -= 10
            else:
                score -= 80
        if candidate.tag_name == "a" and candidate.href_path:
            score += 5
        if score > 0:
            scored.append(
                (
                    int(direct_webcast_action),
                    score,
                    event_date.toordinal() if event_date else 0,
                    -index,
                    candidate,
                )
            )

    if not scored:
        fallback_scored: list[tuple[int, int, int, WebcastCandidate]] = []
        for index, candidate in enumerate(candidates):
            if lifecycle == "live" and live_candidate_event_type_mismatch(candidate):
                continue
            label = " ".join(
                value for value in (candidate.text, candidate.aria_label, candidate.title) if value
            ).lower()
            if candidate.in_navigation or any(
                term in label
                for term in (*NON_PLAYBACK_TERMS, *GENERALIZED_NON_PLAYBACK_TERMS)
            ):
                continue
            if _candidate_period_mismatch(
                candidate,
                target_year=period_target_year,
                target_quarter=period_target_quarter,
            ):
                continue
            if lifecycle == "replay" and replay_candidate_rejection_reason(
                " ".join(
                    value
                    for value in (
                        candidate.text,
                        candidate.aria_label,
                        candidate.title,
                        candidate.context_text,
                        " ".join(candidate.selectors),
                    )
                    if value
                ),
                candidate.href_path,
                reference_date=reference_date,
                minimum_age_days=replay_minimum_age_days,
            ):
                continue
            event_date = candidate_event_date(candidate, live_identity=lifecycle == "live")
            bonus = generalized_candidate_bonus(candidate, generalized_patterns)
            if bonus > 0:
                fallback_scored.append(
                    (
                        bonus,
                        event_date.toordinal() if event_date else 0,
                        -index,
                        candidate,
                    )
                )
        if not fallback_scored:
            if lifecycle == "replay" and (target_year is not None or target_quarter):
                return choose_heuristic_candidate(
                    candidates,
                    generalized_patterns,
                    lifecycle=lifecycle,
                    target_date=target_date,
                    target_time_utc=target_time_utc,
                    reference_date=reference_date,
                    replay_minimum_age_days=replay_minimum_age_days,
                )
            return None
        fallback_scored.sort(key=lambda item: item[:3], reverse=True)
        return fallback_scored[0][3]
    scored.sort(key=lambda item: item[:-1], reverse=True)
    return scored[0][-1]


def is_replay_training_candidate(
    candidate: WebcastCandidate,
    *,
    reference_date: date | None = None,
    minimum_age_days: int = 2,
) -> bool:
    """Check whether a link can train downstream webcast stages.

    Replay training intentionally accepts non-earnings events, but it must
    still reject documents and site-navigation links that cannot reach a
    player or an audio stream.
    """
    label = " ".join(
        value
        for value in (candidate.text, candidate.aria_label, candidate.title)
        if value
    ).lower()
    explicit_playback_term = bool(
        REPLAY_EXPLICIT_PLAYBACK_LABEL_PATTERN.search(label)
    )
    if label.strip() in REPLAY_NAVIGATION_LABELS:
        return False
    href = (candidate.href_path or "").lower()
    media_path = bool(MEDIA_LINK_PATH_PATTERN.search(href))
    selector_evidence = " ".join(candidate.selectors).lower()
    if is_non_replay_navigation_link(href, label) and not re.search(
        r"[?&](?:item|event|eventid|event_id|session|sessionid|id)=",
        selector_evidence,
        re.IGNORECASE,
    ):
        return False
    # A provider link can be nested in a site's navigation tree even though
    # its label is an explicit playback action (for example 3M's STREAM link).
    # Inspect absolute URLs embedded in generated selectors as well; tracking
    # links may otherwise hide a redirect to a company homepage.
    selector_urls = re.findall(r"https?://[^\"'\s>]+", selector_evidence)
    if any(is_non_replay_navigation_link(url, label) for url in selector_urls):
        return False
    context = " ".join(
        value
        for value in (label, candidate.context_text, href)
        if value
    )
    # IR pages often place a prepared-remarks MP3 beside the real webcast.
    # The MP3 is a valid resource, but it does not exercise the registration
    # and browser-player path that replay training is meant to verify. Keep
    # direct audio links only when their visible label explicitly describes
    # an on-demand/listenable recording.
    if (
        AUDIO_LINK_PATH_PATTERN.search(href)
        and REPLAY_PROXY_DOCUMENT_PATTERN.search(candidate.context_text or "")
        and not REPLAY_AUDIO_DOCUMENT_LABEL_PATTERN.search(label)
    ):
        return False
    if not candidate.selectors:
        return False
    # Some IR templates render the event calendar inside a navigation frame or
    # mark the whole event list as navigation. A dated earnings detail link is
    # still a valid downstream training surface in that layout.
    navigation_event_detail = bool(
        candidate.in_navigation
        and candidate.tag_name == "a"
        and has_earnings_context(context)
        and (
            EVENT_DETAIL_PATH_PATTERN.search(href)
            or re.search(r"/(?:ir[-/]calendar|calendar[-/]of[-/]events)/detail(?:/|$)", href)
        )
    )
    if candidate.in_navigation and not navigation_event_detail and not (
        explicit_playback_term or media_path
    ):
        return False
    if any(term in label for term in NON_PLAYBACK_TERMS):
        return False
    if href.split("?", maxsplit=1)[0].endswith(NON_PLAYBACK_PATH_SUFFIXES):
        return False
    if (
        urlparse(href).path.rstrip("/") == ""
        and HOME_NAVIGATION_LABEL_PATTERN.search(label)
        and not re.search(
            r"\b(?:webcast|replay|watch|listen|play|audio|video)\b",
            label,
            re.IGNORECASE,
        )
    ):
        return False
    if NON_PLAYBACK_PATH_PATTERN.search(href):
        return False
    if REPLAY_LOGIN_PATH_PATTERN.search(href):
        return False
    dated_earnings_news_article = is_dated_earnings_news_article(
        candidate,
        reference_date=reference_date,
        minimum_age_days=minimum_age_days,
    )
    if replay_candidate_rejection_reason(
        context,
        href,
        reference_date=reference_date,
        minimum_age_days=minimum_age_days,
    ) and not dated_earnings_news_article:
        return False

    explicit_playback_term = explicit_playback_term or bool(
        EXPLICIT_PLAYBACK_LABEL_PATTERN.search(label)
    )
    if (
        REPLAY_ARCHIVE_PRESENTATIONS_PATH_PATTERN.search(href)
        and not media_path
        and not explicit_playback_term
        and not re.search(
            r"(?:[?&](?:item|event|eventid|event_id|session|sessionid|id)=|"
            r"/detail(?:/|$))",
            selector_evidence,
            re.IGNORECASE,
        )
    ):
        return False
    if is_news_article_without_playback_label(label, href) and not dated_earnings_news_article:
        return False
    # Many IR sites link to a dated earnings detail page first and only expose
    # the actual webcast URL inside that page. Treat that detail page as a
    # valid replay-training candidate even when its anchor says only
    # "Q2 2026 Earnings" and not "Webcast".
    dated_earnings_detail = bool(
        candidate.tag_name == "a"
        and candidate_event_date(candidate)
        and has_earnings_context(context)
        and (
            href.rstrip("/")
            not in {"/events", "/events-and-presentations", "/events-presentations"}
            or bool(
                re.search(
                    r"(?:[?&](?:item|event|eventid|event_id|session|sessionid|id)=|"
                    r"href=.*(?:[?&](?:item|event|eventid|event_id|session|sessionid|id)=))",
                    selector_evidence,
                    re.IGNORECASE,
                )
            )
        )
        and not NEWS_ARTICLE_PATH_PATTERN.search(href)
    )
    if (
        href.rstrip("/")
        in {"/events", "/events-and-presentations", "/events-presentations"}
        and not media_path
        and not explicit_playback_term
        and not dated_earnings_detail
    ):
        return False
    # Static-file URLs are frequently PDFs without a file extension. Keep
    # them only when the visible label explicitly identifies a playable item.
    if "/static-files/" in href and not explicit_playback_term:
        return False
    if (
        not media_path
        and not explicit_playback_term
        and not dated_earnings_detail
        and not dated_earnings_news_article
        and not any(term in context for term in REPLAY_TRAINING_TERMS)
    ):
        return False
    return True


def choose_replay_training_candidate(
    candidates: list[WebcastCandidate],
    *,
    reference_date: date | None = None,
    minimum_age_days: int = 2,
) -> WebcastCandidate | None:
    """Choose the newest playable-looking event for downstream training.

    This is deliberately broader than earnings candidate selection. It is
    used only by replay training surfaces, where a conference or presentation
    webcast is a valid proxy for registration, playback, and audio handling.
    """
    reference_date = reference_date or datetime.now(timezone.utc).date()
    scored: list[tuple[int, int, int, WebcastCandidate]] = []
    for index, candidate in enumerate(candidates):
        if not is_replay_training_candidate(
            candidate,
            reference_date=reference_date,
            minimum_age_days=minimum_age_days,
        ):
            continue
        label = " ".join(
            value
            for value in (candidate.text, candidate.aria_label, candidate.title)
            if value
        ).lower()
        href = (candidate.href_path or "").lower()
        context = " ".join(
            value for value in (label, candidate.context_text, href) if value
        )
        score = sum(points for term, points in WEBCAST_TERMS if term in context)
        if re.search(r"\b(?:webcast|listen|audio|replay|watch|play)\b", label):
            score += 35
        if MEDIA_LINK_PATH_PATTERN.search(href):
            score += 30
        if candidate.tag_name == "a" and candidate.href_path:
            score += 5
        event_date = candidate_event_date(candidate)
        scored.append(
            (
                score,
                event_date.toordinal() if event_date else 0,
                -index,
                candidate,
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda item: item[:3], reverse=True)
    return scored[0][3]


def is_replay_training_surface_candidate(
    candidate: WebcastCandidate,
    *,
    reference_date: date | None = None,
) -> bool:
    """Allow a dated event page as a last-resort replay-training entrypoint.

    ``is_replay_training_candidate`` intentionally asks for strong evidence that
    the clicked element itself reaches a player.  That is correct for normal
    event selection, but too strict for historical training: many IR templates
    expose only a dated event/news/detail link and render the actual webcast
    link on the next page.  This fallback still rejects documents, auth pages,
    product navigation, and future events, while allowing that intermediate
    event page to be inspected by the downstream registration/player logic.
    """
    reference_date = reference_date or datetime.now(timezone.utc).date()
    label = " ".join(
        value
        for value in (candidate.text, candidate.aria_label, candidate.title)
        if value
    ).strip()
    href = (candidate.href_path or "").strip()
    context = " ".join(
        value for value in (label, candidate.context_text, href) if value
    )
    normalized = context.lower()

    if not candidate.selectors or not href:
        return False
    if is_non_replay_navigation_link(href, label):
        return False
    selector_evidence = " ".join(candidate.selectors)
    selector_urls = re.findall(r"https?://[^\"'\s>]+", selector_evidence)
    if any(is_non_replay_navigation_link(url, label) for url in selector_urls):
        return False
    if any(term in label.lower() for term in NON_PLAYBACK_TERMS):
        return False
    if href.lower().split("?", maxsplit=1)[0].endswith(NON_PLAYBACK_PATH_SUFFIXES):
        return False
    if REPLAY_LOGIN_PATH_PATTERN.search(href):
        return False
    if NEWS_ARTICLE_PATH_PATTERN.search(href) and not has_earnings_context(context):
        return False
    if re.search(r"/static-files(?:/|$)", href, re.IGNORECASE):
        return False
    if re.search(r"\b(?:home|products?|solutions?|careers?|privacy|cookie)\b", label, re.IGNORECASE):
        return False

    event_date = event_date_from_text(context)
    if event_date and event_date > reference_date:
        return False

    path_hint = bool(
        MEDIA_LINK_PATH_PATTERN.search(href)
        or EVENT_DETAIL_PATH_PATTERN.search(href)
        or NEWS_ARTICLE_PATH_PATTERN.search(href)
        or re.search(
            r"/(?:calendar|events?|presentations?|webcasts?|replays?|conference|earnings)(?:[-_/?.]|$)",
            href,
            re.IGNORECASE,
        )
    )
    # ``context_text`` can be the whole page on broad IR templates. A
    # navigation link such as Corporate Governance then appears to have
    # playback evidence merely because another part of the page mentions
    # videos or earnings. Require the playback word on the link itself; a
    # dated event/detail path remains eligible through ``path_hint``.
    playback_hint = bool(
        re.search(
            r"\b(?:webcast|replay|listen|watch|play|audio|video|webinar|conference|earnings|results|presentation|event|call)\b",
            " ".join(value for value in (label, href) if value),
            re.IGNORECASE,
        )
    )
    return path_hint or playback_hint


def choose_replay_training_surface_candidate(
    candidates: list[WebcastCandidate],
    *,
    reference_date: date | None = None,
) -> WebcastCandidate | None:
    """Choose a recent historical event/detail link when no player link is visible.

    This is a bounded discovery fallback, not a claim that the link is the
    correct live earnings call.  The caller is expected to open it and run the
    normal registration, playback, and audio checks.
    """
    reference_date = reference_date or datetime.now(timezone.utc).date()
    scored: list[tuple[int, int, int, WebcastCandidate]] = []
    for index, candidate in enumerate(candidates):
        if not is_replay_training_surface_candidate(
            candidate,
            reference_date=reference_date,
        ):
            continue
        label = " ".join(
            value
            for value in (candidate.text, candidate.aria_label, candidate.title)
            if value
        ).lower()
        href = (candidate.href_path or "").lower()
        context = " ".join(
            value for value in (label, candidate.context_text, href) if value
        )
        score = 0
        if MEDIA_LINK_PATH_PATTERN.search(href):
            score += 120
        if EXPLICIT_PLAYBACK_LABEL_PATTERN.search(label):
            score += 100
        if EVENT_DETAIL_PATH_PATTERN.search(href):
            score += 75
        if NEWS_ARTICLE_PATH_PATTERN.search(href) and has_earnings_context(context):
            score += 60
        if re.search(r"\b(?:earnings|results|conference call|quarter)\b", context):
            score += 45
        if re.search(r"\b(?:webcast|replay|listen|watch|audio|video|webinar)\b", context):
            score += 35
        if candidate.in_navigation:
            score -= 20
        event_date = candidate_event_date(candidate)
        scored.append(
            (
                score,
                event_date.toordinal() if event_date else 0,
                -index,
                candidate,
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda item: item[:3], reverse=True)
    return scored[0][3]


def _nearby_earnings_context_score(candidates: list[WebcastCandidate], index: int) -> int:
    """Associate a generic 'Listen to Webcast' link with the event title just above it."""
    candidate = candidates[index]
    visible_label = " ".join(
        value for value in (candidate.text, candidate.aria_label, candidate.title) if value
    ).lower()
    candidate_context = candidate.context_text.lower()
    # An earnings title already carries its own identity and should not receive
    # the large adjacency bonus intended for the generic action beside it.
    if has_earnings_context(visible_label):
        return 0
    if candidate_context and has_earnings_context(candidate_context):
        return 150
    if candidate_context:
        normalized_context = re.sub(r"\s+", " ", candidate_context).strip()
        normalized_label = re.sub(r"\s+", " ", visible_label).strip()
        generic_action_only = (
            normalized_context == normalized_label
            and len(normalized_context) <= 100
            and bool(EXPLICIT_PLAYBACK_LABEL_PATTERN.search(normalized_context))
            and not re.search(
                r"\b(?:investor|analyst|capital markets?|healthcare|technology)\s+"
                r"(?:day|meeting|conference)\b|\bwebinar\b",
                normalized_context,
                re.IGNORECASE,
            )
        )
        if not generic_action_only:
            return 0
    candidate_frame = candidate.candidate_id.split("-element-", maxsplit=1)[0]
    candidate_top = candidate.rect.get("y", 0.0)
    for previous in reversed(candidates[:index]):
        previous_frame = previous.candidate_id.split("-element-", maxsplit=1)[0]
        if previous_frame != candidate_frame:
            continue
        label = " ".join(
            value
            for value in (
                previous.text,
                previous.aria_label,
                previous.title,
                previous.href_path or "",
            )
            if value
        ).lower()
        if not label or "listen to webcast" in label:
            continue
        previous_bottom = previous.rect.get("y", 0.0) + previous.rect.get("height", 0.0)
        distance = candidate_top - previous_bottom
        if distance < -4:
            continue
        if distance > 180:
            break
        if has_earnings_context(label):
            return 150
        return 0
    return 0


def make_recipe(
    page_url: str,
    candidate: WebcastCandidate,
    *,
    strategy: str,
    lifecycle: str = "unknown",
    confidence: float,
    snapshot: LearningSnapshot | None = None,
    vision_reason: str | None = None,
) -> WebcastRecipe:
    evidence: dict[str, Any] = {
        "candidate": candidate.prompt_value(),
        "learned_at": datetime.now(timezone.utc).isoformat(),
    }
    if snapshot:
        evidence["screenshot_path"] = str(snapshot.screenshot_path)
        evidence["candidates_path"] = str(snapshot.candidates_path)
    if vision_reason:
        evidence["vision_reason"] = vision_reason[:500]

    return WebcastRecipe(
        domain=domain_for_url(page_url),
        selectors=candidate.selectors,
        frame_hostname=candidate.frame_hostname,
        target_text=(candidate.text or candidate.aria_label or candidate.title)[:500],
        target_href_path=candidate.href_path,
        strategy=strategy,
        lifecycle=lifecycle.lower(),
        confidence=max(0.0, min(1.0, confidence)),
        evidence=evidence,
        stage="playback",
    )


def artifact_paths(ticker: str, page_url: str) -> tuple[Path, Path]:
    root = webcast_artifacts_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_hash = hashlib.sha256(page_url.encode("utf-8")).hexdigest()[:10]
    prefix = f"{ticker.upper()}-{stamp}-{source_hash}"
    return root / f"{prefix}.jpg", root / f"{prefix}.json"


def webcast_artifacts_root() -> Path:
    """Return a writable evidence directory for the current runtime.

    Docker-created artifact directories can be owned by ``nobody`` after a
    container run. Keep an explicit path authoritative, but fall back to the
    user-owned runtime directory when the legacy default cannot be written.
    """
    configured = os.getenv("WEBCAST_ARTIFACTS_DIR")
    if configured:
        return Path(configured)

    data_pipeline_root = Path(__file__).resolve().parents[2]
    preferred = data_pipeline_root / ".artifacts" / "webcast"
    runtime_fallback = data_pipeline_root / ".runtime" / "artifacts"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        if os.access(preferred, os.W_OK):
            return preferred
    except OSError:
        pass
    return runtime_fallback


class OpenAIVisionSelector:
    """Optional screenshot selector. DOM heuristics remain available without an API key."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.enabled = os.getenv("WEBCAST_VISION_ENABLED", "false").lower() == "true"
        self.model = os.getenv("WEBCAST_VISION_MODEL", "gpt-5.6-luna").strip()

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def select(
        self,
        screenshot_path: Path,
        candidates: list[WebcastCandidate],
        *,
        ticker: str,
    ) -> VisionSelection | None:
        if not self.available:
            return None

        try:
            image_data = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
            mime_type = "image/jpeg" if screenshot_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            candidate_payload = [candidate.prompt_value() for candidate in candidates[:80]]
            prompt = (
                "Find the control that opens the current earnings webcast or live earnings call. "
                "Choose only one supplied candidate_id when a suitable DOM candidate is available. "
                "Do not choose navigation menu entries, historical annual-report links, or generic investor pages. "
                "If no supplied candidate corresponds to the visual target, provide screenshot coordinates "
                "for the center of a clickable control in x/y; otherwise x and y must be 0. "
                f"Ticker: {ticker}. Candidates: {json.dumps(candidate_payload, ensure_ascii=True)}"
            )
            payload = {
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_image",
                                "image_url": f"data:{mime_type};base64,{image_data}",
                                "detail": "low",
                            },
                        ],
                    }
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "webcast_target",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "candidate_id": {"type": "string"},
                                "confidence": {"type": "number"},
                                "reason": {"type": "string"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                            },
                            "required": ["candidate_id", "confidence", "reason", "x", "y"],
                            "additionalProperties": False,
                        },
                    }
                },
            }
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            return parse_vision_selection(extract_response_text(response.json()))
        except Exception as exc:
            print(f"[WebcastLearning] vision selection skipped: {str(exc)[:180]}")
            return None


def extract_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    texts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    return "\n".join(texts)


def parse_vision_selection(value: str) -> VisionSelection | None:
    try:
        parsed = json.loads(value)
        confidence = float(parsed.get("confidence", 0))
        return VisionSelection(
            candidate_id=str(parsed.get("candidate_id") or ""),
            confidence=max(0.0, min(1.0, confidence)),
            reason=str(parsed.get("reason") or "")[:500],
            x=float(parsed.get("x", 0) or 0),
            y=float(parsed.get("y", 0) or 0),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def write_snapshot_metadata(
    candidates_path: Path,
    *,
    page_url: str,
    candidates: list[WebcastCandidate],
) -> None:
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps(
            {
                "page_url": _safe_url(page_url),
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "candidates": [candidate.prompt_value() for candidate in candidates],
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
