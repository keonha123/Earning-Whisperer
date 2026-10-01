"""Shared browser evidence patterns, URL rules and data types."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

from ....config import DATA_PIPELINE_ROOT, REPO_ROOT, load_project_env

from ..webcast_learning import (
    LearningSnapshot,
    OpenAIVisionSelector,
    WebcastCandidate,
    WebcastRecipe,
    EVENT_DATE_PATTERN,
    MONTH_NUMBERS,
    artifact_paths,
    choose_heuristic_candidate,
    choose_replay_training_candidate,
    choose_replay_training_surface_candidate,
    candidate_identity_mismatch,
    domain_for_url,
    event_date_from_text,
    event_datetime_from_text,
    future_event_start_utc,
    live_candidate_identity_confirmation,
    live_event_identity_confirmation,
    is_non_replay_navigation_link,
    is_replay_training_candidate,
    make_generalized_patterns,
    make_recipe,
    NEWS_ARTICLE_PATH_PATTERN,
    REPLAY_LOGIN_PATH_PATTERN,
    REPLAY_ARCHIVE_PRESENTATIONS_PATH_PATTERN,
    is_news_article_without_playback_label,
    replay_candidate_rejection_reason,
    write_snapshot_metadata,
)



REGISTRATION_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "code",
        "id_token",
        "access_token",
        "refresh_token",
        "session",
        "sessionid",
        "state",
        "signature",
        "sig",
        "token",
    }
)


def redact_registration_url(value: str | None) -> str:
    """Keep a review URL useful without exposing auth/session query values."""
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    query = []
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        safe_value = (
            "[REDACTED]"
            if key.casefold() in REGISTRATION_SENSITIVE_QUERY_KEYS
            else query_value
        )
        query.append((key, safe_value))
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            "",
        )
    )


def load_registration_approval_manifest(path_value: str | None) -> dict[str, dict[str, Any]]:
    """Load ticker-scoped approvals without ever storing profile values."""
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    approvals = payload.get("approvals", payload)
    if not isinstance(approvals, dict):
        return {}
    return {
        str(ticker).upper(): entry
        for ticker, entry in approvals.items()
        if isinstance(entry, dict)
    }


def registration_url_identity(value: str | None) -> str:
    """Canonicalize a redacted registration URL for approval comparison."""
    redacted = redact_registration_url(value)
    parsed = urlparse(redacted)
    if not parsed.scheme or not parsed.netloc:
        return ""
    query = sorted(parse_qsl(parsed.query, keep_blank_values=True))
    return urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/") or "/",
            parsed.params,
            urlencode(query),
            "",
        )
    )

WEBCAST_TEXT_PATTERN = re.compile(
    r"Webcast|Listen|Join|Audio|Replay|Presentation|Event",
    re.IGNORECASE,
)
PLAY_TEXT_PATTERN = re.compile(
    r"\b(?:Play|Listen|Start|Unmute|Watch|Join|Enter|Replay|View\s+Now)\b|▶",
    re.IGNORECASE,
)
NON_PLAYBACK_CONTROL_PATTERN = re.compile(
    r"\b(?:download|career|job|overview|learn more|register|sign up|shop|"
    r"subscribe|alert|notification|notify|privacy|cookie|consent)\b|"
    r"\bjoin (?:our team|us)\b",
    re.IGNORECASE,
)

HUMAN_ACTION_CAPTURE_SCRIPT = r"""
(() => {
  if (window.__ewHumanActionCaptureInstalled) return;
  window.__ewHumanActionCaptureInstalled = true;
  window.__ewHumanActions = [];

  const compact = value => String(value || '').replace(/\s+/g, ' ').trim().slice(0, 240);
  const selectorHint = element => {
    if (!element || !element.tagName) return '';
    const tag = element.tagName.toLowerCase();
    if (element.id) return `#${CSS.escape(element.id)}`;
    const name = element.getAttribute('name');
    if (name && !['input', 'textarea'].includes(tag)) {
      return `${tag}[name="${CSS.escape(name)}"]`;
    }
    const aria = element.getAttribute('aria-label');
    if (aria) return `${tag}[aria-label="${CSS.escape(aria)}"]`;
    const role = element.getAttribute('role');
    if (role) return `${tag}[role="${CSS.escape(role)}"]`;
    const href = element.getAttribute('href');
    if (tag === 'a' && href) return `a[href="${CSS.escape(href)}"]`;
    return tag;
  };
  const elementPath = element => {
    if (!element || !element.tagName) return '';
    const parts = [];
    let current = element;
    for (let depth = 0; current && current.nodeType === 1 && depth < 8; depth += 1) {
      const tag = current.tagName.toLowerCase();
      if (current.id) {
        parts.unshift(`#${CSS.escape(current.id)}`);
        break;
      }
      let ordinal = 1;
      let sibling = current;
      while ((sibling = sibling.previousElementSibling)) {
        if (sibling.tagName === current.tagName) ordinal += 1;
      }
      parts.unshift(`${tag}:nth-of-type(${ordinal})`);
      current = current.parentElement;
    }
    return parts.join(' > ');
  };
  const playerContext = element => {
    let current = element;
    for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
      const values = [current.id, current.className, current.getAttribute('aria-label')]
        .filter(value => typeof value === 'string' && value.trim());
      const context = compact(values.join(' '));
      if (/player|video|media|control|playback|progress|timeline|seek|webcast/i.test(context)) {
        return context;
      }
    }
    return '';
  };
  const contextText = element => {
    let current = element;
    for (let depth = 0; current && depth < 7; depth += 1, current = current.parentElement) {
      if (!current.matches) continue;
      if (!current.matches('li,article,tr,[class*="event" i],[class*="webcast" i]')) continue;
      const text = compact(current.innerText || current.textContent);
      if (text) return text.slice(0, 500);
    }
    return '';
  };
  const record = (type, element, extra = {}) => {
    if (!element) return;
    const tag = element.tagName.toLowerCase();
    const isSensitiveField = ['input', 'textarea', 'select'].includes(tag);
    const rect = typeof element.getBoundingClientRect === 'function'
      ? element.getBoundingClientRect()
      : null;
    const iconControl = Boolean(
      !isSensitiveField
      && element.matches
      && element.matches('button, a, [role="button"]')
      && element.querySelector
      && element.querySelector('svg, use, path')
    );
    const item = {
      type,
      tag,
      selector_hint: selectorHint(element),
      text: isSensitiveField ? '' : compact(element.innerText || element.textContent),
      aria_label: compact(element.getAttribute('aria-label')),
      title: compact(element.getAttribute('title')),
      href: tag === 'a' ? String(element.href || '').slice(0, 500) : '',
      context_text: isSensitiveField ? '' : contextText(element),
      element_path: isSensitiveField ? '' : elementPath(element),
      player_context: isSensitiveField ? '' : playerContext(element),
      icon_control: iconControl,
      rect: rect ? {
        x: Number(rect.left.toFixed(2)),
        y: Number(rect.top.toFixed(2)),
        width: Number(rect.width.toFixed(2)),
        height: Number(rect.height.toFixed(2)),
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
      } : null,
      captured_page_url: String(location.href || '').slice(0, 1000),
      value_present: isSensitiveField && Boolean(element.value),
      ...extra,
      captured_at: Date.now(),
    };
    if (typeof window.__ewRecordHumanAction === 'function') {
      Promise.resolve(window.__ewRecordHumanAction(item)).catch(() => {});
    } else {
      window.__ewHumanActions.push(item);
      if (window.__ewHumanActions.length > 200) window.__ewHumanActions.shift();
    }
  };
  document.addEventListener('click', event => {
    const element = event.target && event.target.closest
      ? event.target.closest('a,button,[role="button"],input,select,textarea,label')
      : event.target;
    record('click', element);
  }, true);
  document.addEventListener('input', event => record('input', event.target), true);
  document.addEventListener('change', event => record('change', event.target), true);
})();
"""
REGISTRATION_EMAIL_ERROR_PATTERN = re.compile(
    r"please enter a valid e-?mail address|invalid e-?mail(?: address)?",
    re.IGNORECASE,
)
REGISTRATION_BARRIER_PATTERN = re.compile(
    r"hcaptcha|recaptcha|captcha|i['’]?m\s+not\s+a\s+robot|"
    r"verify\s+(?:that\s+)?you\s+are\s+human|acceptance of the .* terms of use|"
    r"privacy policy.*this field is required",
    re.IGNORECASE,
)
ALREADY_REGISTERED_PATTERN = re.compile(
    r"already\s+registered(?!\?)|registration\s+already\s+exists|"
    r"login\s+instructions|receive\s+an\s+email[\s\w-]*login",
    re.IGNORECASE,
)
EXISTING_WEBINAR_LOGIN_PATTERN = re.compile(
    r"(?:\blog\s+in\s+now\b|\balready\s+registered\??\b).*"
    r"(?:\battend\b|\blog\s*in\b|\baccess\b)",
    re.IGNORECASE | re.DOTALL,
)
REGISTRATION_CONSENT_POSITIVE_PATTERN = re.compile(
    r"(?:^|\b)(?:yes|agree|accept|consent|understand|acknowledge|"
    r"i\s+accept|i\s+agree|i\s+understand)(?:\b|$)",
    re.IGNORECASE,
)
REGISTRATION_CONSENT_NEGATIVE_PATTERN = re.compile(
    r"(?:^|\b)(?:no|decline|reject|disagree|do\s+not|don't|without)\b",
    re.IGNORECASE,
)


def is_positive_registration_consent_text(text: str | None) -> bool:
    """Return whether a registration option represents affirmative consent."""
    normalized = " ".join(str(text or "").split())
    if not normalized or REGISTRATION_CONSENT_NEGATIVE_PATTERN.search(normalized):
        return False
    return bool(REGISTRATION_CONSENT_POSITIVE_PATTERN.search(normalized))


def is_existing_webinar_login_surface(text: str | None) -> bool:
    """Recognize webinar.net's already-registered email attendance screen."""
    normalized = " ".join(str(text or "").split())
    return bool(EXISTING_WEBINAR_LOGIN_PATTERN.search(normalized))
