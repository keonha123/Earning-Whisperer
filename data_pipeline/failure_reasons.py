"""Shared typed failure semantics for browser, retry policy and operations.

Compatibility wrappers keep the old reason/category APIs; new producers may
supply explicit stage/error_code dictionaries instead of reclassifying prose.
"""
from __future__ import annotations

import re
from typing import Any


def normalized_failure_text(error: Any) -> str:
    if isinstance(error, dict):
        error = " ".join(str(error.get(key) or "") for key in ("error_code", "reason", "error", "message"))
    return re.sub(r"[_-]+", " ", str(error or "").lower())


def classify_live_failure(error: Any) -> dict[str, str]:
    """Return stage, error_code, reason, next_action and display category.

    Genuine permission barriers always outrank internal guard/continuation
    markers. A form selector or transition failure alone is recoverable.
    """
    value = normalized_failure_text(error)
    external = re.sub(r"\bmedia fallback blocked\b", "", value)

    def result(stage, code, reason, action, category=None):
        output = {"stage": stage, "error_code": code, "reason": reason,
                  "next_action": action, "category": category or reason}
        if isinstance(error, dict):
            # Typed producer evidence takes precedence for observability, while
            # the conservative text classification still owns retry barriers.
            for key in ("stage", "error_code", "next_action"):
                if error.get(key):
                    output[key] = str(error[key])
        return output

    if not value.strip():
        return result("none", "NONE", "none", "none")
    if any(marker in external for marker in (
        "captcha", "human verification", "email login link", "email verification",
        "two factor", "2fa", "login required", "sign in required", "auth required",
        "registration already exists", "registration has ", "already registered",
        "login instructions", "registration submission is disabled", "registration approval required",
        "approval manifest", "registration preview", "submission not attempted",
    )):
        return result("registration", "AUTH_REQUIRED", "auth_required", "manual_authentication")
    if any(marker in external for marker in (
        "access denied", "cloudflare", "forbidden", "rate limit", "too many requests",
        "http 401", "http 403", "http 429", "page access blocked", "verify you are human",
    )):
        return result("access", "ACCESS_BLOCKED", "access_blocked", "manual_authentication")
    if any(marker in value for marker in (
        "form automation failed", "registration field unavailable", "registration form rejected",
        "registration submission did not transition", "registration submit control not found",
        "registration pending", "required field not found", "form validation failed",
    )):
        return result("registration", "FORM_AUTOMATION_FAILED", "form_automation_failed", "repair_form_and_retry")
    if "registration required" in value:
        return result("registration", "AUTH_REQUIRED", "auth_required", "manual_authentication")
    if "audio rescue budget unavailable" in value:
        return result("audio_storage", "AUDIO_RESCUE_BUDGET_UNAVAILABLE", "resource_capacity", "reclaim_closed_audio")
    if "audio rescue storage unavailable" in value:
        return result("audio_storage", "AUDIO_RESCUE_STORAGE_UNAVAILABLE", "resource_capacity", "inspect_audio_storage")
    if "blocked" in external:
        return result("access", "ACCESS_BLOCKED", "access_blocked", "manual_authentication")
    if "capacity wait" in value:
        return result("capacity", "CAPACITY_WAIT", "capacity_wait", "await_capture_slot")
    if 'verified replay source' in value:
        return result('capture_source', 'VERIFIED_REPLAY_SOURCE', 'replay_source',
                      'exclude_recording_and_rediscover', 'replay_source')
    if any(marker in value for marker in ("target event mismatch", "candidate ticker contradicts", "candidate year or quarter contradicts", "candidate start time contradicts", "candidate date contradicts", "target date mismatch", "event date mismatch")):
        return result("event_identity", "TARGET_EVENT_MISMATCH", "schedule_mismatch", "refresh_schedule_and_reselect", "event_mismatch")
    if any(marker in value for marker in ("non target event", "investor day", "analyst day", "capital markets day")):
        return result("event_identity", "NON_TARGET_EVENT", "candidate_unavailable", "ignore_and_reselect", "non_target_event")
    if any(marker in value for marker in ("not live yet", "not yet available", "has not started")):
        return result("lifecycle", "NOT_LIVE_YET", "candidate_unavailable", "wait_until_event_window", "not_live_yet")
    if any(marker in value for marker in ("live target unconfirmed", "target identity unconfirmed", "no dated target candidate", "media fallback blocked")):
        return result("discovery", "LIVE_TARGET_UNCONFIRMED", "candidate_unavailable", "retry_candidate_discovery", "no_candidate")
    if any(marker in value for marker in ("expired event", "no longer available", "recording not available")):
        return result("discovery", "EXPIRED_EVENT", "candidate_unavailable", "refresh_event_link", "expired_event")
    if any(marker in value for marker in ("candidate navigation failed", "stage=candidate navigation", "about:blank")):
        return result("discovery", "CANDIDATE_NAVIGATION_FAILED", "transient_error", "retry_direct_webcast_link", "candidate_navigation")
    if "playback ready timed out" in value:
        return result("playback", "PLAYBACK_READY_TIMED_OUT", "playback_failed", "inspect_player_and_retry", "player_activation")
    if any(marker in value for marker in ("playback was not detected", "control did not activate", "playback stalled")):
        return result("playback", "PLAYBACK_STALLED", "playback_failed", "try_alternate_control", "player_activation")
    if any(marker in value for marker in ("audio runtime unavailable", "pulseaudio server did not start", "module initialization failed", "connection failure terminated")):
        return result("audio_runtime", "AUDIO_RUNTIME_UNAVAILABLE", "audio_failed", "restart_audio_runtime", "pulse_audio_unavailable")
    if "audio not detected" in value or "audio was not detected" in value:
        return result("audio", "AUDIO_NOT_DETECTED", "audio_failed", "inspect_sink_and_media_route", "audio_not_detected")
    if any(marker in value for marker in ("stt input lost", "stt exit no pcm", "no chunk timeout", "pcm source lost")):
        return result("audio", "STT_INPUT_LOST", "live_capture_incomplete", "reconnect_audio_preserve_pcm", "stt_worker_failed")
    if any(marker in value for marker in ("stt exit no text", "stt backpressure", "stt exit backpressure", "stt model stalled", "stt inference stalled", "model load stalled", "inference stalled", "stt progress stalled")):
        return result("stt", "STT_PROGRESS_STALLED", "live_capture_incomplete", "restart_stt_preserve_pcm", "stt_worker_failed")
    if "live capture incomplete" in value:
        return result("capture", "LIVE_CAPTURE_INCOMPLETE", "live_capture_incomplete", "resume_capture_preserve_pcm", "stt_worker_failed")
    if any(marker in value for marker in ("resource not found", "404")):
        return result("discovery", "RESOURCE_NOT_FOUND", "candidate_unavailable", "refresh_event_link", "resource_not_found")
    if any(marker in value for marker in ("webcast button not found", "no playback control", "no candidate", "no playable", "no active media", "no audio", "webcast target did not become active", "entrypoint cooldown active")):
        return result("discovery", "NO_CANDIDATE", "candidate_unavailable", "learn_new_candidate", "no_candidate")
    if re.search(r"sttworker.*exited code=[1-9]|stt worker.*failed", value):
        return result("stt", "STT_WORKER_FAILED", "transient_error", "inspect_capture_worker", "stt_worker_failed")
    if any(marker in value for marker in ("timed out", "timeout")):
        return result("runtime", "RUNTIME_TIMEOUT", "transient_error", "backoff_and_retry", "timeout")
    return result("unknown", "UNCLASSIFIED_FAILURE", "transient_error", "manual_triage", "other")


def classify_stream_failure(error: Any) -> str:
    return classify_live_failure(error)["reason"]
