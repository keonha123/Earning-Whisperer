from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from dotenv import dotenv_values

from .webcast_learning import (
    LearningSnapshot,
    OpenAIVisionSelector,
    WebcastCandidate,
    WebcastRecipe,
    EVENT_DATE_PATTERN,
    MONTH_NUMBERS,
    artifact_paths,
    choose_heuristic_candidate,
    domain_for_url,
    make_generalized_patterns,
    make_recipe,
    write_snapshot_metadata,
)


DATA_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DATA_PIPELINE_ROOT.parent

WEBCAST_TEXT_PATTERN = re.compile(
    r"Webcast|Listen|Join|Audio|Replay|Presentation|Event",
    re.IGNORECASE,
)
PLAY_TEXT_PATTERN = re.compile(
    r"\b(?:Play|Listen|Start|Unmute|Watch|Join|Enter|Replay)\b|▶",
    re.IGNORECASE,
)
NON_PLAYBACK_CONTROL_PATTERN = re.compile(
    r"\b(?:download|career|job|overview|learn more|register|sign up|shop)\b|"
    r"\bjoin (?:our team|us)\b",
    re.IGNORECASE,
)
REGISTRATION_EMAIL_ERROR_PATTERN = re.compile(
    r"please enter a valid e-?mail address|invalid e-?mail(?: address)?",
    re.IGNORECASE,
)
REGISTRATION_BARRIER_PATTERN = re.compile(
    r"hcaptcha|recaptcha|captcha|acceptance of the .* terms of use|"
    r"privacy policy.*this field is required",
    re.IGNORECASE,
)
ALREADY_REGISTERED_PATTERN = re.compile(
    r"already\s+registered|login\s+instructions|receive\s+an\s+email[\s\w-]*login",
    re.IGNORECASE,
)
REGISTRATION_FORM_TEXT_PATTERN = re.compile(
    r"(?:first\s+name|last\s+name|email\s+address|company|organization)"
    r"[\s\S]{0,240}(?:register|submit|enter|join)|"
    r"(?:register|submit|enter|join)[\s\S]{0,240}"
    r"(?:first\s+name|last\s+name|email\s+address|company|organization)",
    re.IGNORECASE,
)
Q4_EVENT_GATE_PATTERN = re.compile(
    r"register\s+for\s+event|register\s+with\s+a\s+q4\s+account|"
    r"continue\s+with\s+q4",
    re.IGNORECASE,
)
EXPIRED_EVENT_PATTERN = re.compile(
    r"(?:recording|session|conference\s+website)[\s\S]{0,100}"
    r"(?:not\s+available|no\s+longer\s+available|expired)",
    re.IGNORECASE,
)
NOT_LIVE_EVENT_PATTERN = re.compile(
    r"(?:entry|access|registration)[\s\S]{0,100}"
    r"(?:not\s+yet\s+available|come\s+back\s+closer|has\s+not\s+started)|"
    r"(?:live\s+presentation|webcast|event)[\s\S]{0,100}"
    r"(?:not\s+yet\s+available|has\s+not\s+started)",
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
    r"this request was blocked by our security service|error\s*15|powered by imperva",
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
    r"\.(?:pdf|docx?|xlsx?|pptx?)(?:$|[?#])",
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
REPLAY_ARCHIVE_VIEW_PATTERN = re.compile(
    r"^\s*(?:past|previous|archived)\s+(?:events?|webcasts?|calls?)\s*$",
    re.IGNORECASE,
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
    ("events and presentations", 50),
    ("events & presentations", 50),
)
KNOWN_PROVIDER_ARCHIVE_PATHS = {
    "ir.thermofisher.com": "/investors/news-events/events/default.aspx",
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
class InvestorProfile:
    email: str
    password: str
    first_name: str
    last_name: str
    company: str
    industry_affiliation: str = "Other"
    country: str = "United States"
    occupation: str = "Other"
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
            industry_affiliation=os.getenv(
                "WEBCAST_INDUSTRY_AFFILIATION",
                "Other",
            ).strip(),
            country=os.getenv("WEBCAST_COUNTRY", "United States").strip(),
            occupation=os.getenv("WEBCAST_OCCUPATION", "Other").strip(),
            q4_email=os.getenv("Q4_EMAIL", email).strip(),
            q4_password=os.getenv("Q4_PASSWORD", password).strip(),
            q4_first_name=os.getenv("Q4_FIRST_NAME", first_name).strip(),
            q4_last_name=os.getenv("Q4_LAST_NAME", last_name).strip(),
        )


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


def is_media_candidate_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if any(hostname == blocked or hostname.endswith(f".{blocked}") for blocked in NON_MEDIA_HOSTS):
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
    if re.search(
        r"\b(?:play|listen|start|unmute|watch|enter|replay|audio)\b|▶",
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
    host = domain_for_url(url)
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in DIRECT_PLAYER_HOST_SUFFIXES)


def is_audio_priming_player_url(url: str) -> bool:
    host = domain_for_url(url)
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in AUDIO_PRIMING_PLAYER_HOST_SUFFIXES
    )


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
        score = sum(points for term, points in ARCHIVE_NAVIGATION_TERMS if term in label)
        if score <= 0:
            continue
        candidate_url = urljoin(page_url, candidate.href_path)
        if domain_for_url(candidate_url) != source_domain:
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