REGISTRATION_FORM_TEXT_PATTERN = re.compile(
    r"(?:first\s+name|last\s+name|email\s+address|company|organization)"
    r"[\s\S]{0,240}(?:register|submit|enter|join)|"
    r"(?:register|submit|enter|join)[\s\S]{0,240}"
    r"(?:first\s+name|last\s+name|email\s+address|company|organization)",
    re.IGNORECASE,
)
OPEN_EXCHANGE_REGISTRATION_URL_PATTERN = re.compile(
    r"^https?://(?:[a-z0-9-]+\.)*open-exchange\.net/registration(?:/)?(?:[?#].*)?$",
    re.IGNORECASE,
)
WEBCASTS_REGISTRATION_FORM_SELECTOR = "form#frmRegister"
REGISTRATION_FORM_CONTAINER_SELECTORS = (
    WEBCASTS_REGISTRATION_FORM_SELECTOR,
    "form#fmRegister",
    "form[id*='reg' i]",
    "form",
    "div[id*='reg' i]",
    "div[class*='form' i]",
)
WEBCASTS_REGISTRATION_FIELD_SELECTORS = {
    "first_name": "input[title='First Name' i]",
    "last_name": "input[title='Last Name' i]",
    "company": "input[title='Company' i]",
    "email": "input[title='Email' i]",
}
WEBCASTS_REGISTRATION_SUBMIT_SELECTOR = (
    "input.buttonSubmit[type='submit'][value='Submit' i]"
)
Q4_EVENT_GATE_PATTERN = re.compile(
    r"register\s+for\s+(?:the\s+)?event|register\s+for\s+this\s+event|"
    r"register\s+with\s+a\s+q4\s+account|continue\s+with\s+q4|"
    r"continue\s+without\s+(?:a\s+)?q4\s+account|attendee\s+type",
    re.IGNORECASE,
)
Q4_GUEST_REGISTRATION_PATTERN = re.compile(
    r"guest\s+registration|i\s+am\s+an\s+individual\s+attendee|"
    r"company\s+name\s+required",
    re.IGNORECASE,
)


