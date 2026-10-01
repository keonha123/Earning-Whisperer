"""Audit every IR entrypoint with historical or proxy webcast training surfaces."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from ... import database
    from ...operations import record_event
    from ...stt_worker.manager import STTWorkerManager, WebcastProbeResult
    from .internal_ir_discovery import InternalIRDiscovery
    from ..learning.webcast_learning_batch import (
        capture_environment,
        classify_probe_outcome,
        diagnose_probe_error,
        effective_audio_probe_timeout_seconds,
    )
    from ...collectors.streams.webcast_learning import is_non_replay_navigation_link
except ImportError:  # Allows direct script execution from data_pipeline.
    from data_pipeline import database
    from data_pipeline.operations import record_event
    from data_pipeline.stt_worker.manager import STTWorkerManager, WebcastProbeResult
    from data_pipeline.tools.replay.internal_ir_discovery import InternalIRDiscovery
    from data_pipeline.tools.learning.webcast_learning_batch import (
        capture_environment,
        classify_probe_outcome,
        diagnose_probe_error,
        effective_audio_probe_timeout_seconds,
    )
    from data_pipeline.collectors.streams.webcast_learning import is_non_replay_navigation_link


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_DIR = (
    REPO_ROOT
    / "data_pipeline"
    / ".runtime"
    / "operations"
    / "training-surface-audit"
)
REVIEW_QUEUE_ORDER = (
    "audio_proven",
    "human_downstream",
    "entrypoint_review",
    "automatic_retry",
)
BATCH_QUEUE_ORDER = (
    "automatic_retry",
    "human_downstream",
    "entrypoint_review",
    "audio_proven",
)
INTERNAL_IR_CRAWL_RETRY_STATUSES = frozenset(
    {
        "candidate_discovery_retry",
        "no_training_surface",
        # A browser can stall while opening an issuer's event-detail template
        # even when its public HTML exposes the downstream webcast provider.
        # Crawl from the stable IR entrypoint and probe that provider directly.
        "navigation_failed",
    }
)
MEDIA_URL_PATTERN = re.compile(
    r"(?:events?\.q4inc\.com|media-server\.com|choruscall\.com|"
    r"webcasts?\.com|youtube\.com|youtu\.be|vimeo\.com|"
    r"virtualshareholdermeeting\.com|on24\.com|brightcove\.net|"
    r"(?:^|[/?&_.-])(?:attendee|mediaframe|player|starthere|viewer|vsm|webcast)"
    r"(?:$|[/?&_.=-]))",
    re.IGNORECASE,
)
# A different host alone is not enough to prove that a link is a playable
# webcast. Investor pages commonly link to PDF remarks and presentation
# downloads on a CDN, so those documents must not become downstream surfaces.
NON_MEDIA_URL_PATTERN = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|svg)(?:$|[?#])",
    re.IGNORECASE,
)
EARNINGS_CONTEXT_PATTERN = re.compile(
    r"\b(?:earnings|financial\s+results|quarter(?:ly)?|conference\s+call|"
    r"fiscal\s+(?:year|quarter))\b",
    re.IGNORECASE,
)
DISCOVERY_ARTICLE_PATH_PATTERN = re.compile(
    r"/(?:news(?:room)?|media|regulatory-news/news-details)/",
    re.IGNORECASE,
)
EVENT_DETAIL_PATH_PATTERN = re.compile(
    r"/(?:events?|event[-_]detail|event[-_]details|conference[-_]call)/",
    re.IGNORECASE,
)
IR_ARCHIVE_TARGET_URL_PATTERN = re.compile(
    r"https?://\S+/(?:[^\s/]+/)*events?[-_/](?:and[-_/])?presentations"
    r"(?:/default\.aspx)?(?:[?#]\S*)?$",
    re.IGNORECASE,
)
WSW_REGISTRATION_ROUTE_PATTERN = re.compile(
    r"https?://(?:www\.)?wsw\.com/\S*/register\.aspx(?:[?#]\S*)?$",
    re.IGNORECASE,
)
REGISTRATION_SUCCESS_PATTERN = re.compile(
    r"registration\s+(?:form\s+)?(?:detected|completed|accepted)|"
    r"registration\s+fields\s+prepared|registered\s+player",
    re.IGNORECASE,
)
REPORTED_SURFACE_URL_PATTERN = re.compile(
    r"(?:webcast target opened|embedded webcast target opened|"
    r"opening direct replay candidate|opening candidate href directly|"
    r"click target stabilized|replay surface fallback[^\n]*?\burl=)[:\s]+"
    r"(https?://[^\s\]|)>]+)",
    re.IGNORECASE,
)
TARGET_URL_OUTPUT_PATTERN = re.compile(
    r"(?:webcast target opened|embedded webcast target opened|"
    r"opening direct replay candidate|opening candidate href directly|"
    r"click target stabilized|media_candidate=)[:\s]+"
    r"(https?://[^\s\]|)>]+)",
    re.IGNORECASE,
)
PROBE_OUTCOME_PRIORITY = {
    # Keep the result that travelled furthest through the downstream pipeline.
    # A later retry of the generic IR page must not hide a provider page that
    # already reached registration, playback, or the audio device.
    "audible": 100,
    "no_audio": 90,
    "playback_failed": 80,
    "registration_failed": 75,
    "registration_preview": 74,
    "registration_required": 74,
    "auth_required": 73,
    "not_live_yet": 70,
    "expired": 65,
    "blocked": 60,
    "capture_runtime_failed": 50,
    "not_found": 45,
    "navigation_failed": 40,
    "candidate_discovery_retry": 30,
    "no_training_surface": 20,
    "entrypoint_missing": 10,
    "error": 0,
}


@dataclass(frozen=True)
class CandidateProbeAttempt:
    """One attempted replay candidate and its independently classified result."""

    result: WebcastProbeResult
    selected_url: str | None
    status: str
    surface_kind: str


def choose_preferred_probe_attempt(
    attempts: list[CandidateProbeAttempt],
) -> CandidateProbeAttempt | None:
    """Choose the most useful candidate result without letting fallback erase it."""
    if not attempts:
        return None
    return max(
        attempts,
        key=lambda attempt: (
            PROBE_OUTCOME_PRIORITY.get(attempt.status, 0),
            int(attempt.surface_kind in {"earnings", "webcast", "proxy"}),
            int(bool(attempt.selected_url)),
        ),
    )


def should_stop_candidate_probe(
    status: str,
    *,
    audible: bool,
    allow_registration_submission: bool,
) -> bool:
    """Stop once a candidate reaches a useful downstream gate.

    When form submission is intentionally disabled, trying more candidates
    after a registration/auth gate only creates traffic and can obscure the
    exact handoff point. A playback failure remains retryable because another
    candidate may still contain a usable player.
    """
    if audible or status == "audible":
        return True
    return (
        not allow_registration_submission
        and status in {"registration_required", "registration_preview", "auth_required"}
    )


def effective_probe_timeout_seconds(args: argparse.Namespace) -> int:
    """Keep the audit compatible with the shared batch timeout policy."""
    return effective_audio_probe_timeout_seconds(
        configured_timeout_seconds=args.timeout_seconds,
        playback_timeout_seconds=args.playback_timeout_seconds,
        warmup_seconds=args.warmup_seconds,
        audio_wait_seconds=args.audio_wait_seconds,
    )


def extract_registration_preview(output: str) -> dict[str, Any] | None:
    """Extract the browser's value-free registration preview record."""
    for line in reversed(str(output or "").splitlines()):
        match = re.search(r"\bREGISTRATION_PREVIEW\s+(\{.*\})\s*$", line)
        if not match:
            continue
        try:
            preview = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(preview, dict):
            return preview
    return None