class BrowserWebcastAgent:
    def __init__(
        self,
        ticker: str,
        ir_url: str,
        *,
        headless: bool = True,
        storage_state_path: str | None = None,
        save_storage_state_path: str | None = None,
        hold_seconds: float = 0,
        executable_path: str | None = None,
        profile: InvestorProfile | None = None,
        target_year: int | None = None,
        target_quarter: str | None = None,
    ) -> None:
        self.ticker = ticker.upper()
        self.ir_url = ir_url
        self.headless = headless
        self.storage_state_path = storage_state_path or os.getenv(
            "WEBCAST_STORAGE_STATE",
            str(DATA_PIPELINE_ROOT / ".state" / "q4_auth.json"),
        )
        self.save_storage_state_path = save_storage_state_path or self.storage_state_path
        self.hold_seconds = hold_seconds
        self.target_year = target_year
        self.target_quarter = target_quarter
        self.executable_path = executable_path or default_chromium_executable()
        self.profile = profile or InvestorProfile.from_env()
        requested_lifecycle = os.getenv("WEBCAST_LIFECYCLE", "unknown").strip().lower()
        self.lifecycle = requested_lifecycle if requested_lifecycle in RECIPE_LIFECYCLES else "unknown"
        manual_ready_file = os.getenv("WEBCAST_MANUAL_READY_FILE", "").strip()
        self.manual_ready_path = Path(manual_ready_file) if manual_ready_file else None
        self.manual_ready_timeout_seconds = float(
            os.getenv("WEBCAST_MANUAL_READY_TIMEOUT_SECONDS", "900")
        )
        self.page_ready_timeout_ms = max(
            1_000,
            int(float(os.getenv("WEBCAST_PAGE_READY_TIMEOUT_SECONDS", "20")) * 1_000),
        )
        self.playback_control_timeout_seconds = max(
            10.0,
            float(os.getenv("WEBCAST_CONTROL_TIMEOUT_SECONDS", "45")),
        )
        self.registration_timeout_seconds = max(
            10.0,
            float(os.getenv("WEBCAST_REGISTRATION_TIMEOUT_SECONDS", "60")),
        )
        self.allow_registration_submission = (
            os.getenv("WEBCAST_ALLOW_REGISTRATION_SUBMISSION", "false").lower() == "true"
        )
        self.target_navigation_timeout_seconds = max(
            3.0,
            float(os.getenv("WEBCAST_TARGET_NAVIGATION_TIMEOUT_SECONDS", "15")),
        )
        self.failure_hold_seconds = max(
            0.0,
            float(os.getenv("WEBCAST_FAILURE_HOLD_SECONDS", "0")),
        )
        self.generalized_learning_enabled = (
            os.getenv("WEBCAST_GENERALIZED_LEARNING_ENABLED", "true").lower() == "true"
        )
        self.replay_seek_seconds = max(
            0.0,
            float(os.getenv("WEBCAST_REPLAY_SEEK_SECONDS", "120")),
        )
        playback_ready_file = os.getenv("WEBCAST_PLAYBACK_READY_FILE", "").strip()
        self.playback_ready_path = Path(playback_ready_file) if playback_ready_file else None
        active_player_url_file = os.getenv(
            "WEBCAST_ACTIVE_PLAYER_URL_FILE",
            "",
        ).strip()
        self.active_player_url_path = (
            Path(active_player_url_file) if active_player_url_file else None
        )
        media_candidates_file = os.getenv(
            "WEBCAST_MEDIA_CANDIDATES_FILE",
            "",
        ).strip()
        self.media_candidates_path = (
            Path(media_candidates_file) if media_candidates_file else None
        )
        self.media_candidates: list[str] = []
        self._active_recipe: WebcastRecipe | None = None
        self._recipe_origin: str | None = None
        self._learning_snapshot: LearningSnapshot | None = None
        self._vision_selector = OpenAIVisionSelector()
        self._page_barrier: str | None = None
        self._page_http_status: int | None = None
        self._registration_target_page: Any | None = None
        self._registration_failure_error: str | None = None
        self._not_live_reason: str | None = None
        self._direct_audio_primed_urls: set[str] = set()
        self._watched_page_ids: set[int] = set()

    async def run(self) -> WebcastDiscoveryResult:
        try:
            from playwright.async_api import (
                TimeoutError as PlaywrightTimeoutError,
                async_playwright,
            )
        except ImportError as exc:
            return WebcastDiscoveryResult(
                ticker=self.ticker,
                ir_url=self.ir_url,
                success=False,
                clicked_text=None,
                final_url=None,
                playback_triggered=False,
                media_candidates=[],
                error=f"playwright is not installed: {exc}",
            )

        self._clear_recipe_context()
        async with async_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "args": [
                    "--no-user-gesture-required",
                    "--autoplay-policy=no-user-gesture-required",
                    # A few IR hosts return malformed HTTP/2 responses to Chromium
                    # while serving the same archive normally over HTTP/1.1.
                    "--disable-http2",
                ],
            }
            if not self.headless:
                # Docker Chromium is displayed through the host's XWayland server.
                # Keep the window on-screen and avoid GPU compositing, which can render
                # as a transparent surface on that path.
                launch_options["args"].extend(
                    [
                        "--disable-gpu",
                        "--disable-gpu-compositing",
                        "--window-position=80,60",
                        "--window-size=1280,900",
                    ]
                )
            if self.executable_path:
                launch_options["executable_path"] = self.executable_path

            browser = await playwright.chromium.launch(**launch_options)
            try:
                context_options = self._context_options()
                context = await browser.new_context(**context_options)
                context.on("page", self._attach_media_watchers)
                verified_page = await self._try_verified_player_fallback_in_context(
                    context,
                    self.ir_url,
                    PlaywrightTimeoutError,
                )
                if verified_page:
                    self._signal_playback_ready(verified_page.url)
                    await self._save_storage_state(context)
                    if self.hold_seconds > 0:
                        await asyncio.sleep(self.hold_seconds)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=True,
                        clicked_text="verified player shortcut",
                        final_url=verified_page.url,
                        playback_triggered=True,
                        media_candidates=self.media_candidates,
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                    )

                if self._not_live_reason:
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=None,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"NOT_LIVE_YET {self._not_live_reason}",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                    )

                page = await self._open_ir_page(context)

                manual_error = await self._wait_for_manual_ready(page)
                if manual_error:
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=manual_error,
                    )

                if self._page_barrier:
                    self._learning_snapshot = await self._capture_learning_snapshot(page)
                    fallback_page = await self._try_verified_player_fallback(
                        page,
                        PlaywrightTimeoutError,
                    )
                    if fallback_page:
                        self._signal_playback_ready(fallback_page.url)
                        await self._save_storage_state(context)
                        if self.hold_seconds > 0:
                            await asyncio.sleep(self.hold_seconds)
                        return WebcastDiscoveryResult(
                            ticker=self.ticker,
                            ir_url=self.ir_url,
                            success=True,
                            clicked_text="verified player fallback",
                            final_url=fallback_page.url,
                            playback_triggered=True,
                            media_candidates=self.media_candidates,
                            recipe_id=self._recipe_id(),
                            recipe_strategy=self._recipe_strategy(),
                            learning_artifact_path=self._artifact_path(),
                        )
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"page access blocked: {self._page_barrier}",
                        learning_artifact_path=self._artifact_path(),
                    )

                missing_resource = await self._wait_for_missing_resource(page)
                if missing_resource:
                    await self._capture_failure_snapshot(page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"RESOURCE_NOT_FOUND {missing_resource}",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                not_live_reason = await self._detect_not_live_event(page)
                if not_live_reason:
                    await self._capture_failure_snapshot(page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"NOT_LIVE_YET {not_live_reason}",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                if is_direct_player_url(page.url):
                    playback_triggered = await self.trigger_media_playback(
                        page,
                        allow_control_scan=False,
                    )
                    if not playback_triggered:
                        await self._capture_failure_snapshot(page)
                        return WebcastDiscoveryResult(
                            ticker=self.ticker,
                            ir_url=self.ir_url,
                            success=False,
                            clicked_text="direct player",
                            final_url=page.url,
                            playback_triggered=False,
                            media_candidates=self.media_candidates,
                            error="direct player did not become active",
                            learning_artifact_path=self._artifact_path(),
                        )
                    self._signal_playback_ready(page.url)
                    await self._save_storage_state(context)
                    if self.hold_seconds > 0:
                        await asyncio.sleep(self.hold_seconds)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=True,
                        clicked_text="direct player",
                        final_url=page.url,
                        playback_triggered=True,
                        media_candidates=self.media_candidates,
                        learning_artifact_path=self._artifact_path(),
                    )

                found_el, page = await self.find_webcast_button_with_archive_fallback(page)
                if not found_el:
                    playback_reason = await self.detect_active_playback(page)
                    if playback_reason:
                        print(
                            f"[{self.ticker}] active playback detected: {playback_reason}",
                            flush=True,
                        )
                        self._signal_playback_ready(page.url)
                        if self.hold_seconds > 0:
                            await asyncio.sleep(self.hold_seconds)
                        return WebcastDiscoveryResult(
                            ticker=self.ticker,
                            ir_url=self.ir_url,
                            success=True,
                            clicked_text="active player",
                            final_url=page.url,
                            playback_triggered=True,
                            media_candidates=self.media_candidates,
                            learning_artifact_path=self._artifact_path(),
                        )
                    if await self._has_visible_media_element(page):
                        playback_triggered = await self.trigger_media_playback(page)
                        if playback_triggered:
                            self._signal_playback_ready(page.url)
                            if self.hold_seconds > 0:
                                await asyncio.sleep(self.hold_seconds)
                            return WebcastDiscoveryResult(
                                ticker=self.ticker,
                                ir_url=self.ir_url,
                                success=True,
                                clicked_text="media element",
                                final_url=page.url,
                                playback_triggered=True,
                                media_candidates=self.media_candidates,
                                learning_artifact_path=self._artifact_path(),
                            )
                    registration_barrier = await self._detect_registration_barrier(page)
                    if registration_barrier:
                        await self._capture_failure_snapshot(page)
                        return WebcastDiscoveryResult(
                            ticker=self.ticker,
                            ir_url=self.ir_url,
                            success=False,
                            clicked_text="registration form",
                            final_url=page.url,
                            playback_triggered=False,
                            media_candidates=self.media_candidates,
                            error=f"REGISTRATION_BLOCKED {registration_barrier}",
                            learning_artifact_path=self._artifact_path(),
                        )
                    if await self.has_registration_form(page):
                        clicked_text = "registration form"
                        print(f"[{self.ticker}] registration form detected", flush=True)
                        form_success = await self.handle_registration_form(
                            page,
                            PlaywrightTimeoutError,
                        )
                        page = self._registration_target_page or page
                        if not form_success:
                            await self._capture_failure_snapshot(page)
                            return WebcastDiscoveryResult(
                                ticker=self.ticker,
                                ir_url=self.ir_url,
                                success=False,
                                clicked_text=clicked_text,
                                final_url=page.url,
                                playback_triggered=False,
                                media_candidates=self.media_candidates,
                                error=self._registration_error(),
                                learning_artifact_path=self._artifact_path(),
                            )
                        playback_triggered = await self.trigger_media_playback(page)
                        if not playback_triggered:
                            not_live_reason = await self._detect_not_live_event(page)
                            missing_resource = await self._detect_missing_resource(page)
                            await self._capture_failure_snapshot(page)
                            return WebcastDiscoveryResult(
                                ticker=self.ticker,
                                ir_url=self.ir_url,
                                success=False,
                                clicked_text=clicked_text,
                                final_url=page.url,
                                playback_triggered=False,
                                media_candidates=self.media_candidates,
                                error=(
                                    f"NOT_LIVE_YET {not_live_reason}"
                                    if not_live_reason
                                    else f"RESOURCE_NOT_FOUND {missing_resource}"
                                    if missing_resource
                                    else "registration completed but playback was not detected"
                                ),
                                learning_artifact_path=self._artifact_path(),
                            )
                        self._signal_playback_ready(page.url)
                        await self._save_storage_state(context)
                        if self.hold_seconds > 0:
                            await asyncio.sleep(self.hold_seconds)
                        return WebcastDiscoveryResult(
                            ticker=self.ticker,
                            ir_url=self.ir_url,
                            success=True,
                            clicked_text=clicked_text,
                            final_url=page.url,
                            playback_triggered=playback_triggered,
                            media_candidates=self.media_candidates,
                            learning_artifact_path=self._artifact_path(),
                        )
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error="webcast button not found",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                # A newly learned selector must survive a clean context before it is trusted.
                if self._recipe_origin == "learned" and self._active_recipe:
                    await context.close()
                    context = await browser.new_context(**context_options)
                    context.on("page", self._attach_media_watchers)
                    page = await self._open_ir_page(context)
                    found_el, page = await self.find_webcast_button_with_archive_fallback(page)
                    if not found_el:
                        return WebcastDiscoveryResult(
                            ticker=self.ticker,
                            ir_url=self.ir_url,
                            success=False,
                            clicked_text=None,
                            final_url=page.url,
                            playback_triggered=False,
                            media_candidates=self.media_candidates,
                            error="learned recipe did not replay in a fresh browser context",
                            recipe_id=self._active_recipe.recipe_id,
                            recipe_strategy=self._active_recipe.strategy,
                            learning_artifact_path=self._artifact_path(),
                        )

                clicked_text = (await found_el.inner_text()).strip()
                if not clicked_text:
                    clicked_text = (
                        await found_el.evaluate(
                            """element => {
                                const container = element.closest('li, article, [class*="document" i]')
                                    || element;
                                return (container.innerText || element.getAttribute('title') || '')
                                    .replace(/\\s+/g, ' ').trim().slice(0, 160);
                            }"""
                        )
                    ).strip()
                clicked_href = (await found_el.get_attribute("href") or "").strip()
                clicked_base_url = page.url
                if clicked_href:
                    try:
                        clicked_base_url = await found_el.evaluate(
                            "element => element.ownerDocument.baseURI || location.href"
                        )
                    except Exception:
                        pass
                await found_el.scroll_into_view_if_needed()
                self._write_recipe_context()
                print(f"[{self.ticker}] clicking webcast candidate: {clicked_text[:120]}", flush=True)

                target_page = page
                source_url = page.url
                pages_before_click = tuple(context.pages)
                await found_el.click(force=True, timeout=8000)
                target_page = await self._wait_for_clicked_target(
                    context,
                    source_page=page,
                    source_url=source_url,
                    pages_before_click=pages_before_click,
                )
                target_is_source = target_page is page and str(page.url) == source_url
                target_is_blank_popup = target_page is not page and target_page.url in {"", "about:blank"}
                if (target_is_source or target_is_blank_popup) and clicked_href:
                    fallback_url = urljoin(clicked_base_url, clicked_href)
                    parsed_fallback = urlparse(fallback_url)
                    if (
                        parsed_fallback.scheme in {"http", "https"}
                        and fallback_url != source_url
                    ):
                        print(
                            f"[{self.ticker}] click produced no navigation; "
                            f"opening candidate href directly: {fallback_url}",
                            flush=True,
                        )
                        if target_is_blank_popup:
                            try:
                                await target_page.close()
                            except Exception:
                                pass
                        target_page = await context.new_page()
                        self._attach_media_watchers(target_page)
                        try:
                            await target_page.goto(
                                fallback_url,
                                wait_until="domcontentloaded",
                                timeout=self.page_ready_timeout_ms,
                            )
                        except Exception as exc:
                            if await target_page.locator("body").count() == 0:
                                raise
                            print(
                                f"[{self.ticker}] candidate href navigation timed out; "
                                f"inspecting rendered DOM: {str(exc)[:120]}",
                                flush=True,
                            )

                print(
                    f"[{self.ticker}] webcast target opened: {target_page.url}",
                    flush=True,
                )
                try:
                    await target_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=15000,
                    )
                except PlaywrightTimeoutError:
                    print(
                        f"[{self.ticker}] target load timed out; inspecting rendered DOM",
                        flush=True,
                    )
                await self._wait_for_dynamic_page(target_page)
                await self.accept_cookie_banners(target_page)

                embedded_link = await self._find_embedded_playback_link(target_page)
                if embedded_link:
                    embedded_href = (await embedded_link.get_attribute("href") or "").strip()
                    embedded_url = urljoin(target_page.url, embedded_href)
                    print(
                        f"[{self.ticker}] opening embedded webcast link from event detail: {embedded_url}",
                        flush=True,
                    )
                    try:
                        embedded_page = await context.new_page()
                        self._attach_media_watchers(embedded_page)
                        await embedded_page.goto(
                            embedded_url,
                            wait_until="domcontentloaded",
                            timeout=self.page_ready_timeout_ms,
                        )
                        target_page = embedded_page
                        try:
                            await target_page.wait_for_load_state(
                                "domcontentloaded",
                                timeout=15000,
                            )
                        except PlaywrightTimeoutError:
                            print(
                                f"[{self.ticker}] embedded player load timed out; inspecting rendered DOM",
                                flush=True,
                            )
                        await self._wait_for_dynamic_page(target_page)
                        await self.accept_cookie_banners(target_page)
                        print(
                            f"[{self.ticker}] embedded webcast target opened: {target_page.url}",
                            flush=True,
                        )
                    except Exception as exc:
                        print(
                            f"[{self.ticker}] embedded webcast link click skipped: {str(exc)[:120]}",
                            flush=True,
                        )

                expired_reason = await self._detect_expired_event(target_page)
                if expired_reason:
                    await self._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"EXPIRED_EVENT {expired_reason}",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                not_live_reason = await self._detect_not_live_event(target_page)
                if not_live_reason:
                    await self._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"NOT_LIVE_YET {not_live_reason}",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                missing_resource = await self._detect_missing_resource(target_page)
                if missing_resource:
                    await self._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"RESOURCE_NOT_FOUND {missing_resource}",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                registration_barrier = await self._detect_registration_barrier(target_page)
                if registration_barrier:
                    await self._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=f"REGISTRATION_BLOCKED {registration_barrier}",
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                form_success = await self.handle_registration_form(
                    target_page,
                    PlaywrightTimeoutError,
                )
                target_page = self._registration_target_page or target_page
                if not form_success:
                    await self._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=self._registration_error(),
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )

                playback_triggered = await self.trigger_media_playback(target_page)
                if not playback_triggered:
                    not_live_reason = await self._detect_not_live_event(target_page)
                    missing_resource = await self._detect_missing_resource(target_page)
                    await self._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=self.ticker,
                        ir_url=self.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=self.media_candidates,
                        error=(
                            f"NOT_LIVE_YET {not_live_reason}"
                            if not_live_reason
                            else f"RESOURCE_NOT_FOUND {missing_resource}"
                            if missing_resource
                            else "webcast opened but playback was not detected"
                        ),
                        recipe_id=self._recipe_id(),
                        recipe_strategy=self._recipe_strategy(),
                        learning_artifact_path=self._artifact_path(),
                    )
                self._signal_playback_ready(target_page.url)
                await self._save_storage_state(context)

                if self.hold_seconds > 0:
                    await asyncio.sleep(self.hold_seconds)

                return WebcastDiscoveryResult(
                    ticker=self.ticker,
                    ir_url=self.ir_url,
                    success=True,
                    clicked_text=clicked_text,
                    final_url=target_page.url,
                    playback_triggered=playback_triggered,
                    media_candidates=self.media_candidates,
                    recipe_id=self._recipe_id(),
                    recipe_strategy=self._recipe_strategy(),
                    learning_artifact_path=self._artifact_path(),
                )
            except Exception as exc:
                return WebcastDiscoveryResult(
                    ticker=self.ticker,
                    ir_url=self.ir_url,
                    success=False,
                    clicked_text=None,
                    final_url=None,
                    playback_triggered=False,
                    media_candidates=self.media_candidates,
                    error=str(exc),
                    recipe_id=self._recipe_id(),
                    recipe_strategy=self._recipe_strategy(),
                    learning_artifact_path=self._artifact_path(),
                )
            finally:
                await browser.close()

    async def _try_verified_player_fallback(
        self,
        source_page: Any,
        timeout_error: Any,
    ) -> Any | None:
        """Use an audio-verified external player when the IR entry page is blocked."""
        return await self._try_verified_player_fallback_in_context(
            source_page.context,
            source_page.url,
            timeout_error,
        )

    async def _try_verified_player_fallback_in_context(
        self,
        context: Any,
        source_url: str,
        timeout_error: Any,
    ) -> Any | None:
        """Open a verified external player before or after an IR page barrier."""
        if self.lifecycle != "replay":
            return None

        for recipe in self._load_verified_recipes(source_url):
            verified_url = str(recipe.evidence.get("verified_player_url") or "").strip()
            parsed_url = urlparse(verified_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                continue

            target_page = await context.new_page()
            self._attach_media_watchers(target_page)
            self._active_recipe = recipe
            self._recipe_origin = "verified"
            self._write_recipe_context()
            print(
                f"[{self.ticker}] opening verified player route: {verified_url}",
                flush=True,
            )
            try:
                try:
                    await target_page.goto(
                        verified_url,
                        wait_until="commit",
                        timeout=self.page_ready_timeout_ms,
                    )
                    try:
                        await target_page.wait_for_load_state(
                            "domcontentloaded",
                            timeout=min(self.page_ready_timeout_ms, 5000),
                        )
                    except Exception:
                        pass
                except Exception as exc:
                    if await target_page.locator("body").count() == 0:
                        print(
                            f"[{self.ticker}] verified player unavailable: {str(exc)[:160]}",
                            flush=True,
                        )
                        await target_page.close()
                        continue
                    print(
                        f"[{self.ticker}] verified player navigation timed out; inspecting DOM",
                        flush=True,
                    )

                await asyncio.sleep(1)
                await self._wait_for_dynamic_page(target_page)
                await self.accept_cookie_banners(target_page)
                self._registration_target_page = None
                if await self._detect_access_barrier(target_page):
                    await target_page.close()
                    continue
                not_live_reason = await self._detect_not_live_event(target_page)
                if not_live_reason:
                    self._not_live_reason = not_live_reason
                    await target_page.close()
                    return None

                form_success = await self.handle_registration_form(
                    target_page,
                    timeout_error,
                )
                target_page = self._registration_target_page or target_page
                if not form_success:
                    await target_page.close()
                    continue

                if await self.trigger_media_playback(target_page, allow_control_scan=False):
                    print(
                        f"[{self.ticker}] verified player fallback became audible-ready",
                        flush=True,
                    )
                    return target_page
            except Exception as exc:
                print(
                    f"[{self.ticker}] verified player fallback failed: {str(exc)[:160]}",
                    flush=True,
                )
            try:
                if not target_page.is_closed():
                    await target_page.close()
            except Exception:
                pass
        return None

    def _context_options(self) -> dict[str, Any]:
        context_options: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 1000},
            "locale": "en-US",
        }
        if self.storage_state_path and Path(self.storage_state_path).exists():
            context_options["storage_state"] = self.storage_state_path
        return context_options

    async def _open_ir_page(self, context: Any) -> Any:
        page = await context.new_page()
        self._attach_media_watchers(page)
        print(f"[{self.ticker}] opening IR page: {self.ir_url}", flush=True)
        # Investor pages commonly leave analytics/media requests pending even
        # though their interactive DOM is already available.
        navigation_timed_out = False
        try:
            response = await asyncio.wait_for(
                page.goto(
                    self.ir_url,
                    wait_until="commit",
                    timeout=self.page_ready_timeout_ms,
                ),
                timeout=(self.page_ready_timeout_ms / 1000) + 3,
            )
            self._page_http_status = response.status if response else None
            try:
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=min(self.page_ready_timeout_ms, 5000),
                )
            except Exception:
                print(
                    f"[{self.ticker}] DOMContentLoaded delayed; inspecting rendered DOM",
                    flush=True,
                )
        except asyncio.TimeoutError:
            navigation_timed_out = True
            print(
                f"[{self.ticker}] IR navigation exceeded the local timeout; "
                "checking verified player fallback",
                flush=True,
            )
        except Exception as exc:
            if await page.locator("body").count() == 0:
                raise
            print(f"[{self.ticker}] navigation timed out; inspecting rendered DOM: {str(exc)[:120]}", flush=True)
        await asyncio.sleep(0.5 if navigation_timed_out else 2)
        await self._wait_for_dynamic_page(page)
        if not navigation_timed_out:
            await self.accept_cookie_banners(page)
        self._page_barrier = await self._detect_access_barrier(page)
        if navigation_timed_out and not self._page_barrier:
            self._page_barrier = "IR navigation timeout"
        return page

    async def _wait_for_dynamic_page(self, page: Any) -> None:
        """Wait briefly when a provider exposes only a client-side loading shell."""
        try:
            body_text = (await page.locator("body").inner_text(timeout=1500))[:2500]
        except Exception:
            return
        if not DYNAMIC_LOADING_PATTERN.search(body_text):
            return

        wait_seconds = max(
            0.0,
            float(os.getenv("WEBCAST_DYNAMIC_PAGE_WAIT_SECONDS", "15")),
        )
        if wait_seconds <= 0:
            return
        print(
            f"[{self.ticker}] provider is still loading; waiting up to "
            f"{wait_seconds:g}s for the interactive page",
            flush=True,
        )
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            try:
                body_text = (await page.locator("body").inner_text(timeout=1500))[:2500]
            except Exception:
                continue
            if not DYNAMIC_LOADING_PATTERN.search(body_text):
                print(f"[{self.ticker}] provider loading shell resolved", flush=True)
                return

    async def _detect_access_barrier(self, page: Any) -> str | None:
        if self._page_http_status in HTTP_ACCESS_BARRIER_STATUSES:
            return f"HTTP {self._page_http_status}"
        try:
            body_text = (await page.locator("body").inner_text(timeout=3000))[:2000]
        except Exception:
            return None
        match = ACCESS_BARRIER_PATTERN.search(body_text)
        return match.group(0) if match else None

    async def _detect_registration_barrier(self, page: Any) -> str | None:
        """Recognize anti-bot or mandatory consent gates before form submission."""
        for frame in page.frames:
            try:
                body_text = (await frame.locator("body").inner_text(timeout=3000))[:8000]
            except Exception:
                continue
            if not REGISTRATION_BARRIER_PATTERN.search(body_text):
                continue
            if re.search(r"hcaptcha|recaptcha|captcha", body_text, re.IGNORECASE):
                return "anti-bot captcha requires manual verification"
            return "mandatory terms/privacy consent is required"
        return None

    async def _detect_expired_event(self, page: Any) -> str | None:
        """Separate retired recordings from pages whose player controls are missing."""
        for frame in page.frames:
            try:
                body_text = (await frame.locator("body").inner_text(timeout=3000))[:6000]
            except Exception:
                continue
            match = EXPIRED_EVENT_PATTERN.search(body_text)
            if match:
                return match.group(0)
        return None

    async def _detect_not_live_event(self, page: Any) -> str | None:
        """Recognize scheduled webcasts that expose a page before playback begins."""
        for frame in page.frames:
            try:
                body_text = (await frame.locator("body").inner_text(timeout=3000))[:6000]
            except Exception:
                continue
            match = NOT_LIVE_EVENT_PATTERN.search(body_text)
            if match:
                return match.group(0)
            future_reason = future_event_date_reason(body_text)
            if future_reason:
                return f"scheduled event date is in the future: {future_reason}"
        return None

    async def _detect_missing_resource(self, page: Any) -> str | None:
        """Separate dead provider URLs from pages that contain an undiscovered player."""
        if MISSING_RESOURCE_URL_PATTERN.search(str(page.url)):
            return f"page URL indicates a missing resource: {page.url}"
        for frame in page.frames:
            try:
                body_text = (await frame.locator("body").inner_text(timeout=3000))[:6000]
            except Exception:
                continue
            match = RESOURCE_NOT_FOUND_PATTERN.search(body_text)
            if match:
                return match.group(0)
        return None

    async def _wait_for_missing_resource(self, page: Any) -> str | None:
        """Give slow SPA video routes time to render their terminal 404 state."""
        missing_resource = await self._detect_missing_resource(page)
        if missing_resource:
            return missing_resource
        page_url = str(page.url).lower()
        if "rev.vbrick.com" not in page_url and "#/videos/" not in page_url:
            return None
        for _ in range(6):
            await asyncio.sleep(1)
            missing_resource = await self._detect_missing_resource(page)
            if missing_resource:
                return missing_resource
        return None

    async def _wait_for_manual_ready(self, page: Any) -> str | None:
        """Let a human complete consent/login/anti-bot checks in a visible browser first."""
        if not self.manual_ready_path:
            return None

        print(
            f"[{self.ticker}] MANUAL_BROWSER_READY path={self.manual_ready_path} url={page.url}",
            flush=True,
        )
        deadline = asyncio.get_running_loop().time() + max(1, self.manual_ready_timeout_seconds)
        while asyncio.get_running_loop().time() < deadline:
            if self.manual_ready_path.exists():
                await self.accept_cookie_banners(page)
                self._page_barrier = await self._detect_access_barrier(page)
                return None
            await asyncio.sleep(0.5)
        return f"manual browser confirmation timed out after {self.manual_ready_timeout_seconds:g}s"

    def _signal_playback_ready(self, active_url: str | None = None) -> None:
        if self.active_player_url_path and active_url:
            self.active_player_url_path.parent.mkdir(parents=True, exist_ok=True)
            self.active_player_url_path.write_text(active_url, encoding="utf-8")
        if self.media_candidates_path:
            self.media_candidates_path.parent.mkdir(parents=True, exist_ok=True)
            self.media_candidates_path.write_text(
                json.dumps(self.media_candidates, ensure_ascii=True),
                encoding="utf-8",
            )
        if self.playback_ready_path:
            self.playback_ready_path.parent.mkdir(parents=True, exist_ok=True)
            self.playback_ready_path.touch()
            print(f"[{self.ticker}] PLAYBACK_READY path={self.playback_ready_path}", flush=True)

    async def _save_storage_state(self, context: Any) -> None:
        if not self.save_storage_state_path:
            return
        path = Path(self.save_storage_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.wait_for(context.storage_state(path=str(path)), timeout=5)
            print(f"[{self.ticker}] browser session state saved", flush=True)
        except Exception as exc:
            print(
                f"[{self.ticker}] browser session state save skipped: "
                f"{str(exc)[:120] or 'timeout'}",
                flush=True,
            )

    def _attach_media_watchers(self, page: Any) -> None:
        page_id = id(page)
        if page_id in self._watched_page_ids:
            return
        self._watched_page_ids.add(page_id)

        def remember_url(url: str) -> None:
            if is_media_candidate_url(url) and url not in self.media_candidates:
                self.media_candidates.append(url)

        page.on("request", lambda request: remember_url(request.url))

        def remember_response(response: Any) -> None:
            remember_url(response.url)
            if "registration/submit" in response.url.lower():
                print(
                    f"[{self.ticker}] registration response "
                    f"status={response.status} url={response.url}",
                    flush=True,
                )

        page.on("response", remember_response)

    async def accept_cookie_banners(self, page: Any) -> None:
        cookie_selectors = [
            "#onetrust-accept-btn-handler",
            ".onetrust-close-btn-handler",
            "button:has-text('Accept')",
            "button:has-text('Accept All')",
            "button:has-text('I Agree')",
            "button:has-text('Agree')",
        ]

        for candidate_page in self._playback_pages(page):
            if candidate_page is page or not is_nonessential_popup_url(str(candidate_page.url)):
                continue
            try:
                await candidate_page.close()
                print(
                    f"[{self.ticker}] dismissed nonessential survey tab: "
                    f"{candidate_page.url}",
                    flush=True,
                )
            except Exception:
                continue

        for candidate_page in self._playback_pages(page):
            for frame in candidate_page.frames:
                for selector in cookie_selectors:
                    try:
                        button = frame.locator(selector).first
                        if await button.count() > 0 and await button.is_visible():
                            await button.click(force=True)
                            await asyncio.sleep(0.3)
                            break
                    except Exception:
                        continue

                try:
                    body_text = await frame.locator("body").inner_text(timeout=1500)
                except Exception:
                    continue
                if not SURVEY_TEXT_PATTERN.search(body_text[:4000]):
                    continue

                survey_dismiss = frame.get_by_role(
                    "button",
                    name=re.compile(
                        r"^(?:no|no thanks|no, thanks|not now|maybe later|close)$",
                        re.IGNORECASE,
                    ),
                ).first
                try:
                    if await survey_dismiss.count() > 0 and await survey_dismiss.is_visible():
                        await survey_dismiss.click(force=True)
                        print(f"[{self.ticker}] dismissed survey prompt", flush=True)
                        await asyncio.sleep(0.3)
                        continue
                except Exception:
                    pass

                for selector in (
                    "[aria-label*='Close' i]",
                    "button[title*='Close' i]",
                ):
                    try:
                        close_button = frame.locator(selector).first
                        if await close_button.count() > 0 and await close_button.is_visible():
                            await close_button.click(force=True)
                            print(f"[{self.ticker}] dismissed survey prompt", flush=True)
                            await asyncio.sleep(0.3)
                            break
                    except Exception:
                        continue

    async def _wait_for_clicked_target(
        self,
        context: Any,
        *,
        source_page: Any,
        source_url: str,
        pages_before_click: tuple[Any, ...],
    ) -> Any:
        """Follow a click through popup creation and delayed provider redirects."""
        deadline = (
            asyncio.get_running_loop().time()
            + self.target_navigation_timeout_seconds
        )
        target_page = source_page
        stable_signature: tuple[int, str] | None = None
        stable_count = 0

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            await self.accept_cookie_banners(source_page)

            open_pages = []
            for candidate in context.pages:
                try:
                    if candidate.is_closed():
                        continue
                except Exception:
                    pass
                if is_nonessential_popup_url(str(candidate.url)):
                    continue
                self._attach_media_watchers(candidate)
                open_pages.append(candidate)

            new_pages = [
                candidate
                for candidate in open_pages
                if candidate not in pages_before_click
            ]
            if new_pages:
                target_page = new_pages[-1]
            elif str(source_page.url) != source_url:
                target_page = source_page

            target_url = str(target_page.url)
            meaningful_target = (
                target_page is source_page and target_url != source_url
            ) or (
                target_page is not source_page
                and target_url not in {"", "about:blank", source_url}
            )
            if meaningful_target:
                signature = (id(target_page), target_url)
                if signature == stable_signature:
                    stable_count += 1
                else:
                    stable_signature = signature
                    stable_count = 1
                if stable_count >= 2:
                    print(
                        f"[{self.ticker}] click target stabilized: {target_url}",
                        flush=True,
                    )
                    return target_page

        print(
            f"[{self.ticker}] click target settle timed out; "
            f"continuing with {target_page.url}",
            flush=True,
        )
        return target_page

    async def find_webcast_button(self, page: Any) -> Any | None:
        """Reuse an audio-verified recipe, or learn one from a visual/DOM snapshot."""
        print(f"[{self.ticker}] inspecting page for webcast controls: {page.url}", flush=True)
        for recipe in self._load_verified_recipes(page.url):
            button = await self._find_recipe_button(page, recipe)
            if button:
                self._active_recipe = recipe
                self._recipe_origin = "verified"
                print(f"[{self.ticker}] using verified recipe id={recipe.recipe_id}", flush=True)
                return button

        embedded_link = await self._find_embedded_playback_link(page)
        if embedded_link:
            print(f"[{self.ticker}] found embedded webcast link from surrounding document text", flush=True)
            return embedded_link

        snapshot = await self._capture_learning_snapshot(page)
        self._learning_snapshot = snapshot
        candidate, strategy, confidence, reason = await self._choose_learning_candidate(page, snapshot)
        if not candidate and await self._expand_replay_event_rows(page):
            print(
                f"[{self.ticker}] replay event row expanded; rescanning webcast controls",
                flush=True,
            )
            snapshot = await self._capture_learning_snapshot(page)
            self._learning_snapshot = snapshot
            candidate, strategy, confidence, reason = await self._choose_learning_candidate(
                page,
                snapshot,
            )
        if not candidate:
            return None

        recipe = make_recipe(
            page.url,
            candidate,
            strategy=strategy,
            lifecycle=self.lifecycle,
            confidence=confidence,
            snapshot=snapshot,
            vision_reason=reason,
        )
        recipe.recipe_id = self._save_recipe(recipe)
        self._active_recipe = recipe
        self._recipe_origin = "learned"
        print(
            f"[{self.ticker}] learned {strategy} recipe "
            f"candidate={candidate.candidate_id} confidence={confidence:.2f}",
            flush=True,
        )
        return await self._find_recipe_button(page, recipe)

    async def _find_embedded_playback_link(self, page: Any) -> Any | None:
        """Find icon-only webcast anchors whose label lives in a sibling document span."""
        for frame in page.frames:
            links = frame.locator("a[href]")
            try:
                count = await links.count()
            except Exception:
                continue
            for index in range(count):
                link = links.nth(index)
                try:
                    href = (await link.get_attribute("href") or "").strip()
                    if not href:
                        continue
                    visible = await link.is_visible()
                    icon = link.locator(
                        "[class*='webcast' i], [class*='audio' i], [class*='play' i]"
                    ).first
                    icon_visible = await icon.count() > 0 and await icon.is_visible()
                    link_label = " ".join(
                        value
                        for value in (
                            await link.inner_text(),
                            await link.get_attribute("aria-label"),
                            await link.get_attribute("title"),
                        )
                        if value
                    )
                    if not visible and not icon_visible:
                        continue
                    if not icon_visible and not re.search(
                        r"\b(?:listen|webcast|audio|replay|play|watch)\b",
                        link_label,
                        re.IGNORECASE,
                    ):
                        continue
                    frame_base_url = frame.url if urlparse(frame.url).scheme in {"http", "https"} else page.url
                    resolved_href = urljoin(frame_base_url, href)
                    if resolved_href.rstrip("/") == str(page.url).rstrip("/"):
                        continue
                    if NON_PLAYBACK_DOCUMENT_PATTERN.search(resolved_href):
                        continue
                    evidence = await link.evaluate(
                        """element => {
                            const container = element.closest('li, article')
                                || element.parentElement
                                || element;
                            return [
                                element.innerText,
                                element.getAttribute('aria-label'),
                                element.getAttribute('title'),
                                container.innerText,
                            ].filter(Boolean).join(' ');
                        }"""
                    )
                    if not re.search(
                        r"\b(?:listen|webcast|audio|replay|play|watch)\b",
                        evidence or "",
                        re.IGNORECASE,
                    ):
                        continue
                    if is_playback_control_label(evidence):
                        return link
                except Exception:
                    continue
        return None

    async def find_webcast_button_with_archive_fallback(self, page: Any) -> tuple[Any | None, Any]:
        """Try the supplied IR page, then one same-site recording archive when present."""
        await self._activate_replay_archive_view(page)
        button = await self.find_webcast_button(page)
        if button:
            return button, page

        snapshot = self._learning_snapshot
        archive_url = (
            archive_navigation_url(page.url, snapshot.candidates)
            if snapshot
            else None
        )
        if not archive_url:
            archive_url = provider_archive_navigation_url(page.url)
        if not archive_url or archive_url == page.url:
            return None, page

        print(f"[{self.ticker}] no playback control; opening archive fallback: {archive_url}", flush=True)
        try:
            # Archive pages often keep analytics/media requests open after their
            # interactive DOM is ready, so waiting for the full load event stalls
            # playback discovery unnecessarily.
            response = await page.goto(
                archive_url,
                wait_until="domcontentloaded",
                timeout=self.page_ready_timeout_ms,
            )
            self._page_http_status = response.status if response else None
            await asyncio.sleep(2)
            await self.accept_cookie_banners(page)
            self._page_barrier = await self._detect_access_barrier(page)
            if self._page_barrier:
                return None, page
        except Exception as exc:
            if await page.locator("body").count() == 0:
                print(f"[{self.ticker}] archive fallback unavailable: {str(exc)[:160]}", flush=True)
                return None, page
            print(f"[{self.ticker}] archive navigation timed out; inspecting rendered DOM", flush=True)

        return await self.find_webcast_button(page), page

    async def _expand_replay_event_rows(self, page: Any) -> bool:
        """Expand hidden controls attached to past earnings-call rows."""
        if self.lifecycle != "replay":
            return False

        script = """() => {
            const compact = value => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 1200);
            const visible = element => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' &&
                    Number(style.opacity || 1) > 0 && rect.width > 2 && rect.height > 2;
            };
            const nthPath = element => {
                const parts = [];
                let current = element;
                for (let depth = 0; current && current.nodeType === Node.ELEMENT_NODE && depth < 8; depth += 1) {
                    if (current.id) {
                        parts.unshift(`#${CSS.escape(current.id)}`);
                        break;
                    }
                    const tag = current.tagName.toLowerCase();
                    const siblings = Array.from(current.parentElement?.children || []).filter(
                        sibling => sibling.tagName === current.tagName,
                    );
                    parts.unshift(`${tag}:nth-of-type(${Math.max(siblings.indexOf(current) + 1, 1)})`);
                    current = current.parentElement;
                }
                return parts.join(' > ');
            };
            const eventContext = element => {
                let parent = element.parentElement;
                for (let depth = 0; parent && depth < 7; depth += 1, parent = parent.parentElement) {
                    const text = compact(parent.innerText || parent.textContent);
                    if (text.length > 20 && text.length <= 500 &&
                        /(?:earnings|conference call|webcast|financial results)/i.test(text) &&
                        /(?:20\\d{2}|\\d{1,2}\\/\\d{1,2}\\/20\\d{2})/i.test(text)) {
                        return text;
                    }
                }
                return '';
            };
            const isFutureEvent = context => {
                const match = context.match(/\\b(0?[1-9]|1[0-2])\\/(0?[1-9]|[12]\\d|3[01])\\/(20\\d{2})\\b/);
                if (!match) return false;
                const eventDate = new Date(Number(match[3]), Number(match[1]) - 1, Number(match[2]));
                const today = new Date();
                today.setHours(0, 0, 0, 0);
                return eventDate > today;
            };
            const controls = Array.from(document.querySelectorAll(
                'button, a, summary, [role="button"], [aria-expanded], [data-toggle], [data-target], ' +
                '[class*="accordion"], [class*="expand"], [class*="toggle"], [class*="plus"], ' +
                '[class*="more"], [class*="detail"]'
            ));
            return controls.filter(element => {
                if (!visible(element)) return false;
                const label = compact([
                    element.innerText,
                    element.getAttribute('aria-label'),
                    element.getAttribute('title'),
                ].filter(Boolean).join(' '));
                const metadata = `${element.className || ''} ${element.id || ''}`.toLowerCase();
                const context = eventContext(element);
                if (!context) return false;
                const expandable = element.getAttribute('aria-expanded') === 'false' ||
                    element.hasAttribute('data-toggle') || element.hasAttribute('data-target') ||
                    /(?:accordion|expand|toggle|plus|more|detail)/.test(metadata) ||
                    /^\\s*\\+\\s*$/.test(label);
                if (!expandable) return false;
                return true;
            }).slice(0, 8).map(element => ({
                selector: nthPath(element),
                label: compact([
                    element.innerText,
                    element.getAttribute('aria-label'),
                    element.getAttribute('title'),
                ].filter(Boolean).join(' ')),
                context: eventContext(element),
                future: isFutureEvent(eventContext(element)),
            }));
        }"""

        for frame in page.frames:
            try:
                controls = await asyncio.wait_for(frame.evaluate(script), timeout=5)
            except Exception:
                continue
            for control in controls or []:
                selector = str(control.get("selector") or "").strip()
                label = " ".join(str(control.get("label") or "").split())
                if not selector:
                    continue
                if bool(control.get("future")):
                    continue
                if label and not REPLAY_EXPANSION_LABEL_PATTERN.search(label):
                    # Class/ARIA metadata can identify icon-only controls.
                    if label not in {"+", ""}:
                        continue
                try:
                    locator = frame.locator(selector).first
                    if not await locator.is_visible():
                        continue
                    await locator.click(force=True, timeout=5000)
                    print(
                        f"[{self.ticker}] expanded replay event control: {label or 'icon'}",
                        flush=True,
                    )
                    await asyncio.sleep(1)
                    return True
                except Exception:
                    continue
        return False

    async def _activate_replay_archive_view(self, page: Any) -> bool:
        """Open a client-rendered past-events tab before selecting replay links."""
        if self.lifecycle != "replay":
            return False

        selector = "a, button, [role='tab'], [role='button']"
        for frame in page.frames:
            try:
                controls = frame.locator(selector).filter(
                    has_text=REPLAY_ARCHIVE_VIEW_PATTERN
                )
                for index in range(min(await controls.count(), 8)):
                    control = controls.nth(index)
                    if not await control.is_visible():
                        continue
                    label = " ".join((await control.inner_text()).split())
                    if not REPLAY_ARCHIVE_VIEW_PATTERN.fullmatch(label):
                        continue
                    print(
                        f"[{self.ticker}] opening replay archive view: {label}",
                        flush=True,
                    )
                    await control.click(force=True, timeout=8000)
                    await asyncio.sleep(2)
                    await self.accept_cookie_banners(page)
                    return True
            except Exception:
                continue
        return False

    async def _capture_learning_snapshot(self, page: Any) -> LearningSnapshot:
        screenshot_path, candidates_path = artifact_paths(self.ticker, page.url)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_timeout = max(
            5.0,
            float(os.getenv("WEBCAST_SCREENSHOT_TIMEOUT_SECONDS", "10")),
        )
        print(f"[{self.ticker}] capturing learning snapshot", flush=True)
        try:
            await page.screenshot(
                path=str(screenshot_path),
                type="jpeg",
                quality=60,
                full_page=os.getenv("WEBCAST_FULL_PAGE_SCREENSHOT", "false").lower() == "true",
                animations="allow",
                timeout=int(screenshot_timeout * 1000),
            )
        except Exception as exc:
            print(
                f"[{self.ticker}] learning snapshot unavailable; continuing with DOM: "
                f"{str(exc)[:120] or 'timeout'}",
                flush=True,
            )
        candidates = await self._collect_candidates(page)
        print(f"[{self.ticker}] collected {len(candidates)} visible candidates", flush=True)
        write_snapshot_metadata(candidates_path, page_url=page.url, candidates=candidates)
        return LearningSnapshot(
            screenshot_path=screenshot_path,
            candidates_path=candidates_path,
            candidates=tuple(candidates),
        )

    async def _capture_failure_snapshot(self, page: Any) -> None:
        """Persist a redacted terminal browser state for later rule improvement."""
        try:
            await page.evaluate(
                """() => {
                    for (const input of document.querySelectorAll(
                        'input[type="text"], input[type="email"], input[type="password"], input[type="tel"]'
                    )) {
                        input.value = '';
                        input.setAttribute('value', '');
                    }
                    for (const textarea of document.querySelectorAll('textarea')) {
                        textarea.value = '';
                        textarea.textContent = '';
                    }
                }"""
            )
            self._learning_snapshot = await self._capture_learning_snapshot(page)
            print(
                f"[{self.ticker}] captured redacted failure snapshot: "
                f"{self._artifact_path()}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[{self.ticker}] failure snapshot skipped: {str(exc)[:120]}",
                flush=True,
            )
        if self.failure_hold_seconds > 0:
            print(
                f"[{self.ticker}] holding failure screen for "
                f"{self.failure_hold_seconds:g}s",
                flush=True,
            )
            await asyncio.sleep(self.failure_hold_seconds)

    async def _collect_candidates(self, page: Any) -> list[WebcastCandidate]:
        script = """() => {
            const compact = value => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 500);
            const contextText = element => {
                let parent = element.parentElement;
                for (let depth = 0; parent && depth < 8; depth += 1, parent = parent.parentElement) {
                    if (['BODY', 'MAIN'].includes(parent.tagName)) break;
                    const text = (parent.innerText || parent.textContent || '')
                        .replace(/\\s+/g, ' ').trim();
                    if (text.length > 20 && text.length <= 1500 &&
                        /(?:earnings|conference call|webcast)/i.test(text) &&
                        /(?:20\\d{2}|January|February|March|April|May|June|July|August|September|October|November|December)/i.test(text)) {
                        return text.slice(0, 1500);
                    }
                }
                return '';
            };
            const visible = element => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' &&
                    Number(style.opacity || 1) > 0 && rect.width > 2 && rect.height > 2;
            };
            const inNavigation = element => {
                let parent = element.parentElement;
                while (parent) {
                    const tag = parent.tagName.toLowerCase();
                    const labels = `${parent.id || ''} ${parent.className || ''}`.toLowerCase();
                    if (tag === 'nav' || tag === 'header' || tag === 'footer' ||
                        /(nav|menu|sidebar|footer)/.test(labels)) return true;
                    parent = parent.parentElement;
                }
                return false;
            };
            const nthPath = element => {
                const parts = [];
                let current = element;
                for (let depth = 0; current && current.nodeType === Node.ELEMENT_NODE && depth < 7; depth += 1) {
                    if (current.id) {
                        parts.unshift(`#${CSS.escape(current.id)}`);
                        break;
                    }
                    const tag = current.tagName.toLowerCase();
                    const siblings = Array.from(current.parentElement?.children || []).filter(
                        sibling => sibling.tagName === current.tagName,
                    );
                    const index = siblings.indexOf(current) + 1;
                    parts.unshift(`${tag}:nth-of-type(${Math.max(index, 1)})`);
                    current = current.parentElement;
                }
                return parts.join(' > ');
            };
            const selectors = element => {
                const values = [];
                if (element.id) values.push(`#${CSS.escape(element.id)}`);
                const testId = element.getAttribute('data-testid');
                if (testId) values.push(`[data-testid=${JSON.stringify(testId)}]`);
                const aria = element.getAttribute('aria-label');
                if (aria) values.push(`[aria-label=${JSON.stringify(aria)}]`);
                values.push(nthPath(element));
                return [...new Set(values)].filter(Boolean);
            };

            return Array.from(document.querySelectorAll(
                'a, button, [role="button"], [role="link"], [onclick], video, audio'
            ))
                .filter(visible)
                .slice(0, 300)
                .map((element, index) => {
                    const rect = element.getBoundingClientRect();
                    const rawHref = element.getAttribute('href') || '';
                    let hrefPath = null;
                    try { hrefPath = rawHref ? new URL(rawHref, document.baseURI).pathname : null; } catch (_) {}
                    return {
                        dom_index: index,
                        selectors: selectors(element),
                        text: compact(element.innerText || element.textContent),
                        aria_label: compact(element.getAttribute('aria-label')),
                        title: compact(element.getAttribute('title')),
                        href_path: hrefPath,
                        tag_name: element.tagName.toLowerCase(),
                        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                        in_navigation: inNavigation(element),
                        context_text: contextText(element),
                    };
                });
        }"""
        candidates: list[WebcastCandidate] = []
        for frame_index, frame in enumerate(page.frames):
            try:
                rows = await asyncio.wait_for(frame.evaluate(script), timeout=5)
            except Exception:
                continue
            frame_hostname = None if frame == page.main_frame else domain_for_url(frame.url)
            for row in rows:
                row["candidate_id"] = f"frame-{frame_index}-element-{row.pop('dom_index')}"
                row["frame_hostname"] = frame_hostname or None
                candidates.append(WebcastCandidate.from_dict(row))
        return candidates

    async def _choose_learning_candidate(
        self,
        page: Any,
        snapshot: LearningSnapshot,
    ) -> tuple[WebcastCandidate | None, str, float, str | None]:
        candidates = list(snapshot.candidates)
        selection = await self._vision_selector.select(
            snapshot.screenshot_path,
            candidates,
            ticker=self.ticker,
        )
        minimum_confidence = float(os.getenv("WEBCAST_VISION_MIN_CONFIDENCE", "0.55"))
        if selection and selection.confidence >= minimum_confidence:
            selected = next(
                (candidate for candidate in candidates if candidate.candidate_id == selection.candidate_id),
                None,
            )
            if selected:
                return selected, "vision", selection.confidence, selection.reason
            if selection.x > 0 and selection.y > 0:
                pointed = await self._candidate_at_page_point(page, selection.x, selection.y)
                if pointed:
                    return pointed, "vision-point", selection.confidence, selection.reason

        generalized_patterns = ()
        if self.generalized_learning_enabled:
            try:
                try:
                    from ... import database
                except ImportError:
                    from data_pipeline import database

                generalized_patterns = make_generalized_patterns(
                    database.get_generalized_webcast_patterns(
                        self._compatible_recipe_lifecycles()
                    )
                )
                if generalized_patterns:
                    print(
                        f"[{self.ticker}] applying generalized webcast evidence "
                        f"patterns={len(generalized_patterns)}",
                        flush=True,
                    )
            except Exception as exc:
                print(
                    f"[{self.ticker}] generalized evidence lookup skipped: {str(exc)[:120]}",
                    flush=True,
                )

        heuristic = choose_heuristic_candidate(
            candidates,
            generalized_patterns,
            lifecycle=self.lifecycle,
            target_year=self.target_year,
            target_quarter=self.target_quarter,
        )
        if heuristic:
            return heuristic, "dom-heuristic", 0.50, None
        return None, "none", 0.0, None

    async def _candidate_at_page_point(
        self,
        page: Any,
        x: float,
        y: float,
    ) -> WebcastCandidate | None:
        row = await page.evaluate(
            """({ x, y }) => {
                window.scrollTo(0, Math.max(0, y - window.innerHeight / 2));
                const element = document.elementFromPoint(x, y - window.scrollY);
                if (!element) return null;
                const target = element.closest('a, button, [role="button"], [role="link"], [onclick]') || element;
                const compact = value => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 500);
                const parts = [];
                let current = target;
                for (let depth = 0; current && current.nodeType === Node.ELEMENT_NODE && depth < 7; depth += 1) {
                    if (current.id) { parts.unshift(`#${CSS.escape(current.id)}`); break; }
                    const tag = current.tagName.toLowerCase();
                    const siblings = Array.from(current.parentElement?.children || []).filter(
                        sibling => sibling.tagName === current.tagName,
                    );
                    parts.unshift(`${tag}:nth-of-type(${Math.max(siblings.indexOf(current) + 1, 1)})`);
                    current = current.parentElement;
                }
                const rect = target.getBoundingClientRect();
                return {
                    selectors: [target.id ? `#${CSS.escape(target.id)}` : '', parts.join(' > ')].filter(Boolean),
                    text: compact(target.innerText || target.textContent),
                    aria_label: compact(target.getAttribute('aria-label')),
                    title: compact(target.getAttribute('title')),
                    href_path: target.href ? new URL(target.href).pathname : null,
                    tag_name: target.tagName.toLowerCase(),
                    rect: { x: rect.x, y: rect.y + window.scrollY, width: rect.width, height: rect.height },
                    in_navigation: false,
                };
            }""",
            {"x": x, "y": y},
        )
        if not row:
            return None
        row["candidate_id"] = f"vision-point-{int(x)}-{int(y)}"
        row["frame_hostname"] = None
        return WebcastCandidate.from_dict(row)

    async def _find_recipe_button(self, page: Any, recipe: WebcastRecipe) -> Any | None:
        frames = [page.main_frame]
        if recipe.frame_hostname:
            frames = [
                frame
                for frame in page.frames
                if domain_for_url(frame.url) == recipe.frame_hostname
            ]
        for frame in frames:
            if recipe.target_href_path:
                try:
                    href_selector = f"a[href*={json.dumps(recipe.target_href_path)}]"
                    candidate = frame.locator(href_selector).first
                    if await candidate.count() > 0 and await candidate.is_visible():
                        return candidate
                except Exception:
                    pass
            for selector in recipe.selectors:
                try:
                    candidate = frame.locator(selector).first
                    if await candidate.count() > 0 and await candidate.is_visible():
                        return candidate
                except Exception:
                    continue
            if recipe.target_text:
                try:
                    text_pattern = re.compile(
                        re.escape(recipe.target_text[:120]),
                        re.IGNORECASE,
                    )
                    candidate = frame.locator("a, button, [role='button']").filter(
                        has_text=text_pattern
                    ).first
                    if await candidate.count() > 0 and await candidate.is_visible():
                        return candidate
                except Exception:
                    pass
        return None

    def _load_verified_recipes(self, page_url: str) -> list[WebcastRecipe]:
        domain = domain_for_url(page_url)
        if not domain:
            return []
        try:
            try:
                from ... import database
            except ImportError:
                from data_pipeline import database

            return [
                WebcastRecipe.from_record(row)
                for row in database.get_verified_webcast_recipes(
                    domain,
                    lifecycles=self._compatible_recipe_lifecycles(),
                )
            ]
        except Exception as exc:
            print(f"[{self.ticker}] recipe lookup skipped: {str(exc)[:160]}")
            return []

    def _compatible_recipe_lifecycles(self) -> tuple[str, ...]:
        if self.lifecycle == "live":
            # A replay recipe often contains an event-specific attendee path. Reusing it
            # for a live watch can open an old recording and create a false audio hit.
            return ("live", "unknown")
        if self.lifecycle == "pre_live":
            return ("pre_live", "unknown")
        if self.lifecycle == "replay":
            return ("replay", "unknown")
        return ("unknown",)

    def _save_recipe(self, recipe: WebcastRecipe) -> int | None:
        try:
            try:
                from ... import database
            except ImportError:
                from data_pipeline import database

            return database.save_webcast_recipe(recipe.database_value())
        except Exception as exc:
            print(f"[{self.ticker}] recipe save skipped: {str(exc)[:160]}")
            return None

    def _recipe_context_path(self) -> Path:
        return Path(os.getenv("WEBCAST_RECIPE_CONTEXT_PATH", "/tmp/ew-webcast-recipe.json"))

    def _clear_recipe_context(self) -> None:
        self._recipe_context_path().unlink(missing_ok=True)

    def _write_recipe_context(self) -> None:
        if not self._active_recipe or not self._active_recipe.recipe_id:
            return
        path = self._recipe_context_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "recipe_id": self._active_recipe.recipe_id,
                    "recipe_strategy": self._active_recipe.strategy,
                    "recipe_lifecycle": self._active_recipe.lifecycle,
                    "ticker": self.ticker,
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )

    def _recipe_id(self) -> int | None:
        return self._active_recipe.recipe_id if self._active_recipe else None

    def _recipe_strategy(self) -> str | None:
        return self._active_recipe.strategy if self._active_recipe else None

    def _artifact_path(self) -> str | None:
        return str(self._learning_snapshot.screenshot_path) if self._learning_snapshot else None

    async def _is_navigation_element(self, element: Any) -> bool:
        return await element.evaluate(
            """el => {
                let parent = el.parentElement;
                while (parent) {
                    const tagName = parent.tagName.toLowerCase();
                    const className = parent.className ? String(parent.className).toLowerCase() : '';
                    const idName = parent.id ? String(parent.id).toLowerCase() : '';
                    if (
                        tagName === 'nav' || tagName === 'header' || tagName === 'footer' ||
                        className.includes('nav') || className.includes('menu') ||
                        className.includes('sidebar') || idName.includes('nav') ||
                        idName.includes('sidebar')
                    ) {
                        return true;
                    }
                    parent = parent.parentElement;
                }
                return false;
            }"""
        )

    async def fill_registration_form(self, page: Any, timeout_error_type: type[Exception]) -> bool:
        if not self.allow_registration_submission:
            self._registration_failure_error = (
                "REGISTRATION_REQUIRED registration submission is disabled"
            )
            print(f"[{self.ticker}] {self._registration_failure_error}", flush=True)
            return False

        selectors = [
            "form#frmRegister",
            "button#registration-box_signup-button",
            "button:has-text('Register for event')",
            "a:has-text('Register for event')",
            "input#email",
            "input#password",
            "form#fmRegister",
            "form[action*='register' i]",
            "input[type='email']",
            "input[name*='mail' i]",
            "input[autocomplete='given-name']",
            "input[name*='first' i]",
            "input[placeholder*='First' i]",
        ]
        registration_control_found = False
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            for selector in selectors:
                locator = page.locator(selector)
                try:
                    count = min(await locator.count(), 12)
                    if any(
                        [
                            await locator.nth(index).is_visible()
                            for index in range(count)
                        ]
                    ):
                        registration_control_found = True
                        break
                except Exception:
                    continue
            if registration_control_found:
                break
            await asyncio.sleep(0.5)

        if not registration_control_found:
            if await self.has_registration_form(page):
                print(
                    f"[{self.ticker}] using generic registration form detection",
                    flush=True,
                )
                return await self._fill_generic_registration_form(
                    page,
                    timeout_error_type,
                )
            print(
                f"[{self.ticker}] no visible registration controls after 15s",
                flush=True,
            )
            return True

        await self.accept_cookie_banners(page)

        try:
            guest_button = page.locator(
                "button:has-text('Continue as Guest'), "
                "button:has-text('Register as Guest'), "
                "button:has-text('Register as a Guest'), "
                "button:has-text('Continue without an account'), "
                "a:has-text('Continue as Guest')"
            ).first
            if await guest_button.count() > 0 and await guest_button.is_visible():
                print(f"[{self.ticker}] using guest webcast registration", flush=True)
                await guest_button.click(force=True)
                await asyncio.sleep(1)
                return await self._fill_generic_registration_form(
                    page,
                    timeout_error_type,
                )

            q4_gate_button = page.locator(
                "button#registration-box_signup-button, "
                "button:has-text('Register with a Q4 Account'), "
                "button:has-text('Register for event'), "
                "a:has-text('Register for event')"
            ).first
            if await q4_gate_button.count() > 0 and await q4_gate_button.is_visible():
                await q4_gate_button.click(force=True)
                try:
                    await page.wait_for_selector("input#email", state="visible", timeout=10000)
                except timeout_error_type:
                    if await self.detect_active_playback(page):
                        return True
                    if not await self.has_registration_form(page):
                        return True

            q4_email_field = page.locator("input#email").first
            if await q4_email_field.count() > 0 and await q4_email_field.is_visible():
                if not self.profile.q4_email:
                    print(f"[{self.ticker}] email field found but Q4_EMAIL/WEBCAST_EMAIL is missing")
                    return False
                await q4_email_field.fill(self.profile.q4_email)
                next_button = page.locator("button").filter(
                    has_text=re.compile(r"^Next$", re.IGNORECASE)
                ).first
                if await next_button.count() > 0 and await next_button.is_visible():
                    await next_button.click(force=True)
                    await page.wait_for_selector("input#password", state="visible", timeout=10000)

            q4_password_field = page.locator("input#password").first
            if await q4_password_field.count() > 0 and await q4_password_field.is_visible():
                if not self.profile.q4_password:
                    print(
                        f"[{self.ticker}] AUTH_REQUIRED "
                        "WEBCAST_PASSWORD/Q4_PASSWORD is missing",
                        flush=True,
                    )
                    return False
                await q4_password_field.fill(self.profile.q4_password)
                login_button = page.locator("button").filter(
                    has_text=re.compile(r"^Log in$|Sign in", re.IGNORECASE)
                ).first
                if await login_button.count() > 0 and await login_button.is_visible():
                    await login_button.click(force=True)
                    await asyncio.sleep(5)
                    return True

            return await self._fill_generic_registration_form(
                page,
                timeout_error_type,
            )
        except Exception as exc:
            print(f"[{self.ticker}] registration form handling error: {exc}")
            return False

    async def handle_registration_form(
        self,
        page: Any,
        timeout_error_type: type[Exception],
    ) -> bool:
        print(f"[{self.ticker}] checking webcast registration", flush=True)
        self._registration_target_page = None
        self._registration_failure_error = None
        if await self.has_registration_form(page) and not self.allow_registration_submission:
            self._registration_failure_error = (
                "REGISTRATION_REQUIRED registration submission is disabled"
            )
            print(f"[{self.ticker}] {self._registration_failure_error}", flush=True)
            return False
        try:
            return await asyncio.wait_for(
                self.fill_registration_form(page, timeout_error_type),
                timeout=self.registration_timeout_seconds,
            )
        except asyncio.TimeoutError:
            print(
                f"[{self.ticker}] registration handling timed out after "
                f"{self.registration_timeout_seconds:g}s",
                flush=True,
            )
            return False

    def _registration_error(self) -> str:
        return self._registration_failure_error or "registration form handling failed"

    async def has_registration_form(self, page: Any) -> bool:
        try:
            gate_controls = page.locator("button, a")
            for index in range(await gate_controls.count()):
                control = gate_controls.nth(index)
                if not await control.is_visible():
                    continue
                label = " ".join(
                    value
                    for value in (
                        await control.inner_text(),
                        await control.get_attribute("aria-label"),
                        await control.get_attribute("title"),
                    )
                    if value
                )
                if Q4_EVENT_GATE_PATTERN.search(label):
                    return True

            fields = page.locator(
                "input:not([type='hidden']):not([type='submit']):not([type='button']), "
                "select, textarea"
            )
            field_count = 0
            for index in range(await fields.count()):
                if await fields.nth(index).is_visible():
                    field_count += 1
            if field_count < 2:
                return False
            submit_controls = page.locator("button, input[type='submit']")
            for index in range(await submit_controls.count()):
                control = submit_controls.nth(index)
                if not await control.is_visible():
                    continue
                text = ((await control.inner_text()) or await control.get_attribute("value") or "").lower()
                if re.search(r"submit|register|enter|join", text):
                    return True
            body_text = (await page.locator("body").inner_text(timeout=2000))[:6000]
            if REGISTRATION_FORM_TEXT_PATTERN.search(body_text):
                return True
        except Exception:
            return False
        return False

    async def _fill_generic_registration_form(
        self,
        page: Any,
        timeout_error_type: type[Exception],
    ) -> bool:
        container_selectors = [
            "form#fmRegister",
            "form[id*='reg' i]",
            "form",
            "div[id*='reg' i]",
            "div[class*='form' i]",
        ]
        root = page
        for selector in container_selectors:
            locator = page.locator(selector).first
            if await locator.count() > 0 and await locator.is_visible():
                root = locator
                break

        async def fill_field(label_text: str, value: str, fallbacks: list[str]) -> bool:
            if not value:
                return False
            try:
                locator = root.get_by_label(label_text, exact=False)
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.fill(value)
                    return True
            except Exception:
                pass
            for selector in fallbacks:
                locator = root.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.fill(value)
                    return True
            unlabeled_fields = root.locator(
                "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea"
            )
            for index in range(await unlabeled_fields.count()):
                locator = unlabeled_fields.nth(index)
                if not await locator.is_visible():
                    continue
                surrounding_text = await locator.evaluate(
                    """element => {
                        let current = element;
                        for (let depth = 0; current && depth < 5; depth += 1) {
                            const text = (current.innerText || '').replace(/\\s+/g, ' ').trim();
                            if (text && text.length <= 220) return text;
                            current = current.parentElement;
                        }
                        return '';
                    }"""
                )
                if re.search(rf"\b{re.escape(label_text)}\b", surrounding_text, re.IGNORECASE):
                    await locator.fill(value)
                    return True
            return False

        filled_fields = {
            "first_name": await fill_field(
                "First Name",
                self.profile.first_name,
                [
                    "input[title*='First' i]",
                    "input[name*='first' i]",
                    "input[name*='fname' i]",
                    "input[id*='first' i]",
                    "input[id*='fname' i]",
                    "input[placeholder*='first' i]",
                    "input[aria-label*='first' i]",
                ],
            ),
            "last_name": await fill_field(
                "Last Name",
                self.profile.last_name,
                [
                    "input[title*='Last' i]",
                    "input[name*='last' i]",
                    "input[name*='lname' i]",
                    "input[id*='last' i]",
                    "input[id*='lname' i]",
                    "input[placeholder*='last' i]",
                    "input[aria-label*='last' i]",
                ],
            ),
            "company": await fill_field(
                "Company",
                self.profile.company,
                [
                    "input[title*='Company' i]",
                    "input[name*='company' i]",
                    "input[id*='company' i]",
                    "input[placeholder*='company' i]",
                    "input[aria-label*='company' i]",
                ],
            ),
            "organization": await fill_field(
                "Organization",
                self.profile.company,
                [
                    "input[title*='Organization' i]",
                    "input[name*='organization' i]",
                    "input[name*='org' i]",
                    "input[id*='organization' i]",
                    "input[id*='org' i]",
                    "input[placeholder*='organization' i]",
                    "input[aria-label*='organization' i]",
                ],
            ),
            "affiliation": await fill_field(
                "Affiliation",
                self.profile.industry_affiliation,
                [
                    "input[title*='Affiliation' i]",
                    "input[name*='affiliation' i]",
                    "input[id*='affiliation' i]",
                    "input[placeholder*='affiliation' i]",
                    "input[aria-label*='affiliation' i]",
                ],
            ),
            "country": await fill_field(
                "Country",
                self.profile.country,
                [
                    "input[title*='Country' i]",
                    "input[name*='country' i]",
                    "input[id*='country' i]",
                    "input[placeholder*='country' i]",
                    "input[aria-label*='country' i]",
                ],
            ),
            "email": await fill_field(
                "Email",
                self.profile.email,
                [
                    "input[type='email']",
                    "input[title*='Email' i]",
                    "input[name*='mail' i]",
                    "input[id*='mail' i]",
                    "input[placeholder*='mail' i]",
                    "input[aria-label*='mail' i]",
                ],
            ),
        }

        async def select_field(
            label_text: str,
            value: str,
            fallbacks: list[str],
        ) -> bool:
            if not value:
                return False
            candidates = []
            try:
                candidates.append(root.get_by_label(label_text, exact=False))
            except Exception:
                pass
            candidates.extend(root.locator(selector).first for selector in fallbacks)
            for locator in candidates:
                try:
                    if await locator.count() == 0 or not await locator.is_visible():
                        continue
                    await locator.select_option(label=value)
                    return True
                except Exception:
                    continue
            return False

        async def choose_option_field(
            label_text: str,
            value: str,
            fallbacks: list[str],
        ) -> bool:
            if not value:
                return False
            candidates = []
            try:
                candidates.append(root.get_by_label(label_text, exact=False).first)
            except Exception:
                pass
            candidates.extend(root.locator(selector).first for selector in fallbacks)
            for locator in candidates:
                try:
                    if await locator.count() == 0 or not await locator.is_visible():
                        continue
                    tag_name = await locator.evaluate("element => element.tagName.toLowerCase()")
                    if tag_name == "select":
                        try:
                            await locator.select_option(label=value)
                            return True
                        except Exception:
                            await locator.select_option(value=value)
                            return True
                    await locator.click(force=True)
                    await asyncio.sleep(0.3)
                    option = page.get_by_text(value, exact=True).last
                    if await option.count() > 0 and await option.is_visible():
                        await option.click(force=True)
                        return True
                except Exception:
                    continue
            return False

        selected_fields = {
            "industry_affiliation": await select_field(
                "Industry Affiliation",
                self.profile.industry_affiliation,
                [
                    "select[title*='Industry Affiliation' i]",
                    "select[name*='industry' i]",
                ],
            ),
            "occupation": await choose_option_field(
                "Occupation",
                self.profile.occupation,
                [
                    "select[name*='occupation' i]",
                    "[role='combobox'][aria-label*='occupation' i]",
                    "button[aria-label*='occupation' i]",
                    "button[id*='occupation' i]",
                ],
            ),
        }
        has_any_field = any(filled_fields.values()) or any(selected_fields.values())

        if not has_any_field:
            return True
        print(
            f"[{self.ticker}] registration fields prepared: "
            f"{','.join(name for name, filled in {**filled_fields, **selected_fields}.items() if filled)}",
            flush=True,
        )

        invalid_fields = root.locator(
            "input:invalid:not([type='hidden']), select:invalid, textarea:invalid"
        )
        invalid_count = await invalid_fields.count()
        if invalid_count:
            print(
                f"[{self.ticker}] registration has {invalid_count} unfilled required fields",
                flush=True,
            )
            return False

        submit_button = root.locator(
            "input[type='submit'][value*='Submit' i], "
            "input[type='submit'][value*='Register' i], "
            "input[type='submit'][value*='Enter' i], "
            "input[type='submit'][value*='Join' i]"
        ).first
        if await submit_button.count() == 0 or not await submit_button.is_visible():
            submit_button = root.locator("button[type='submit'], button").filter(
                has_text=re.compile(r"Submit|Register|Enter|Join", re.IGNORECASE)
            ).first
        if await submit_button.count() == 0 or not await submit_button.is_visible():
            submit_button = root.locator(
                "[role='button'], input[type='button']"
            ).filter(
                has_text=re.compile(r"Submit|Register|Enter|Join", re.IGNORECASE)
            ).first
        if await submit_button.count() > 0 and await submit_button.is_visible():
            print(f"[{self.ticker}] submitting webcast registration form", flush=True)
            source_url = page.url
            try:
                async with page.context.expect_page(timeout=5000) as new_page_info:
                    await submit_button.click(force=True, timeout=8000)
                submitted_page = await new_page_info.value
                self._attach_media_watchers(submitted_page)
                self._registration_target_page = submitted_page
                print(
                    f"[{self.ticker}] registration opened player tab: "
                    f"{submitted_page.url}",
                    flush=True,
                )
                return True
            except timeout_error_type:
                pass

            if page.url == source_url:
                try:
                    form_still_visible = await root.is_visible()
                except Exception:
                    form_still_visible = False
                if form_still_visible:
                    try:
                        submitted = await root.evaluate(
                            """element => {
                                const form = element.tagName === 'FORM'
                                    ? element
                                    : element.closest('form') || element.querySelector('form');
                                if (!form) return false;
                                if (typeof form.requestSubmit === 'function') {
                                    form.requestSubmit();
                                } else {
                                    form.submit();
                                }
                                return true;
                            }""",
                            timeout=5000,
                        )
                        if submitted:
                            print(
                                f"[{self.ticker}] registration form requestSubmit fallback",
                                flush=True,
                            )
                    except Exception as exc:
                        print(
                            f"[{self.ticker}] registration requestSubmit skipped: "
                            f"{str(exc)[:120]}",
                            flush=True,
                        )

            for _ in range(12):
                await asyncio.sleep(1)
                if await self.detect_active_playback(page):
                    print(f"[{self.ticker}] registration form accepted", flush=True)
                    return True
                try:
                    body_text = await page.locator("body").inner_text(timeout=1000)
                except Exception:
                    body_text = ""
                if ALREADY_REGISTERED_PATTERN.search(body_text):
                    self._registration_failure_error = (
                        "AUTH_REQUIRED webcast registration already exists; "
                        "email login link is required"
                    )
                    print(f"[{self.ticker}] {self._registration_failure_error}", flush=True)
                    return False
                try:
                    form_visible = await root.is_visible()
                except Exception:
                    form_visible = False
                if not form_visible or page.url != source_url:
                    print(f"[{self.ticker}] registration form accepted", flush=True)
                    return True

            body_text = await page.locator("body").inner_text(timeout=3000)
            if ALREADY_REGISTERED_PATTERN.search(body_text):
                self._registration_failure_error = (
                    "AUTH_REQUIRED webcast registration already exists; "
                    "email login link is required"
                )
                print(f"[{self.ticker}] {self._registration_failure_error}", flush=True)
            elif REGISTRATION_EMAIL_ERROR_PATTERN.search(body_text):
                print(f"[{self.ticker}] registration form rejected the configured email address")
            else:
                invalid_count = await page.locator(
                    "input:invalid:not([type='hidden']), select:invalid, textarea:invalid"
                ).count()
                print(
                    f"[{self.ticker}] registration form remained visible "
                    f"invalid_fields={invalid_count}",
                    flush=True,
                )
            return False
        return True

    async def detect_active_playback(self, page: Any) -> str | None:
        """Return evidence that a player is already running in any reachable frame."""
        script = """({ lifecycle, replaySeekSeconds }) => {
            const media = Array.from(document.querySelectorAll('video, audio'));
            for (const element of media) {
                if (!element.paused && !element.ended && element.readyState >= 2) {
                    element.muted = false;
                    element.volume = 1;
                    let seeked = false;
                    if (
                        lifecycle === 'replay' && replaySeekSeconds > 0 &&
                        Number.isFinite(element.duration) &&
                        element.duration > replaySeekSeconds + 20
                    ) {
                        const target = Math.min(
                            element.duration - 10,
                            300,
                            Math.max(replaySeekSeconds, element.duration * 0.05),
                        );
                        if (element.currentTime < Math.min(30, target - 5)) {
                            element.currentTime = target;
                            seeked = true;
                        }
                    }
                    return element.tagName.toLowerCase() +
                        ' element is playing unmuted volume=' + element.volume +
                        ' time=' + Math.round(element.currentTime) +
                        (seeked ? ' seeked' : '');
                }
            }
            const controls = Array.from(document.querySelectorAll(
                'button, [role="button"], a'
            ));
            for (const control of controls) {
                const style = window.getComputedStyle(control);
                const rect = control.getBoundingClientRect();
                if (
                    style.visibility === 'hidden' || style.display === 'none' ||
                    rect.width <= 2 || rect.height <= 2
                ) {
                    continue;
                }
                const label = [
                    control.innerText,
                    control.textContent,
                    control.getAttribute('aria-label'),
                    control.getAttribute('title'),
                ].filter(Boolean).join(' ').trim();
                if (/^pause(?:\\s|$)/i.test(label)) {
                    return 'visible pause control';
                }
            }
            return null;
        }"""
        for candidate_page in self._playback_pages(page):
            for frame in candidate_page.frames:
                try:
                    reason = await asyncio.wait_for(
                        frame.evaluate(
                            script,
                            {
                                "lifecycle": self.lifecycle,
                                "replaySeekSeconds": self.replay_seek_seconds,
                            },
                        ),
                        timeout=3,
                    )
                except Exception:
                    continue
                if reason:
                    return str(reason)
        return None

    async def _has_visible_media_element(self, page: Any) -> bool:
        for candidate_page in self._playback_pages(page):
            for frame in candidate_page.frames:
                try:
                    media = frame.locator("video, audio")
                    for index in range(await media.count()):
                        if await media.nth(index).is_visible():
                            return True
                except Exception:
                    continue
        return False

    @staticmethod
    def _playback_pages(page: Any) -> list[Any]:
        pages = [page]
        try:
            context_pages = page.context.pages
        except Exception:
            context_pages = []
        if isinstance(context_pages, (list, tuple)):
            pages.extend(candidate for candidate in context_pages if candidate not in pages)
        return pages

    async def _wait_for_active_playback(
        self,
        page: Any,
        *,
        attempts: int,
    ) -> str | None:
        for _ in range(max(1, attempts)):
            await asyncio.sleep(1)
            active_reason = await self.detect_active_playback(page)
            if active_reason:
                return active_reason
        return None

    async def _prime_direct_player_audio(self, page: Any) -> None:
        """Use trusted media clicks so direct HTML5 players create a PulseAudio sink-input."""
        for candidate_page in self._playback_pages(page):
            url = str(candidate_page.url)
            if not is_audio_priming_player_url(url) or url in self._direct_audio_primed_urls:
                continue
            try:
                is_youtube = any(
                    domain_for_url(url) == suffix or domain_for_url(url).endswith(f".{suffix}")
                    for suffix in DIRECT_PLAYER_HOST_SUFFIXES
                )
                if not is_youtube:
                    primed = False
                    for frame in candidate_page.frames:
                        if frame == candidate_page.main_frame:
                            try:
                                mute_info = await asyncio.wait_for(
                                    frame.evaluate(
                                        """() => {
                                            const button = Array.from(document.querySelectorAll('button'))
                                                .find(element => /^(?:mute|unmute)$/i.test(
                                                    (element.innerText || element.getAttribute('aria-label') || '').trim()
                                                ));
                                            if (!button) return null;
                                            const rect = button.getBoundingClientRect();
                                            return {
                                                label: (button.innerText || button.getAttribute('aria-label') || '').trim(),
                                                x: rect.left + rect.width / 2,
                                                y: rect.top + rect.height / 2,
                                            };
                                        }"""
                                    ),
                                    timeout=3,
                                )
                            except Exception:
                                mute_info = None
                            if mute_info:
                                clicks = 1 if "unmute" in mute_info["label"].lower() else 2
                                for _ in range(clicks):
                                    await candidate_page.mouse.click(mute_info["x"], mute_info["y"])
                                    await asyncio.sleep(0.3)
                                primed = True
                                break
                        if (
                            not primed
                            and domain_for_url(url).endswith(".media-server.com")
                        ):
                            viewport = candidate_page.viewport_size or {"height": 1000}
                            for _ in range(2):
                                await candidate_page.mouse.click(60, viewport["height"] - 20)
                                await asyncio.sleep(0.3)
                            primed = True
                            break
                        mute_control = frame.locator("button").filter(
                            has_text=re.compile(r"^(?:Mute|Unmute)$", re.IGNORECASE)
                        ).first
                        if await mute_control.count() > 0 and await mute_control.is_visible():
                            label = (
                                await mute_control.inner_text()
                                or await mute_control.get_attribute("aria-label")
                                or ""
                            ).strip().lower()
                            clicks = 1 if "unmute" in label else 2
                            for _ in range(clicks):
                                await mute_control.click(force=True, timeout=3000)
                                await asyncio.sleep(0.3)
                            primed = True
                            break
                        video = frame.locator("video").first
                        if await video.count() == 0:
                            continue
                        await video.evaluate(
                            """async element => {
                                element.muted = false;
                                element.volume = 1;
                                element.click();
                                try { await element.play(); } catch (_) {}
                                return !element.paused && !element.muted && element.volume > 0;
                            }""",
                            timeout=5000,
                        )
                        primed = True
                        break
                    if not primed:
                        continue
                    await asyncio.sleep(0.5)
                    self._direct_audio_primed_urls.add(url)
                    print(
                        f"[{self.ticker}] primed HTML5 direct-player audio with a trusted video click",
                        flush=True,
                    )
                    continue
                video = candidate_page.locator("video").first
                if await video.count() == 0:
                    continue
                try:
                    await video.hover(timeout=3000)
                except Exception:
                    pass
                was_playing = bool(
                    await video.evaluate(
                        "element => !element.paused && !element.ended"
                    )
                )
                mute_button = candidate_page.locator(".ytp-mute-button").first
                if await mute_button.count() == 0 or not await mute_button.is_visible():
                    continue
                label = " ".join(
                    value
                    for value in (
                        await mute_button.get_attribute("aria-label"),
                        await mute_button.get_attribute("title"),
                    )
                    if value
                )
                clicks = 1 if "unmute" in label.lower() else 2
                for _ in range(clicks):
                    await mute_button.click(force=True, timeout=3000)
                    await asyncio.sleep(0.4)
                await video.click(force=True, timeout=3000)
                await asyncio.sleep(0.5)
                playing_after_click = bool(
                    await video.evaluate(
                        "element => !element.paused && !element.ended"
                    )
                )
                if not playing_after_click:
                    await video.click(force=True, timeout=3000)
                    await asyncio.sleep(0.5)
                self._direct_audio_primed_urls.add(url)
                print(
                    f"[{self.ticker}] primed direct-player audio with trusted "
                    f"mute and video clicks was_playing={was_playing}",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"[{self.ticker}] direct-player audio priming skipped: "
                    f"{str(exc)[:120]}",
                    flush=True,
                )

    async def trigger_media_playback(
        self,
        page: Any,
        *,
        allow_control_scan: bool = True,
    ) -> bool:
        try:
            return await asyncio.wait_for(
                self._trigger_media_playback(
                    page,
                    allow_control_scan=allow_control_scan,
                ),
                timeout=self.playback_control_timeout_seconds,
            )
        except asyncio.TimeoutError:
            print(
                f"[{self.ticker}] player control search timed out after "
                f"{self.playback_control_timeout_seconds:g}s",
                flush=True,
            )
            return False

    async def _trigger_media_playback(
        self,
        page: Any,
        *,
        allow_control_scan: bool,
    ) -> bool:
        try:
            await asyncio.wait_for(
                self._prime_direct_player_audio(page),
                timeout=min(8.0, self.playback_control_timeout_seconds / 2),
            )
        except asyncio.TimeoutError:
            print(f"[{self.ticker}] direct-player audio priming timed out; checking playback", flush=True)
        active_reason = await self.detect_active_playback(page)
        if active_reason:
            print(f"[{self.ticker}] playback already active: {active_reason}", flush=True)
            return True

        print(f"[{self.ticker}] waiting for player to become active", flush=True)
        active_reason = await self._wait_for_active_playback(page, attempts=8)
        if active_reason:
            print(f"[{self.ticker}] playback became active: {active_reason}", flush=True)
            return True

        try:
            control_clicked = False
            if allow_control_scan:
                print(f"[{self.ticker}] searching for player controls", flush=True)
                try:
                    await page.wait_for_selector(
                        "button, a, div[role='button']",
                        state="visible",
                        timeout=8000,
                    )
                except Exception:
                    pass

                for frame in page.frames:
                    # A large number of webcast players expose only an aria-label
                    # or title on icon buttons, so text filtering alone misses them.
                    # Keep the attribute selectors keyword-scoped; selecting every
                    # labelled element also pulls in analytics and accessibility UI.
                    play_buttons = frame.locator(
                        "button, a, div[role='button'], "
                        "[aria-label*='play' i], [aria-label*='listen' i], "
                        "[aria-label*='start' i], [aria-label*='unmute' i], "
                        "[aria-label*='watch' i], [aria-label*='replay' i], "
                        "[title*='play' i], [title*='listen' i], "
                        "[title*='start' i], [title*='unmute' i], "
                        "[title*='watch' i], [title*='replay' i]"
                    )
                    count = await asyncio.wait_for(play_buttons.count(), timeout=3)
                    for index in range(count):
                        button = play_buttons.nth(index)
                        if await asyncio.wait_for(button.is_visible(), timeout=2):
                            label = " ".join(
                                value.strip()
                                for value in (
                                    await asyncio.wait_for(button.inner_text(), timeout=2),
                                    await button.get_attribute("aria-label"),
                                    await button.get_attribute("title"),
                                )
                                if value and value.strip()
                            ) or "player control"
                            if not is_playback_control_label(label):
                                continue
                            print(
                                f"[{self.ticker}] clicking player control: {label[:80]}",
                                flush=True,
                            )
                            await asyncio.wait_for(button.click(force=True), timeout=5)
                            control_clicked = True
                            active_reason = await self._wait_for_active_playback(
                                page,
                                attempts=12,
                            )
                            if active_reason:
                                print(
                                    f"[{self.ticker}] playback became active after click: "
                                    f"{active_reason}",
                                    flush=True,
                                )
                                return True
                            print(
                                f"[{self.ticker}] control did not activate playback: "
                                f"{label[:80]}",
                                flush=True,
                            )

            if control_clicked:
                print(
                    f"[{self.ticker}] playback control clicked; deferring final "
                    "confirmation to the OS audio probe",
                    flush=True,
                )
                return True

            for candidate_page in self._playback_pages(page):
                for frame in candidate_page.frames:
                    started = await asyncio.wait_for(
                        frame.evaluate(
                            """async () => {
                            const media = document.querySelector('video, audio');
                            if (!media) return false;
                            media.muted = false;
                            media.volume = 1;
                            const attempt = media.play()
                                .then(() => !media.paused && !media.muted && media.volume > 0)
                                .catch(() => false);
                            const deadline = new Promise(resolve => {
                                window.setTimeout(() => resolve(false), 5000);
                            });
                            return await Promise.race([attempt, deadline]);
                        }"""
                        ),
                        timeout=7,
                    )
                    if started:
                        active_reason = await self._wait_for_active_playback(
                            page,
                            attempts=5,
                        )
                        if active_reason:
                            print(
                                f"[{self.ticker}] started HTML media element: "
                                f"{active_reason}",
                                flush=True,
                            )
                            return True
                        print(
                            f"[{self.ticker}] media.play() resolved; deferring final "
                            "confirmation to the OS audio probe",
                            flush=True,
                        )
                        return True
            print(f"[{self.ticker}] no active media or playable control found", flush=True)
            return False
        except Exception as exc:
            print(f"[{self.ticker}] media playback trigger skipped: {str(exc)[:120]}")
            return False


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open an IR page and trigger an earnings webcast.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--ir-url", required=True)
    parser.add_argument("--headed", action="store_true", help="Show the Chromium window.")
    parser.add_argument("--storage-state", default=None)
    parser.add_argument("--save-storage-state", default=None)
    parser.add_argument("--hold-seconds", type=float, default=float(os.getenv("WEBCAST_HOLD_SECONDS", "0")))
    parser.add_argument("--target-year", type=int, default=None)
    parser.add_argument("--target-quarter", default=None)
    parser.add_argument(
        "--executable-path",
        default=None,
        help="Chrome/Chromium executable path. Defaults to PLAYWRIGHT_CHROMIUM_EXECUTABLE or common system paths.",
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON result payload.")
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    agent = BrowserWebcastAgent(
        args.ticker,
        args.ir_url,
        headless=not args.headed,
        storage_state_path=args.storage_state,
        save_storage_state_path=args.save_storage_state,
        hold_seconds=args.hold_seconds,
        executable_path=args.executable_path,
        target_year=args.target_year,
        target_quarter=args.target_quarter,
    )
    result = await agent.run()
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(f"[{result.ticker}] success={result.success} final_url={result.final_url}")
        for url in result.media_candidates:
            print(f"media_candidate={url}")
        if result.error:
            print(f"error={result.error}")
    return 0 if result.success else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