def is_q4_followup_registration_text(text: str | None) -> bool:
    """Detect Q4's post-guest-registration attendee-type step."""
    normalized = " ".join(str(text or "").split())
    return bool(
        re.search(r"one\s+more\s+thing", normalized, re.IGNORECASE)
        and re.search(r"attendee\s+type", normalized, re.IGNORECASE)
        and re.search(r"register\s+for\s+this\s+event", normalized, re.IGNORECASE)
    )


def is_q4_custom_registration_text(text: str | None) -> bool:
    """Detect Q4's single-field post-login registration step."""
    normalized = " ".join(str(text or "").split())
    return bool(
        re.search(r"company\s+name", normalized, re.IGNORECASE)
        and re.search(r"register\s+for\s+this\s+event", normalized, re.IGNORECASE)
        and re.search(
            r"one\s+more\s+thing|finish\s+registering|register\s+to\s+access",
            normalized,
            re.IGNORECASE,
        )
    )


def is_q4_guest_registration_text(text: str | None) -> bool:
    """Detect Q4's full guest form before the optional company lookup."""
    normalized = " ".join(str(text or "").split())
    return bool(Q4_GUEST_REGISTRATION_PATTERN.search(normalized))
EXPIRED_EVENT_PATTERN = re.compile(
    r"webcast\s*no\s*longer\s*available|"
    r"(?:recording|replay|session|conference\s+website|presentation)[\s\S]{0,100}"
    r"(?:not\s+available|no\s+longer\s+available|expired|"
    r"has\s+concluded|is\s+closed)|"
    r"no\s+replay\s+available",
    re.IGNORECASE,
)
EXPIRED_MEDIA_PATH_PATTERN = re.compile(
    r"(?:^|/)(?:expired|unavailable)\.(?:m3u8|mpd|mp4|m4a|mp3|aac|wav)(?:/|$)",
    re.IGNORECASE,
)
NON_EARNINGS_EVENT_PATTERN = re.compile(
    r"\b(?:investor|analyst|capital\s+markets?)\s+day\b|"
    r"\b(?:investor|analyst)\s+(?:conference|meeting)\b|"
    r"\b(?:annual\s+)?(?:growth\s+stock|industry|technology|healthcare|"
    r"global|virtual)\s+conference\b|"
    r"\bwebinar\b|"
    r"\b(?:product|innovation)\s+(?:event|presentation)\b",
    re.IGNORECASE,
)
EARNINGS_EVENT_CONTEXT_PATTERN = re.compile(
    r"\b(?:earnings|quarter(?:ly)?|financial\s+results|conference\s+call|"
    r"fiscal\s+(?:year|quarter))\b",
    re.IGNORECASE,
)
NOT_LIVE_EVENT_PATTERN = re.compile(
    r"(?:webinar|webcast|event|presentation)\s+(?:has\s+not\s+(?:quite\s+)?started|hasn['’]t\s+started|is\s+not\s+yet\s+(?:live|available))|"
    r"(?:entry|access|registration)[\s\S]{0,100}"
    r"(?:not\s+yet\s+available|come\s+back\s+closer|has\s+not\s+started)|"
    r"(?:live\s+presentation|webcast|event)[\s\S]{0,100}"
    r"(?:not\s+yet\s+available|has\s+not\s+started)|"
    r"thank\s+you\s+for\s+registering[\s\S]{0,500}"
    r"access\s+the\s+webcast\s+up\s+to\s+\d+\s+minutes\s+before|"
    r"return\s+to\s+this\s+page\s+a\s+few\s+minutes\s+before\s+"
    r"(?:the\s+)?start",
    re.IGNORECASE,
)
RESOURCE_NOT_FOUND_PATTERN = re.compile(
    r"resource you have requested cannot be found|"
    r"(?:page|event|webcast|recording)\s+(?:was\s+)?not\s+found|"
    r"\b404\b",
    re.IGNORECASE,
)
MISSING_RESOURCE_URL_PATTERN = re.compile(
    r"(?:/|#)404(?:[/#?]|$)|not[-_]found",
    re.IGNORECASE,
)
ACCESS_BARRIER_PATTERN = re.compile(
    r"access denied|forbidden|you (?:do not|don't) have permission|"
    r"verify you are human|performing security verification|checking your browser|captcha|unusual traffic|"
    r"this request was blocked by our security service|access to the player was denied|"
    r"player access was denied|code\s*[:#]?\s*1011|error\s*15|powered by imperva",
    re.IGNORECASE,
)
HTTP_ACCESS_BARRIER_STATUSES = {401, 403, 429}
DYNAMIC_LOADING_PATTERN = re.compile(
    r"(?:^|\n)\s*loading\s*\.*\s*(?:\n|$)",
    re.IGNORECASE,
)
MEDIA_URL_PATTERN = re.compile(
    r"(\.m3u8|\.mpd|\.mp4|\.m4a|\.mp3|\.aac|\.wav|\.m4s|\.ts)(?:$|[?#])",
    re.IGNORECASE,
)
NON_PLAYBACK_DOCUMENT_PATTERN = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|svg)(?:$|[?#])",
    re.IGNORECASE,
)
REPLAY_PROXY_LINK_PATTERN = re.compile(
    r"\b(?:webcast|replay|watch|listen|audio|video|play|presentation|conference|event)\b",
    re.IGNORECASE,
)
REPLAY_PROXY_DOCUMENT_PATTERN = re.compile(
    r"\b(?:legal\s+disclaimer|disclaimer|transcript|prepared\s+remarks|"
    r"press\s+release|financial\s+tables?|slides?)\b",
    re.IGNORECASE,
)
NON_PLAYBACK_URL_HOSTS = (
    "facebook.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
)
NON_PLAYBACK_SURFACE_HOSTS = (
    "play.google.com",
    "apps.apple.com",
    "itunes.apple.com",
    "apps.microsoft.com",
    "store.steampowered.com",
)
NON_PLAYBACK_SURFACE_PATH_PATTERN = re.compile(
    r"^/store(?:/|$)|^/app-store(?:/|$)|^/apps(?:/|$)",
    re.IGNORECASE,
)
NON_PLAYBACK_PRODUCT_PATH_PATTERN = re.compile(
    r"/(?:products?|system-solutions|product-catalog|application-pages|"
    r"audio-and-radio)(?:/|$)",
    re.IGNORECASE,
)
NON_PLAYBACK_PRODUCT_LABEL_PATTERN = re.compile(
    r"\b(?:audio\s+and\s+radio|product(?:s)?(?:\s+(?:overview|catalog))?|"
    r"solutions?)\b",
    re.IGNORECASE,
)
NON_PLAYBACK_HOME_LABEL_PATTERN = re.compile(
    r"\b(?:home(?:\s+page)?|link\s+to\s+home|company\s+home)\b",
    re.IGNORECASE,
)
NON_PLAYBACK_MEDIA_PATH_PATTERN = re.compile(
    r"(?:^|[-_/])(?:banner|hero|background|sizzle|promo|sample|placeholder|"
    r"teaser|career|homepage[-_]?loop|homepage[-_]?video)(?:[-_/.]|$)",
    re.IGNORECASE,
)
NON_PLAYBACK_URL_PATH_PATTERN = re.compile(
    r"/(?:share(?:_channel)?|privacy|terms|legal|cookie)(?:[/?:#]|$)",
    re.IGNORECASE,
)
SUBSCRIPTION_PAGE_PATTERN = re.compile(
    r"/(?:subscribe(?:[_-]error)?|email[-_]?alerts?|newsletter)(?:[/#?]|$)",
    re.IGNORECASE,
)
AUTHENTICATION_SURFACE_URL_PATTERN = re.compile(
    r"/(?:login|sign[-_]?in|authenticate|authentication|auth)(?:[/?:#]|$)",
    re.IGNORECASE,
)
AUTHENTICATION_FORM_TEXT_PATTERN = re.compile(
    r"(?:please\s+)?(?:log\s*in|sign\s*in)[\s\S]{0,320}"
    r"(?:e[-\s]?mail|email\s+address)[\s\S]{0,320}"
    r"(?:log\s*in|sign\s*in|access|attend)",
    re.IGNORECASE,
)
NON_MEDIA_HOSTS = ("browser.events.data.microsoft.com", "google-analytics.com")
NONESSENTIAL_POPUP_HOST_SUFFIXES = ("qualtrics.com",)
RECIPE_LIFECYCLES = {"unknown", "pre_live", "live", "replay"}
DIRECT_PLAYER_HOST_SUFFIXES = ("youtube.com", "youtu.be")
AUDIO_PRIMING_PLAYER_HOST_SUFFIXES = (*DIRECT_PLAYER_HOST_SUFFIXES, "media-server.com")
SURVEY_TEXT_PATTERN = re.compile(
    r"\b(?:survey|feedback|your opinion matters|after your site visit)\b",
    re.IGNORECASE,
)
COOKIE_CONSENT_TEXT_PATTERN = re.compile(
    r"\b(?:we|this (?:site|website))\s+(?:use|uses)\s+(?:essential\s+)?cookies?\b|"
    r"\bcookie\s+(?:preferences?|settings|consent|banner|notice)\b",
    re.IGNORECASE,
)
LEGAL_OVERLAY_TEXT_PATTERN = re.compile(
    r"\b(?:forward[-\s]?looking statements?|non[-\s]?gaap|legal disclaimer)\b",
    re.IGNORECASE,
)
DISCLOSURE_AGREEMENT_PAGE_PATTERN = re.compile(
    r"\b(?:please review the following disclosure agreement|"
    r"disclosure agreement)\b",
    re.IGNORECASE,
)
REPLAY_ARCHIVE_VIEW_PATTERN = re.compile(
    r"^\s*(?:(?:past|previous|archived)\s+(?:events?|webcasts?|calls?)|"
    r"(?:webcasts?|events?)\s+(?:&|and)\s+presentations|"
    r"investor\s+calls?|historical\s+webcasts?|webcast\s+archives?)\s*$",
    re.IGNORECASE,
)
REPLAY_ARCHIVE_NAVIGATION_LABELS = frozenset(
    {
        "events",
        "events & presentations",
        "events and presentations",
        "news & events",
        "news and events",
        "past events",
        "archived events",
    }
)
REPLAY_EXPANSION_LABEL_PATTERN = re.compile(
    r"^\s*(?:\+|more(?:\s+information|\s+info)?|view\s+details|show\s+details|"
    r"expand|details?)\s*$",
    re.IGNORECASE,
)
ARCHIVE_NAVIGATION_TERMS = (
    ("audio archive", 100),
    ("audio archives", 100),
    ("webcast archive", 90),
    ("webcast archives", 90),
    ("earnings archive", 80),
    ("historical webcasts", 95),
    ("historical webcast", 95),
    ("news & events", 65),
    ("news and events", 65),
    ("events and presentations", 50),
    ("events & presentations", 50),
)
ARCHIVE_NAVIGATION_PATH_PATTERN = re.compile(
    r"/(?:events?(?:[-/]and[-/]|[-/])presentations|"
    r"events?[-/]calendar|calendar[-/]of[-/]events|ir[-/]calendar)(?:/|$)",
    re.IGNORECASE,
)
KNOWN_PROVIDER_ARCHIVE_PATHS = {
    "ir.thermofisher.com": "/investors/news-events/events/default.aspx",
}
KNOWN_ACCESS_FALLBACK_HOSTS = {
    # FirstEnergy retains an older Q4-hosted investor site alongside the
    # current domain. Keep this explicit; do not guess arbitrary domains.
    "investors.firstenergycorp.com": "firstenergycorp2020index.q4web.com",
}
COMMON_CHROMIUM_EXECUTABLES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
    "/opt/google/chrome/chrome",
)