def export_registration_approval_template(path_value: str) -> Path:
    """Write disabled-by-default approvals from persisted preview evidence."""
    raw_path = str(path_value or "").strip()
    if not raw_path:
        raise ValueError("approval template path is required")
    path = Path(raw_path).expanduser()
    records = database.get_webcast_training_surface_targets()
    approvals: dict[str, dict[str, Any]] = {}
    for record in records:
        preview = extract_registration_preview(str(record.get("last_output") or ""))
        if not preview:
            continue
        ticker = str(record.get("ticker") or preview.get("ticker") or "").upper()
        if not ticker:
            continue
        approvals[ticker] = {
            "approved": False,
            "destination_url": preview.get("destination_url", ""),
            "prepared_fields": sorted(
                str(field)
                for field in preview.get("prepared_fields", [])
                if str(field).strip()
            ),
            "consent_selected": bool(preview.get("consent_selected")),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "approvals": dict(sorted(approvals.items())),
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def should_try_internal_ir_crawl(status: str | None) -> bool:
    """Return whether a stable IR crawl can recover a downstream replay URL."""
    return str(status or "").strip().lower() in INTERNAL_IR_CRAWL_RETRY_STATUSES


def prior_event_detail_url(target: dict[str, Any]) -> str | None:
    """Return a prior same-issuer event page suitable for static link recovery."""
    if str(target.get("status") or "").lower() != "navigation_failed":
        return None
    ir_url = str(target.get("ir_url") or "").strip()
    selected_url = str(target.get("selected_url") or "").strip()
    if not ir_url or not selected_url:
        return None
    if urlparse(ir_url).netloc.lower() != urlparse(selected_url).netloc.lower():
        return None
    if not EVENT_DETAIL_PATH_PATTERN.search(urlparse(selected_url).path):
        return None
    return selected_url


def read_runtime_value(
    manager: STTWorkerManager,
    call: dict[str, Any],
    capture_env: dict[str, str],
    *keys: str,
) -> str | None:
    runtime = manager.build_isolated_capture_environment(call, capture_env)
    for key in keys:
        path_value = str(runtime.get(key) or "").strip()
        if not path_value:
            continue
        try:
            value = manager.host_runtime_artifact_path(path_value).read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            continue
        if value:
            return value
    return None


def selected_surface_url(
    manager: STTWorkerManager,
    call: dict[str, Any],
    capture_env: dict[str, str],
) -> str | None:
    value = read_runtime_value(
        manager,
        call,
        capture_env,
        "WEBCAST_ACTIVE_PLAYER_URL_FILE",
        "WEBCAST_LAST_TARGET_URL_FILE",
    )
    if not value:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def reported_surface_url(output: str, *, ir_url: str | None = None) -> str | None:
    """Recover a navigated surface when the per-probe artifact was unavailable."""
    original = str(ir_url or "").strip().rstrip("/")
    matches = list(REPORTED_SURFACE_URL_PATTERN.finditer(str(output or "")))
    for match in reversed(matches):
        value = match.group(1).rstrip(".,;:)")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if value.rstrip("/") == original:
            continue
        if is_non_media_url(value):
            continue
        return value
    return None


def is_non_media_url(url: str | None) -> bool:
    """Return whether a URL is a document/download rather than replay media."""
    value = str(url or "").strip()
    if not value:
        return False
    return bool(NON_MEDIA_URL_PATTERN.search(urlparse(value).path))


def output_target_urls(output: str) -> list[str]:
    """Return URLs named by replay-target log lines."""
    return [
        match.group(1).rstrip(".,;:)")
        for match in TARGET_URL_OUTPUT_PATTERN.finditer(str(output or ""))
    ]


def clicked_candidate_evidence(output: str) -> str:
    match = re.search(
        r"clicking webcast candidate:(.*?)(?:"
        r"click target stabilized|webcast target opened|checking webcast registration)",
        output,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return " ".join(match.group(1).split())[:1000]
    # A failed click may be followed directly by a bracketed log line, so it
    # has no later success marker. The candidate line itself is still proof
    # that discovery reached the downstream stage.
    fallback = re.search(
        r"clicking webcast candidate:(.*?)(?=\n\[[^\]]+\]\s|\Z)",
        output,
        re.IGNORECASE | re.DOTALL,
    )
    return " ".join(fallback.group(1).split())[:1000] if fallback else ""


def has_downstream_surface_evidence(
    output: str,
    *,
    selected_url: str | None,
    ir_url: str | None,
) -> bool:
    """Return whether discovery reached a candidate, form, player, or media URL."""
    selected_host = urlparse(selected_url).netloc.lower() if selected_url else ""
    ir_host = urlparse(str(ir_url or "")).netloc.lower()
    selected_is_non_media = is_non_media_url(selected_url)
    target_urls = output_target_urls(output)
    only_non_media_targets = bool(target_urls) and all(
        is_non_media_url(target_url) for target_url in target_urls
    )
    selected_media = bool(
        selected_url
        and not selected_is_non_media
        and (
            MEDIA_URL_PATTERN.search(selected_url)
            or (selected_host and ir_host and selected_host != ir_host)
        )
    )
    candidate_click = (
        not selected_is_non_media
        and not only_non_media_targets
        and bool(clicked_candidate_evidence(output))
    )
    if selected_media or candidate_click or (
        not selected_is_non_media
        and not only_non_media_targets
        and re.search(r"clicking webcast candidate:", output, re.IGNORECASE)
    ):
        return True
    if re.search(
        r"REPLAY_TRAINING_PROXY|"
        r"checking webcast registration|"
        r"registration (?:completed|form detected|fields prepared|required)|"
        r"registered playback already active|"
        r"provider media discovered",
        output,
        re.IGNORECASE,
    ):
        return True
    if only_non_media_targets:
        return False
    return bool(
        re.search(
            r"^(?:\[[^\]]+\]\s+PLAYBACK_READY\s+path=|"
            r"PLAYBACK_READY_CONFIRMED\b)",
            output,
            re.IGNORECASE | re.MULTILINE,
        )
    )


def infer_surface_kind(
    result: WebcastProbeResult,
    *,
    selected_url: str | None,
    ir_url: str | None,
    status: str,
) -> str:
    output = result.output
    if "REPLAY_TRAINING_PROXY" in output:
        return "proxy"
    candidate_evidence = clicked_candidate_evidence(output)
    if EARNINGS_CONTEXT_PATTERN.search(candidate_evidence):
        return "earnings"
    if status in {"no_training_surface", "candidate_discovery_retry"}:
        return "none"
    if selected_url and not is_non_media_url(selected_url):
        if selected_url.rstrip("/") != str(ir_url or "").rstrip("/"):
            return "webcast"
        if "PLAYBACK_READY" in output or result.audible:
            return "webcast"
    if has_downstream_surface_evidence(
        output,
        selected_url=selected_url,
        ir_url=ir_url,
    ):
        return "webcast"
    return "unknown"


def classify_training_surface_outcome(
    result: WebcastProbeResult,
    *,
    selected_url: str | None,
    ir_url: str | None,
) -> str:
    if result.audible:
        return "audible"
    if not str(ir_url or "").strip():
        return "entrypoint_missing"

    combined_output = f"{result.error or ''}\n{result.output or ''}"
    classified = classify_probe_outcome(False, combined_output)
    diagnosis = diagnose_probe_error(combined_output)
    if re.search(r"\bREGISTRATION_PREVIEW\b", combined_output, re.IGNORECASE):
        return "registration_preview"
    # Lifecycle and access barriers take precedence over generic player
    # symptoms. A scheduled event may emit the same "no active media" text
    # while correctly waiting for its broadcast window, and MetaMeetings can
    # redirect a public replay to its attendee sign-in page.
    if re.search(
        r"\bnot_live_yet\b|scheduled event date is in the future|"
        r"return to this page a few minutes before the start|"
        r"you can access the webcast up to 15 minutes before",
        combined_output,
        re.IGNORECASE,
    ):
        return "not_live_yet"
    if classified in {"blocked", "auth_required", "registration_required", "not_live_yet", "not_found", "expired"}:
        return classified
    if re.search(
        r"metameetings\.net/[^\s]+(?:general_signin|participants/saml/sign_in|"
        r"(?:public/)?signin)|"
        r"general_signin|participants/saml/sign_in|(?:public/)?signin|"
        r"attendee\s+log\s*in",
        result.output,
        re.IGNORECASE,
    ) and (
        (selected_url and "metameetings.net" in urlparse(selected_url).netloc.lower())
        or "metameetings.net" in result.output.lower()
    ):
        return "auth_required"
    if re.search(
        r"access\s+to\s+the\s+player\s+was\s+denied|"
        r"player\s+access\s+was\s+denied|code\s*[:#]?\s*1011",
        combined_output,
        re.IGNORECASE,
    ):
        return "blocked"
    selected_path = urlparse(selected_url).path if selected_url else ""
    article_discovery_failed = bool(
        selected_url
        and DISCOVERY_ARTICLE_PATH_PATTERN.search(selected_path)
        and re.search(
            r"webcast button not found|no active media or playable control found|"
            r"playback_ready_timed_out|no visible registration controls",
            combined_output,
            re.IGNORECASE,
        )
        and not re.search(
            r"embedded webcast target opened|registration form detected|"
            r"registration fields prepared|registered playback already active|"
            r"media_candidate=|"
            r"provider media discovered|PLAYBACK_READY_CONFIRMED|"
            r"clicking player control",
            result.output,
            re.IGNORECASE,
        )
    )
    if article_discovery_failed:
        # An old earnings/news article can be a useful discovery page while
        # still containing no replay surface. It is a retryable discovery
        # miss, not proof that the IR entrypoint has no usable media.
        return "candidate_discovery_retry"
    direct_target_navigation_failed = bool(
        re.search(
            r"opening direct replay candidate:|direct replay candidate navigation "
            r"(?:warning|timed out)|webcast target opened:\s*about:blank",
            combined_output,
            re.IGNORECASE,
        )
        and re.search(
            r"about:blank|navigation warning|navigation timed out",
            combined_output,
            re.IGNORECASE,
        )
        and not re.search(
            r"registration (?:form|completed)|registered player|media_candidate=|"
            r"provider media discovered|PLAYBACK_READY(?:_CONFIRMED|\s+path=)",
            combined_output,
            re.IGNORECASE,
        )
    )
    if direct_target_navigation_failed:
        return "navigation_failed"
    downstream_evidence = has_downstream_surface_evidence(
        result.output,
        selected_url=selected_url,
        ir_url=ir_url,
    )
    archive_navigation_attempted = bool(
        re.search(
            r"opening replay archive view|opening replay event detail|"
            r"scanning historical replay page|no playback control; opening archive fallback",
            result.output,
            re.IGNORECASE,
        )
    )
    if archive_navigation_attempted and not downstream_evidence and re.search(
        r"PLAYBACK_READY_TIMED_OUT|navigation timed out|page ready timed out",
        combined_output,
        re.IGNORECASE,
    ):
        return "candidate_discovery_retry"
    if re.search(
        r"chrome-error://|net::ERR_|ERR_(?:NAME|CONNECTION|TIMED|ADDRESS|NETWORK)",
        result.output,
        re.IGNORECASE,
    ):
        return "navigation_failed"
    if diagnosis == "download_response" or re.search(
        r"page[- ]not[- ]found|about:blank|download is starting",
        combined_output,
        re.IGNORECASE,
    ):
        return "candidate_discovery_retry"

    # WSW can leave an old event on its registration route even after the
    # form has been submitted. With no player or media evidence, this is an
    # expired replay surface rather than an activation failure to generalize.
    stale_wsw_registration = bool(
        selected_url
        and WSW_REGISTRATION_ROUTE_PATTERN.search(selected_url)
        and REGISTRATION_SUCCESS_PATTERN.search(combined_output)
        and re.search(
            r"PLAYBACK_READY_TIMED_OUT|audio probe timed out|"
            r"no active media|no playable control|player did not become active",
            combined_output,
            re.IGNORECASE,
        )
        and not re.search(
            r"PLAYBACK_READY_CONFIRMED|media_candidate=|provider media discovered|"
            r"registered playback already active",
            combined_output,
            re.IGNORECASE,
        )
    )
    if stale_wsw_registration:
        return "expired"

    archive_target_only = bool(
        IR_ARCHIVE_TARGET_URL_PATTERN.search(combined_output)
        and not re.search(
            r"embedded webcast target opened|registration (?:form|completed)|"
            r"registered player|media_candidate=|provider media discovered|"
            r"PLAYBACK_READY(?:_CONFIRMED|\s+path=)",
            combined_output,
            re.IGNORECASE,
        )
    )
    if archive_target_only and re.search(
        r"PLAYBACK_READY_TIMED_OUT|audio probe timed out|"
        r"navigation timed out|page ready timed out",
        combined_output,
        re.IGNORECASE,
    ):
        return "candidate_discovery_retry"

    event_detail_only = bool(
        re.search(
            r"(?:opening candidate href directly|click target stabilized):\s*"
            r"https?://\S*(?:event[-_]details?|event[-_]detail|conference[-_]call)\S*",
            combined_output,
            re.IGNORECASE,
        )
        and not REGISTRATION_SUCCESS_PATTERN.search(combined_output)
        and not re.search(
            r"webcast target opened|embedded webcast target opened|"
            r"media_candidate=|provider media discovered|"
            r"PLAYBACK_READY(?:_CONFIRMED|\s+path=)",
            combined_output,
            re.IGNORECASE,
        )
    )
    selected_is_ir_detail = bool(
        selected_url
        and ir_url
        and urlparse(selected_url).netloc.lower() == urlparse(ir_url).netloc.lower()
        and EVENT_DETAIL_PATH_PATTERN.search(urlparse(selected_url).path)
    )
    if event_detail_only or (
        selected_is_ir_detail
        and not REGISTRATION_SUCCESS_PATTERN.search(combined_output)
        and not re.search(
            r"media_candidate=|provider media discovered|"
            r"PLAYBACK_READY(?:_CONFIRMED|\s+path=)",
            combined_output,
            re.IGNORECASE,
        )
    ):
        return "candidate_discovery_retry"
    if re.search(r"\bAUDIO_NOT_DETECTED\b", combined_output, re.IGNORECASE):
        # The player reached a concrete media surface and the isolated audio
        # monitor completed its observation window. This is distinct from a
        # player activation failure; it may be a genuinely silent asset.
        return "no_audio"
    if downstream_evidence and re.search(
        r"playback (?:was )?not detected|no active media|"
        r"no playable control|registered player did not become active|"
        r"audio probe timed out",
        combined_output,
        re.IGNORECASE,
    ):
        return "playback_failed"

    if classified == "no_candidate":
        return "playback_failed" if downstream_evidence else "candidate_discovery_retry"
    if diagnosis == "registration_failed":
        return "registration_failed"
    if diagnosis in {
        "playback_activation_failed",
        "player_control_missing",
        "learned_recipe_replay_failed",
        "player_interaction_timeout",
        "playback_ready_timeout",
    }:
        return "playback_failed" if downstream_evidence else "candidate_discovery_retry"
    if re.search(r"audio probe timed out", combined_output, re.IGNORECASE):
        return "playback_failed" if downstream_evidence else "candidate_discovery_retry"
    if diagnosis == "navigation_timeout":
        return "navigation_failed"
    if classified in {"capture_runtime_failed", "no_audio"}:
        return classified
    return "error"


def has_training_surface_candidate(record: dict[str, Any]) -> bool:
    """Return whether an audit reached a video candidate or a downstream gate."""
    return has_downstream_surface_evidence(
        str(record.get("last_output") or ""),
        selected_url=str(record.get("selected_url") or "") or None,
        ir_url=str(record.get("ir_url") or "") or None,
    )


def classify_training_surface_review_queue(record: dict[str, Any]) -> str:
    """Route one ticker without declaring an IR URL invalid automatically."""
    status = str(record.get("status") or "pending").lower()
    if status == "audible" or int(record.get("audible_count") or 0) > 0:
        return "audio_proven"
    if has_training_surface_candidate(record):
        return "human_downstream"
    if status in {"candidate_discovery_retry", "no_training_surface", "playback_failed"}:
        # A missing proxy candidate is never a terminal human-search result.
        # The replay proxy broadens its link search on the next attempt.
        return "automatic_retry"
    if status in {"blocked", "navigation_failed", "not_found", "entrypoint_missing"}:
        return "entrypoint_review"
    return "automatic_retry"


def training_surface_review_reason(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "pending").lower()
    queue = classify_training_surface_review_queue(record)
    if queue == "audio_proven":
        return "audio_detected"
    if status in {"candidate_discovery_retry", "no_training_surface"}:
        return "replay_surface_retry"
    reasons = {
        "auth_required": "authentication_required",
        "blocked": "access_blocked",
        "expired": "candidate_expired",
        "navigation_failed": "navigation_failed",
        "no_audio": "audio_signal_missing",
        "no_training_surface": "replay_surface_retry",
        "candidate_discovery_retry": "replay_surface_retry",
        "not_found": "entrypoint_not_found",
        "playback_failed": "playback_activation_failed",
        "registration_failed": "registration_failed",
        "registration_preview": "registration_preview_only",
        "registration_required": "registration_required",
    }
    return reasons.get(status, "automatic_retry_required")


def build_training_surface_review_queues(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    queues: dict[str, list[dict[str, Any]]] = {
        queue: [] for queue in REVIEW_QUEUE_ORDER
    }
    for record in records:
        queue = classify_training_surface_review_queue(record)
        output = str(record.get("last_output") or "")
        item = {
            "ticker": str(record.get("ticker") or "").upper(),
            "company_name": record.get("company_name"),
            "queue": queue,
            "reason": training_surface_review_reason(record),
            "status": str(record.get("status") or "pending").lower(),
            "surface_kind": str(record.get("surface_kind") or "unknown").lower(),
            "ir_url": record.get("ir_url"),
            "selected_url": record.get("selected_url"),
            "candidate_label": clicked_candidate_evidence(output) or None,
            "attempt_count": int(record.get("attempt_count") or 0),
            "audible_count": int(record.get("audible_count") or 0),
            "last_attempt_at": record.get("last_attempt_at"),
            "last_error": record.get("last_error"),
        }
        queues[queue].append(item)

    reason_priority = {
        "audio_signal_missing": 0,
        "playback_activation_failed": 1,
        "registration_failed": 2,
        "registration_required": 3,
        "authentication_required": 4,
        "candidate_expired": 5,
        "access_blocked": 6,
        "navigation_failed": 7,
        "replay_surface_retry": 8,
        "entrypoint_not_found": 9,
        "automatic_retry_required": 10,
    }
    for items in queues.values():
        items.sort(
            key=lambda item: (
                reason_priority.get(str(item["reason"]), 99),
                -int(item["attempt_count"]),
                str(item["ticker"]),
            )
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_tickers": len(records),
        "counts": {queue: len(queues[queue]) for queue in REVIEW_QUEUE_ORDER},
        "queues": queues,
        "policy": {
            "audio_proven": "registration, playback, and virtual audio passed",
            "human_downstream": "a candidate or downstream gate exists; human intervention should continue from that point",
            "entrypoint_review": "access or navigation prevented candidate assessment",
            "automatic_retry": "retry candidate discovery and technical or incomplete outcomes before human review",
            "invalid_entrypoint": "never assigned automatically; requires repeated access evidence",
        },
    }


def _review_item_domain(item: dict[str, Any]) -> str:
    url = str(item.get("selected_url") or item.get("ir_url") or "")
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.") or "unknown"


def build_training_surface_batch_plan(
    classification: dict[str, Any],
    *,
    batch_size: int = 50,
) -> dict[str, Any]:
    """Build stable, stratified batches without leaving a tiny final batch."""
    requested_size = max(1, int(batch_size))
    total = int(classification.get("total_tickers") or 0)
    queues = classification.get("queues") or {}
    queue_total = sum(len(queues.get(queue) or []) for queue in REVIEW_QUEUE_ORDER)
    if total != queue_total:
        raise ValueError(
            f"classification total mismatch: total={total} queues={queue_total}"
        )
    if total == 0:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requested_batch_size": requested_size,
            "batch_count": 0,
            "total_tickers": 0,
            "source_counts": classification.get("counts") or {},
            "batches": [],
        }

    batch_count = max(1, int((total / requested_size) + 0.5))
    base_size, larger_batch_count = divmod(total, batch_count)
    capacities = [
        base_size + (1 if index < larger_batch_count else 0)
        for index in range(batch_count)
    ]
    working = [
        {
            "capacity": capacities[index],
            "items": [],
            "queue_counts": Counter(),
            "domain_counts": Counter(),
        }
        for index in range(batch_count)
    ]

    for queue in BATCH_QUEUE_ORDER:
        for item in queues.get(queue) or []:
            domain = _review_item_domain(item)
            eligible = [
                index
                for index, batch in enumerate(working)
                if len(batch["items"]) < batch["capacity"]
            ]
            selected_index = min(
                eligible,
                key=lambda index: (
                    working[index]["queue_counts"][queue],
                    working[index]["domain_counts"][domain],
                    len(working[index]["items"]) / working[index]["capacity"],
                    index,
                ),
            )
            batch = working[selected_index]
            batch["items"].append(dict(item))
            batch["queue_counts"][queue] += 1
            batch["domain_counts"][domain] += 1

    batches: list[dict[str, Any]] = []
    for index, batch in enumerate(working, start=1):
        items = list(batch["items"])
        controls = [item for item in items if item["queue"] == "audio_proven"]
        unresolved = [item for item in items if item["queue"] != "audio_proven"]
        preflight = controls[:2]
        ordered_items = [*preflight, *unresolved, *controls[2:]]
        reason_counts = Counter(str(item["reason"]) for item in items)
        batches.append(
            {
                "batch_index": index,
                "batch_id": f"batch-{index:02d}",
                "size": len(ordered_items),
                "capacity": int(batch["capacity"]),
                "queue_counts": {
                    queue: int(batch["queue_counts"][queue])
                    for queue in REVIEW_QUEUE_ORDER
                },
                "reason_counts": dict(sorted(reason_counts.items())),
                "preflight_tickers": [item["ticker"] for item in preflight],
                "tickers": [item["ticker"] for item in ordered_items],
                "items": ordered_items,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_batch_size": requested_size,
        "batch_count": batch_count,
        "total_tickers": total,
        "source_counts": classification.get("counts") or {},
        "batches": batches,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if hasattr(value, "as_tuple"):
        return int(value)
    return value


def write_classification_report(*, report_dir: Path) -> tuple[Path, dict[str, Any]]:
    report_dir.mkdir(parents=True, exist_ok=True)
    classification = build_training_surface_review_queues(
        database.get_webcast_training_surface_details()
    )
    classification = _json_ready(classification)
    path = report_dir / "classification-latest.json"
    temporary_path = report_dir / "classification-latest.json.tmp"
    temporary_path.write_text(
        json.dumps(classification, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return path, classification


def write_batch_plan(
    *,
    report_dir: Path,
    batch_size: int,
) -> tuple[Path, dict[str, Any]]:
    _, classification = write_classification_report(report_dir=report_dir)
    plan = _json_ready(
        build_training_surface_batch_plan(
            classification,
            batch_size=batch_size,
        )
    )
    path = report_dir / "batch-plan.json"
    temporary_path = report_dir / "batch-plan.json.tmp"
    temporary_path.write_text(
        json.dumps(plan, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return path, plan


def write_progress_report(
    *,
    report_dir: Path,
    processed: int,
    selected: int,
    run_counts: Counter[str],
    started_at: datetime,
    completed: bool,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    classification_path, classification = write_classification_report(
        report_dir=report_dir
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at.isoformat(),
        "completed": completed,
        "selected_tickers": selected,
        "processed_tickers": processed,
        "run_status_counts": dict(sorted(run_counts.items())),
        "coverage": database.get_webcast_training_surface_coverage(),
        "summary": database.get_webcast_training_surface_summary(),
        "classification_counts": classification["counts"],
        "classification_report": str(classification_path),
        "high_risk_ir_entrypoints": database.get_webcast_training_surface_risks(),
    }
    report = _json_ready(report)
    latest_path = report_dir / "latest.json"
    temporary_path = report_dir / "latest.json.tmp"
    temporary_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    temporary_path.replace(latest_path)
    if completed:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        completed_path = report_dir / f"audit-{timestamp}.json"
        completed_path.write_text(
            json.dumps(report, ensure_ascii=True, indent=2, default=str),
            encoding="utf-8",
        )
    return latest_path


async def run_audit(args: argparse.Namespace) -> int:
    recovered = database.recover_stale_webcast_training_surface_audits()
    if recovered:
        print(
            f"[TrainingSurfaceAudit] recovered {recovered} interrupted probes",
            flush=True,
        )

    report_dir = Path(args.report_dir).expanduser()
    if args.classify_only:
        report_path, classification = write_classification_report(
            report_dir=report_dir
        )
        counts = ", ".join(
            f"{queue}={classification['counts'][queue]}"
            for queue in REVIEW_QUEUE_ORDER
        )
        print(f"[TrainingSurfaceAudit] classification: {counts}", flush=True)
        print(f"[TrainingSurfaceAudit] report={report_path}", flush=True)
        return 0
    if args.plan_batches:
        plan_path, plan = write_batch_plan(
            report_dir=report_dir,
            batch_size=args.batch_size,
        )
        sizes = ",".join(str(batch["size"]) for batch in plan["batches"])
        print(
            f"[TrainingSurfaceAudit] batch-plan: count={plan['batch_count']} "
            f"sizes={sizes}",
            flush=True,
        )
        print(f"[TrainingSurfaceAudit] plan={plan_path}", flush=True)
        return 0

    requested_ticker_order = [
        ticker.strip().upper()
        for ticker in args.tickers.split(",")
        if ticker.strip()
    ]
    if args.batch_plan:
        if args.batch_index is None:
            raise SystemExit("--batch-index is required with --batch-plan")
        plan_path = Path(args.batch_plan).expanduser()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        matching_batches = [
            batch
            for batch in plan.get("batches") or []
            if int(batch.get("batch_index") or 0) == args.batch_index
        ]
        if not matching_batches:
            raise SystemExit(
                f"batch index {args.batch_index} was not found in {plan_path}"
            )
        requested_ticker_order = [
            str(ticker).upper() for ticker in matching_batches[0].get("tickers") or []
        ]
    requested_tickers = set(requested_ticker_order)
    requested_statuses = {
        status.strip().lower()
        for status in args.statuses.split(",")
        if status.strip()
    }
    targets = database.get_webcast_training_surface_targets()
    if requested_tickers:
        targets_by_ticker = {
            str(target["ticker"]).upper(): target for target in targets
        }
        targets = [
            targets_by_ticker[ticker]
            for ticker in requested_ticker_order
            if ticker in targets_by_ticker
        ]
    if requested_statuses:
        targets = [
            target
            for target in targets
            if str(target.get("status") or "pending").lower() in requested_statuses
        ]
    if args.limit is not None:
        targets = targets[: max(1, args.limit)]
    if not targets:
        print("[TrainingSurfaceAudit] No matching active IR targets.", flush=True)
        return 0

    started_at = datetime.now(timezone.utc)
    manager = STTWorkerManager()
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    capture_env = {
        **capture_environment(args),
        "WEBCAST_LIFECYCLE": "replay",
        # This audit intentionally uses any historical webcast-like event as
        # a proxy so registration, playback, and audio can be trained before
        # a real earnings call is live.
        "WEBCAST_REPLAY_TRAINING_PROXY": "true",
    }
    stored_replay_targets_by_ticker: dict[str, list[dict[str, Any]]] = {}
    if not args.disable_internal_ir_crawl:
        try:
            stored_replay_targets = database.get_historical_replay_targets(
                include_registration_required=True,
                include_auth_required=True,
            )
        except Exception as exc:
            stored_replay_targets = []
            print(
                "[TrainingSurfaceAudit] stored replay candidates unavailable: "
                f"{str(exc)[:160]}",
                flush=True,
            )
        source_priority = {
            "browser_resolved": 0,
            "internal_crawl": 1,
            "serper_direct": 2,
            "serper_announcement": 3,
            "serper_archive": 4,
            "ir_entrypoint": 8,
        }
        for replay_target in stored_replay_targets:
            ticker = str(replay_target.get("ticker") or "").upper()
            target_url = str(replay_target.get("target_url") or "").strip()
            if not ticker or not target_url:
                continue
            source_title = str(replay_target.get("source_title") or "").strip()
            if is_non_replay_navigation_link(target_url, source_title):
                continue
            stored_replay_targets_by_ticker.setdefault(ticker, []).append(
                replay_target
            )
        for ticker, replay_targets in stored_replay_targets_by_ticker.items():
            replay_targets.sort(
                key=lambda target: (
                    source_priority.get(
                        str(target.get("source_kind") or "").lower(),
                        7,
                    ),
                    -int(target.get("audible_count") or 0),
                    str(target.get("target_url") or ""),
                )
            )
    timeout_seconds = effective_probe_timeout_seconds(args)
    run_counts: Counter[str] = Counter()
    processed = 0
    skipped = 0
    report_lock = asyncio.Lock()

    print(
        f"[TrainingSurfaceAudit] selected={len(targets)} "
        f"concurrency={args.concurrency} timeout={timeout_seconds}s "
        f"registration_submission={args.allow_registration_submission}",
        flush=True,
    )
    if args.timeout_seconds and timeout_seconds > args.timeout_seconds:
        print(
            "[TrainingSurfaceAudit] raised probe timeout to cover browser and "
            f"media fallback audio windows: {args.timeout_seconds}s -> "
            f"{timeout_seconds}s",
            flush=True,
        )

    async def probe(target: dict[str, Any]) -> str | None:
        nonlocal processed, skipped
        async with semaphore:
            if not database.claim_webcast_training_surface_target(
                target,
                cooldown_minutes=0 if args.force else args.cooldown_minutes,
            ):
                skipped += 1
                return None

            ticker = str(target["ticker"]).upper()
            ir_url = str(target.get("ir_url") or "").strip()
            call = {
                "id": f"training-surface-{ticker}",
                "ticker": ticker,
                "ir_url": ir_url,
                "call_year": None,
                "quarter": None,
            }
            candidate_calls = [call]
            initial_status = str(target.get("status") or "").lower()
            if ir_url and not args.disable_internal_ir_crawl:
                seen_urls = {ir_url.rstrip("/")}
                stored_candidates = stored_replay_targets_by_ticker.get(ticker, [])
                stored_candidate_count = 0
                for index, replay_target in enumerate(
                    stored_candidates[: max(0, args.stored_replay_candidates)]
                ):
                    target_url = str(replay_target.get("target_url") or "").strip()
                    if not target_url or target_url.rstrip("/") in seen_urls:
                        continue
                    seen_urls.add(target_url.rstrip("/"))
                    candidate_calls.insert(
                        index,
                        {
                            **call,
                            "id": f"{call['id']}-stored-{index}",
                            "replay_target_url": target_url,
                        },
                    )
                    stored_candidate_count += 1
                if stored_candidate_count:
                    print(
                        f"[TrainingSurfaceAudit] {ticker} stored replay candidates="
                        f"{stored_candidate_count}",
                        flush=True,
                    )
                # Saved candidate URLs represent already-discovered provider
                # surfaces. Reuse them for every nonterminal status, including
                # registration and playback retries, instead of reopening a
                # generic issuer page first.
                internal_candidate_count = 0
                if should_try_internal_ir_crawl(initial_status):
                    try:
                        crawler = InternalIRDiscovery(
                            max_depth=args.internal_crawl_depth,
                            max_pages=args.internal_crawl_pages,
                            candidates_per_call=args.internal_crawl_candidates,
                            timeout_seconds=args.internal_crawl_timeout_seconds,
                        )
                        crawled = []
                        prior_detail_url = prior_event_detail_url(target)
                        if prior_detail_url:
                            crawled.extend(
                                await asyncio.to_thread(
                                    crawler.discover_provider_links_from_page,
                                    prior_detail_url,
                                    ir_url=ir_url,
                                    ticker=ticker,
                                )
                            )
                            if crawled:
                                print(
                                    f"[TrainingSurfaceAudit] {ticker} recovered provider links="
                                    f"{len(crawled)} from prior event detail",
                                    flush=True,
                                )
                        crawled.extend(
                            await asyncio.to_thread(crawler.discover_call, call)
                        )
                    except Exception as exc:
                        crawled = []
                        print(
                            f"[TrainingSurfaceAudit] {ticker} internal crawl skipped: "
                            f"{str(exc)[:160]}",
                            flush=True,
                        )
                    if crawled:
                        try:
                            saved = database.save_historical_replay_targets(
                                call,
                                [candidate.as_database_candidate() for candidate in crawled],
                            )
                            if saved:
                                print(
                                    f"[TrainingSurfaceAudit] {ticker} stored internal replay "
                                    f"candidates={saved}",
                                    flush=True,
                                )
                        except Exception as exc:
                            print(
                                f"[TrainingSurfaceAudit] {ticker} could not persist internal "
                                f"replay candidates: {str(exc)[:160]}",
                                flush=True,
                            )
                    for index, candidate in enumerate(crawled):
                        target_url = str(candidate.target_url or "").strip()
                        if not target_url or target_url.rstrip("/") in seen_urls:
                            continue
                        seen_urls.add(target_url.rstrip("/"))
                        candidate_calls.insert(
                            index,
                            {
                                **call,
                                "id": f"{call['id']}-internal-{index}",
                                "replay_target_url": target_url,
                            },
                        )
                        internal_candidate_count += 1
                if internal_candidate_count:
                    print(
                        f"[TrainingSurfaceAudit] {ticker} internal crawl candidates="
                        f"{internal_candidate_count}",
                        flush=True,
                    )

            candidate_attempts: list[CandidateProbeAttempt] = []
            for candidate_call in candidate_calls:
                if not str(candidate_call.get("ir_url") or "").strip():
                    attempt = WebcastProbeResult(
                        audible=False,
                        error="missing IR URL",
                        output="",
                        return_code=None,
                    )
                    candidate_attempts.append(
                        CandidateProbeAttempt(
                            result=attempt,
                            selected_url=None,
                            status="entrypoint_missing",
                            surface_kind="unknown",
                        )
                    )
                    continue
                attempt = await manager.probe_webcast_url_detailed(
                    candidate_call,
                    capture_env=capture_env,
                    timeout_seconds=timeout_seconds,
                )
                candidate_resolved_url = selected_surface_url(
                    manager,
                    candidate_call,
                    capture_env,
                ) or reported_surface_url(attempt.output, ir_url=ir_url) or str(
                    candidate_call.get("replay_target_url") or ""
                ).strip() or None
                candidate_status = classify_training_surface_outcome(
                    attempt,
                    selected_url=candidate_resolved_url,
                    ir_url=ir_url,
                )
                candidate_surface_kind = infer_surface_kind(
                    attempt,
                    selected_url=candidate_resolved_url,
                    ir_url=ir_url,
                    status=candidate_status,
                )
                candidate_attempts.append(
                    CandidateProbeAttempt(
                        result=attempt,
                        selected_url=candidate_resolved_url,
                        status=candidate_status,
                        surface_kind=candidate_surface_kind,
                    )
                )
                if should_stop_candidate_probe(
                    candidate_status,
                    audible=attempt.audible,
                    allow_registration_submission=args.allow_registration_submission,
                ):
                    break

            preferred_attempt = choose_preferred_probe_attempt(candidate_attempts)
            if preferred_attempt:
                result = preferred_attempt.result
                resolved_url = preferred_attempt.selected_url
                status = preferred_attempt.status
                surface_kind = preferred_attempt.surface_kind
            else:
                result = WebcastProbeResult(
                    audible=False,
                    error="missing IR URL",
                    output="",
                    return_code=None,
                )
                resolved_url = None
                status = classify_training_surface_outcome(
                    result,
                    selected_url=resolved_url,
                    ir_url=ir_url,
                )
                surface_kind = infer_surface_kind(
                    result,
                    selected_url=resolved_url,
                    ir_url=ir_url,
                    status=status,
                )
            database.record_webcast_training_surface_outcome(
                target,
                status=status,
                surface_kind=surface_kind,
                selected_url=resolved_url,
                error=result.error,
                output=result.output,
            )
            record_event(
                "training_surface_probe",
                ticker=ticker,
                status=status,
                error=database.redact_sensitive_text(result.error),
                surface_kind=surface_kind,
                selected_url=database.redact_sensitive_url(resolved_url),
                ir_url=ir_url,
            )

            async with report_lock:
                processed += 1
                run_counts[status] += 1
                if processed % max(1, args.report_every) == 0:
                    report_path = write_progress_report(
                        report_dir=report_dir,
                        processed=processed,
                        selected=len(targets),
                        run_counts=run_counts,
                        started_at=started_at,
                        completed=False,
                    )
                    print(
                        f"[TrainingSurfaceAudit] progress={processed}/{len(targets)} "
                        f"report={report_path}",
                        flush=True,
                    )

            safe_error = database.redact_sensitive_text(result.error)
            detail = f" detail={safe_error[:180]}" if safe_error else ""
            print(
                f"[TrainingSurfaceAudit] {ticker} status={status} "
                f"surface={surface_kind}"
                f" selected={database.redact_sensitive_url(resolved_url) or '-'}{detail}",
                flush=True,
            )
            if args.inter_target_delay_seconds > 0:
                await asyncio.sleep(args.inter_target_delay_seconds)
            return status

    tasks = [asyncio.create_task(probe(target)) for target in targets]
    for task in asyncio.as_completed(tasks):
        await task

    report_path = write_progress_report(
        report_dir=report_dir,
        processed=processed,
        selected=len(targets),
        run_counts=run_counts,
        started_at=started_at,
        completed=True,
    )
    summary = ", ".join(
        f"{status}={count}" for status, count in sorted(run_counts.items())
    ) or "no probes"
    print(
        f"[TrainingSurfaceAudit] complete: {summary}; "
        f"processed={processed} skipped={skipped}",
        flush=True,
    )
    print(
        f"[TrainingSurfaceAudit] coverage="
        f"{database.get_webcast_training_surface_coverage()}",
        flush=True,
    )
    print(f"[TrainingSurfaceAudit] report={report_path}", flush=True)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit every configured IR page by replaying earnings or proxy "
            "webcasts through registration, playback, and virtual audio."
        )
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--statuses", default="")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("WEBCAST_TRAINING_AUDIT_CONCURRENCY", "2")),
    )
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=int(os.getenv("WEBCAST_TRAINING_AUDIT_COOLDOWN_MINUTES", "10080")),
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help="Write current 503-ticker human-review queues without launching browsers.",
    )
    parser.add_argument(
        "--plan-batches",
        action="store_true",
        help="Write a fixed stratified batch plan without launching browsers.",
    )
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--batch-plan", default="")
    parser.add_argument("--batch-index", type=int, default=None)
    parser.add_argument("--allow-registration-submission", action="store_true")
    parser.add_argument(
        "--registration-preview-only",
        action="store_true",
        help=(
            "Fill detected registration forms and report redacted destinations/"
            "field names without submitting them."
        ),
    )
    parser.add_argument(
        "--registration-approval-file",
        default="",
        help=(
            "JSON approval manifest; submission is allowed only when the "
            "ticker, destination, prepared fields, and consent state match."
        ),
    )
    parser.add_argument(
        "--export-registration-approval-template",
        default="",
        help=(
            "Export a disabled-by-default JSON approval template from persisted "
            "registration previews without launching browsers."
        ),
    )
    parser.add_argument(
        "--disable-internal-ir-crawl",
        action="store_true",
        help="Do not crawl issuer-owned IR pages for replay candidates.",
    )
    parser.add_argument(
        "--internal-crawl-depth",
        type=int,
        default=int(os.getenv("IR_CRAWL_MAX_DEPTH", "3")),
    )
    parser.add_argument(
        "--internal-crawl-pages",
        type=int,
        default=int(os.getenv("IR_CRAWL_MAX_PAGES", "10")),
    )
    parser.add_argument(
        "--internal-crawl-candidates",
        type=int,
        default=int(os.getenv("IR_CRAWL_CANDIDATES_PER_CALL", "5")),
    )
    parser.add_argument(
        "--stored-replay-candidates",
        type=int,
        default=int(os.getenv("IR_STORED_REPLAY_CANDIDATES", "5")),
        help="Try up to this many previously saved replay URLs before crawling the IR page.",
    )
    parser.add_argument(
        "--internal-crawl-timeout-seconds",
        type=float,
        default=float(os.getenv("IR_CRAWL_TIMEOUT_SECONDS", "8")),
    )
    parser.add_argument("--disable-generalized-learning", action="store_true")
    parser.add_argument(
        "--audio-wait-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_TRAINING_AUDIT_AUDIO_WAIT_SECONDS", "20")),
    )
    parser.add_argument(
        "--audio-probe-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_LEARNING_AUDIO_PROBE_SECONDS", "2")),
    )
    parser.add_argument(
        "--warmup-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_TRAINING_AUDIT_WARMUP_SECONDS", "3")),
    )
    parser.add_argument(
        "--playback-timeout-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS", "90")),
    )
    parser.add_argument(
        "--audio-min-db",
        type=float,
        default=float(os.getenv("DATE_STREAM_AUDIO_MIN_DB", "-55")),
    )
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument(
        "--inter-target-delay-seconds",
        type=float,
        default=float(os.getenv("WEBCAST_TRAINING_AUDIT_INTER_TARGET_DELAY_SECONDS", "5")),
        help="Pause between sequential target probes to reduce burst traffic.",
    )
    parser.add_argument("--report-every", type=int, default=10)
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.export_registration_approval_template:
        path = export_registration_approval_template(
            args.export_registration_approval_template
        )
        print(f"[TrainingSurfaceAudit] approval template={path}", flush=True)
        return 0
    return asyncio.run(run_audit(args))


if __name__ == "__main__":
    raise SystemExit(main())