def future_event_date_reason(
    text: str,
    *,
    reference_date: date | None = None,
) -> str | None:
    """Return a future earnings/event date when a page has not opened playback yet."""
    if not re.search(r"earnings|conference\s+call|webcast|event", text, re.IGNORECASE):
        return None
    reference_date = reference_date or date.today()
    for match in EVENT_DATE_PATTERN.finditer(text):
        try:
            event_date = date(
                int(match.group(3)),
                MONTH_NUMBERS[match.group(1)[:3].lower()],
                int(match.group(2)),
            )
        except (KeyError, ValueError):
            continue
        if event_date > reference_date:
            return match.group(0)
    return None


def live_event_wait_reason(
    evidence: str,
    *,
    target_date: date | None,
    target_time_utc: datetime | None = None,
    reference_time_utc: datetime | None = None,
) -> str | None:
    """Evaluate readiness only within the positively identified event row."""
    from ..webcast_learning import event_identity_text
    from ...schedules.call_times import parse_call_times, seasonal_abbreviation_conflict
    evidence = event_identity_text(evidence)
    if target_date is None:
        return None
    call_clock = parse_call_times(evidence, target_date, grace_days=0)
    # An explicit conflict/TBD in this selected dated call is a retry condition,
    # never permission to proceed because the first clock happened to be old.
    if call_clock.conflicted:
        return "scheduled event start time is ambiguous; waiting for current official time"
    if call_clock.unavailable_reason:
        return f"scheduled event start is {call_clock.unavailable_reason}"
    if not live_event_identity_confirmation(
        evidence, target_date=target_date, target_time_utc=target_time_utc,
    ):
        return None
    reference = reference_time_utc or datetime.now(timezone.utc)
    reference = (reference.replace(tzinfo=timezone.utc) if reference.tzinfo is None
                 else reference.astimezone(timezone.utc))
    # A matched event whose page omits a clock still obeys the fresh UTC start
    # supplied by the scheduler from DB. A new explicit page clock is observed
    # and committed by the caller before any capture handoff.
    # A standard-zone abbreviation can be a stale template label during DST.
    # Do not delay an independently verified DB clock by one hour solely on
    # that label. Literal standard time without a conflicting target is intact.
    standard_label_conflict = bool(call_clock.selected and
        seasonal_abbreviation_conflict(call_clock.selected, target_time_utc))
    start = (target_time_utc if standard_label_conflict else
             call_clock.selected.scheduled_at_utc if call_clock.selected else target_time_utc)
    if start is not None:
        start = (start.replace(tzinfo=timezone.utc) if start.tzinfo is None
                 else start.astimezone(timezone.utc))
        from datetime import timedelta
        early = max(0, int(os.getenv("DATE_STREAM_EARLY_ENTRY_MINUTES", "5")))
        if reference < start - timedelta(minutes=early):
            return f"scheduled event time is in the future: {start.isoformat()}"
    # An exact timezone-aware start takes precedence over a date-only check.
    # Date-only schedules use the same New York day as the live watch queue.
    if call_clock.selected is None:
        future_date = future_event_date_reason(
            evidence,
            reference_date=reference.astimezone(ZoneInfo("America/New_York")).date(),
        )
        if future_date:
            return f"scheduled event date is in the future: {future_date}"
    match = NOT_LIVE_EVENT_PATTERN.search(evidence)
    return match.group(0) if match else None


def is_event_specific_replay_recipe(recipe: WebcastRecipe) -> bool:
    """Return whether a replay recipe points at one dated historical event.

    A recipe learned from a successful replay can contain the exact event URL
    that was clicked. Reusing that URL on a later run can resurrect an expired
    recording even when the IR page now exposes a newer replay.
    """
    evidence = " ".join(
        value
        for value in (
            recipe.target_text,
            recipe.target_href_path or "",
        )
        if value
    )
    if event_date_from_text(evidence):
        return True
    return bool(
        re.search(
            r"\b(?:q[1-4]|[1-4]q)[\s_-]*20\d{2}\b|"
            r"\b20\d{2}[\s_-]*(?:q[1-4]|[1-4]q)\b",
            evidence,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:earnings|results|conference|webcast|call)\b",
            evidence,
            re.IGNORECASE,
        )
    )


def non_earnings_event_reason(text: str) -> str | None:
    """Reject a playable investor-day style event when an earnings call is expected."""
    if EARNINGS_EVENT_CONTEXT_PATTERN.search(text):
        return None
    match = NON_EARNINGS_EVENT_PATTERN.search(text)
    return match.group(0) if match else None


def replay_page_number(*labels: str | None) -> int | None:
    """Extract an archive page number from visible text or accessible labels."""
    for raw_label in labels:
        label = " ".join(str(raw_label or "").split())
        if re.fullmatch(r"\d{1,2}", label):
            return int(label)
        match = re.fullmatch(r"(?:go\s+to\s+)?page\s+(\d{1,2})", label, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _load_env() -> None:
    load_project_env()


_load_env()


@dataclass(frozen=True)
class InvestorProfile:
    email: str
    password: str
    first_name: str
    last_name: str
    company: str
    phone_number: str = ""
    industry_affiliation: str = "Other"
    country: str = "United States"
    occupation: str = "Other"
    job_title: str = "Investor"
    city: str = "New York"
    state: str = "NY"
    attendee_type: str = "Other"
    other_option: str = "Other"
    q4_email: str = ""
    q4_password: str = ""
    q4_first_name: str = ""
    q4_last_name: str = ""

    @classmethod
    def from_env(cls) -> "InvestorProfile":
        email = os.getenv("WEBCAST_EMAIL", "").strip()
        password = os.getenv("WEBCAST_PASSWORD", "").strip()
        first_name = os.getenv("WEBCAST_FIRST_NAME", "Private").strip()
        last_name = os.getenv("WEBCAST_LAST_NAME", "Investor").strip()
        return cls(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            company=os.getenv("WEBCAST_COMPANY", "Private Investor").strip(),
            phone_number=os.getenv("WEBCAST_PHONE", "").strip(),
            industry_affiliation=os.getenv(
                "WEBCAST_INDUSTRY_AFFILIATION",
                "Other",
            ).strip(),
            country=os.getenv("WEBCAST_COUNTRY", "United States").strip(),
            occupation=os.getenv("WEBCAST_OCCUPATION", "Other").strip(),
            job_title=os.getenv("WEBCAST_JOB_TITLE", "Investor").strip(),
            city=os.getenv("WEBCAST_CITY", "New York").strip(),
            state=os.getenv("WEBCAST_STATE", "NY").strip(),
            attendee_type=os.getenv("WEBCAST_ATTENDEE_TYPE", "Other").strip(),
            other_option=os.getenv("WEBCAST_OTHER_OPTION", "Other").strip(),
            q4_email=os.getenv("Q4_EMAIL", email).strip(),
            q4_password=os.getenv("Q4_PASSWORD", password).strip(),
            q4_first_name=os.getenv("Q4_FIRST_NAME", first_name).strip(),
            q4_last_name=os.getenv("Q4_LAST_NAME", last_name).strip(),
        )

    @property
    def full_name(self) -> str:
        return " ".join(
            value for value in (self.first_name, self.last_name) if value
        ).strip()


@dataclass
class WebcastDiscoveryResult:
    ticker: str
    ir_url: str
    success: bool
    clicked_text: str | None
    final_url: str | None
    playback_triggered: bool
    media_candidates: list[str]
    error: str | None = None
    recipe_id: int | None = None
    recipe_strategy: str | None = None
    learning_artifact_path: str | None = None
    discovery_only: bool = False
    discovered_url: str | None = None
    target_identity_verified: bool = False
    event_identity: dict[str, Any] | None = None
    retry_state: str | None = None
    schedule_observation: dict[str, Any] | None = None


@dataclass(frozen=True)
class HumanPageAssessment:
    """A fresh, current-tab-only classification after the human returns."""

    state: str
    reason: str | None = None


def is_media_candidate_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if any(hostname == blocked or hostname.endswith(f".{blocked}") for blocked in NON_MEDIA_HOSTS):
        return False
    if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"} and parsed.path.startswith("/s/"):
        return False
    if NON_PLAYBACK_MEDIA_PATH_PATTERN.search(parsed.path):
        return False
    if EXPIRED_MEDIA_PATH_PATTERN.search(parsed.path):
        return False
    return bool(MEDIA_URL_PATTERN.search(parsed.path))


def default_chromium_executable() -> str | None:
    env_path = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
    if env_path:
        return env_path

    for path in COMMON_CHROMIUM_EXECUTABLES:
        if Path(path).exists():
            return path
    return None


def is_playback_control_label(label: str) -> bool:
    """Reject navigation lookalikes while keeping explicit webcast controls."""
    normalized = " ".join(label.split())
    if not normalized or NON_PLAYBACK_CONTROL_PATTERN.search(normalized):
        return False
    # A bare "Watch" is commonly a product-navigation label (notably on
    # Apple IR pages). Event rows contribute surrounding title/date text, so
    # genuine webcast actions still carry enough context to pass below.
    if normalized.casefold() == "watch":
        return False
    if re.search(
        r"\b(?:play|listen|start|unmute|watch|enter|replay|audio|view\s+now)\b|▶",
        normalized,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(r"\bjoin\b", normalized, re.IGNORECASE)
        and re.search(
            r"\b(?:webcast|call|event|live|earnings|presentation)\b",
            normalized,
            re.IGNORECASE,
        )
    )


def is_direct_player_url(url: str) -> bool:
    """Return whether a URL is an actual direct player, not a provider home page."""
    host = domain_for_url(url)
    if host.endswith("youtu.be"):
        return bool(urlparse(url).path.strip("/"))
    if not (host == "youtube.com" or host.endswith(".youtube.com")):
        return False
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    if path in {"/watch", "/live"}:
        return bool(parsed.query and re.search(r"(?:^|&)v=[^&]+", parsed.query, re.IGNORECASE)) or path == "/live"
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in ("/embed", "/live", "/shorts")
    )


def is_webcast_player_url(url: str) -> bool:
    """Recognize provider player pages, including Q4 attendee URLs."""
    if is_direct_player_url(url):
        return True
    parsed = urlparse(url)
    if (
        (parsed.hostname or "").lower().endswith("choruscall.com")
        and parsed.path.lower().rstrip("/").endswith("/mediaframe/webcast.html")
        and not re.search(r"(?:^|[?&])(?:webcastid|eventid|id)=[^&]+", parsed.query, re.IGNORECASE)
    ):
        return False
    return bool(
        parsed.netloc
        and re.search(
            r"/(?:attendee|starthere|mediaframe|player|webcast|replay|mmc)(?:/|$)",
            parsed.path,
            re.IGNORECASE,
        )
    )


def is_open_exchange_registration_url(url: str) -> bool:
    """Recognize Open Exchange's provider-level registration surface."""
    return bool(OPEN_EXCHANGE_REGISTRATION_URL_PATTERN.match(str(url or "").strip()))


def is_non_playback_surface_url(url: str) -> bool:
    """Reject app stores and software catalogs that expose play-like labels."""
    parsed = urlparse(str(url or ""))
    hostname = (parsed.hostname or "").lower()
    if any(
        hostname == host or hostname.endswith(f".{host}")
        for host in NON_PLAYBACK_SURFACE_HOSTS
    ):
        return True
    return bool(NON_PLAYBACK_SURFACE_PATH_PATTERN.search(parsed.path))


def is_non_playback_product_surface_url(url: str, label: str = "") -> bool:
    """Reject product-catalog navigation links that contain play-like words."""
    parsed = urlparse(str(url or ""))
    if re.search(r"/application-pages(?:/|$)", parsed.path, re.IGNORECASE):
        return True
    # Product and solution URL namespaces are navigation surfaces even when
    # their visible title contains words such as "audio" or "video". Requiring
    # a matching label allowed links like "Audio Gate Drivers" to be selected
    # as replay candidates on otherwise sparse IR pages.
    if NON_PLAYBACK_PRODUCT_PATH_PATTERN.search(parsed.path):
        return True
    if not parsed.path:
        return bool(
            re.fullmatch(
                r"(?:audio\s+and\s+radio|products?|product\s+catalog|"
                r"system\s+solutions|application\s+pages|solutions?)",
                " ".join(str(label or "").split()),
                re.IGNORECASE,
            )
        )
    return False


def is_non_playback_home_url(url: str, label: str = "") -> bool:
    """Reject a company homepage link misidentified as a replay candidate."""
    parsed = urlparse(str(url or ""))
    return bool(
        parsed.path.rstrip("/") == ""
        and NON_PLAYBACK_HOME_LABEL_PATTERN.search(str(label or ""))
        and not re.search(
            r"\b(?:webcast|replay|watch|listen|play|audio|video)\b",
            str(label or ""),
            re.IGNORECASE,
        )
    )


def is_replay_proxy_link(
    url: str,
    label: str = "",
    *,
    type_hint: str = "",
    icon_control: bool = False,
) -> bool:
    """Accept a plausible video/audio link for downstream replay training.

    Replay training deliberately accepts conference and presentation webcasts,
    even when they are not earnings calls. Static legal documents are excluded
    separately because many IR pages place them next to the real webcast link.
    """
    normalized_url = str(url or "").strip()
    normalized_label = " ".join(str(label or "").split())
    normalized_type = str(type_hint or "").strip().lower()
    if not normalized_url:
        return False
    if is_non_replay_navigation_link(normalized_url, normalized_label):
        return False
    if is_non_playback_surface_url(normalized_url):
        return False
    if is_non_playback_product_surface_url(normalized_url, normalized_label):
        return False
    if is_non_playback_home_url(normalized_url, normalized_label):
        return False
    if NON_PLAYBACK_DOCUMENT_PATTERN.search(normalized_url):
        return False
    if normalized_type in {
        "application/pdf",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    } or normalized_type.startswith("application/vnd.openxmlformats"):
        return False

    parsed = urlparse(normalized_url)
    path = parsed.path.lower()
    if (
        (parsed.hostname or "").lower().endswith("choruscall.com")
        and path.rstrip("/").endswith("/mediaframe/webcast.html")
        and not re.search(r"(?:^|[?&])(?:webcastid|eventid|id)=[^&]+", parsed.query, re.IGNORECASE)
    ):
        return False
    if (
        (parsed.hostname or "").lower().endswith("youtube.com")
        and not is_direct_player_url(normalized_url)
    ) or (
        (parsed.hostname or "").lower().endswith("youtu.be")
        and not is_direct_player_url(normalized_url)
    ):
        return False
    if "/static-files/" in path and REPLAY_PROXY_DOCUMENT_PATTERN.search(normalized_label):
        return False
    if is_media_candidate_url(normalized_url) or is_webcast_player_url(normalized_url):
        return True
    if normalized_type.startswith(("audio/", "video/")):
        return True
    return bool(REPLAY_PROXY_LINK_PATTERN.search(normalized_label) or icon_control)


def is_audio_priming_player_url(url: str) -> bool:
    host = domain_for_url(url)
    if is_direct_player_url(url):
        return True
    return host == "media-server.com" or host.endswith(".media-server.com")


def is_nonessential_popup_url(url: str) -> bool:
    host = domain_for_url(url)
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in NONESSENTIAL_POPUP_HOST_SUFFIXES
    )


def archive_navigation_url(page_url: str, candidates: tuple[WebcastCandidate, ...]) -> str | None:
    """Return the best same-site archive menu URL, if this page exposes one."""
    source_domain = domain_for_url(page_url)
    scored: list[tuple[int, str]] = []
    for candidate in candidates:
        if candidate.tag_name != "a" or not candidate.href_path:
            continue
        label = " ".join(
            value for value in (candidate.text, candidate.aria_label, candidate.title) if value
        ).lower()
        candidate_url = urljoin(page_url, candidate.href_path)
        if domain_for_url(candidate_url) != source_domain:
            continue
        score = sum(points for term, points in ARCHIVE_NAVIGATION_TERMS if term in label)
        # Some issuer templates expose only a plain Events menu. Keep this
        # exact-label bonus separate so News & Events does not outrank a
        # stronger event-calendar path through substring matching.
        if candidate.text.strip().lower() == "events" and urlparse(candidate_url).path.rstrip("/") == "/events":
            score += 55
        if ARCHIVE_NAVIGATION_PATH_PATTERN.search(urlparse(candidate_url).path):
            score += 110
        if score <= 0:
            continue
        scored.append((score, candidate_url))

    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def provider_archive_navigation_url(page_url: str) -> str | None:
    """Return a known same-site archive entrypoint when the article has no event link."""
    path = KNOWN_PROVIDER_ARCHIVE_PATHS.get(domain_for_url(page_url))
    return urljoin(page_url, path) if path else None


def access_fallback_urls(page_url: str) -> tuple[str, ...]:
    """Return a short, explicit list of public entrypoint alternatives.

    A 403 can be produced by a CDN challenge before the IR DOM is available.
    These alternatives handle known canonical-domain aliases and provider
    route changes, while avoiding broad URL guessing or security bypasses.
    """
    parsed = urlparse(page_url)
    host = (parsed.hostname or "").lower()
    candidates: list[str] = []

    def add(hostname: str, path: str | None = None) -> None:
        if not hostname or (hostname == host and path is None):
            return
        candidates.append(
            urlunparse(
                (
                    parsed.scheme or "https",
                    hostname,
                    path if path is not None else parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
        )

    if host == "www.garmin.com":
        add("investors.garmin.com")
    elif host == "investors.garmin.com":
        add("www.garmin.com")

    if host == "investor.qualcomm.com" and "events-disclaimer" in parsed.path:
        add(host, parsed.path.replace("events-disclaimer", "events", 1))

    fallback_host = KNOWN_ACCESS_FALLBACK_HOSTS.get(host)
    if fallback_host:
        add(fallback_host)

    # Preserve order while removing duplicate routes.
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate != page_url))
