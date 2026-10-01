"""Compatible browser CLI and imports; implementation: streams.browser."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict

from .browser.agent import BrowserWebcastAgent
from .browser.rules import (
    ACCESS_BARRIER_PATTERN,
    ALREADY_REGISTERED_PATTERN,
    ARCHIVE_NAVIGATION_PATH_PATTERN,
    ARCHIVE_NAVIGATION_TERMS,
    AUDIO_PRIMING_PLAYER_HOST_SUFFIXES,
    AUTHENTICATION_FORM_TEXT_PATTERN,
    AUTHENTICATION_SURFACE_URL_PATTERN,
    COMMON_CHROMIUM_EXECUTABLES,
    COOKIE_CONSENT_TEXT_PATTERN,
    DATA_PIPELINE_ROOT,
    DIRECT_PLAYER_HOST_SUFFIXES,
    DISCLOSURE_AGREEMENT_PAGE_PATTERN,
    DYNAMIC_LOADING_PATTERN,
    EARNINGS_EVENT_CONTEXT_PATTERN,
    EVENT_DATE_PATTERN,
    EXISTING_WEBINAR_LOGIN_PATTERN,
    EXPIRED_EVENT_PATTERN,
    EXPIRED_MEDIA_PATH_PATTERN,
    HTTP_ACCESS_BARRIER_STATUSES,
    HUMAN_ACTION_CAPTURE_SCRIPT,
    HumanPageAssessment,
    InvestorProfile,
    KNOWN_ACCESS_FALLBACK_HOSTS,
    KNOWN_PROVIDER_ARCHIVE_PATHS,
    LEGAL_OVERLAY_TEXT_PATTERN,
    LearningSnapshot,
    MEDIA_URL_PATTERN,
    MISSING_RESOURCE_URL_PATTERN,
    MONTH_NUMBERS,
    NEWS_ARTICLE_PATH_PATTERN,
    NONESSENTIAL_POPUP_HOST_SUFFIXES,
    NON_EARNINGS_EVENT_PATTERN,
    NON_MEDIA_HOSTS,
    NON_PLAYBACK_CONTROL_PATTERN,
    NON_PLAYBACK_DOCUMENT_PATTERN,
    NON_PLAYBACK_HOME_LABEL_PATTERN,
    NON_PLAYBACK_MEDIA_PATH_PATTERN,
    NON_PLAYBACK_PRODUCT_LABEL_PATTERN,
    NON_PLAYBACK_PRODUCT_PATH_PATTERN,
    NON_PLAYBACK_SURFACE_HOSTS,
    NON_PLAYBACK_SURFACE_PATH_PATTERN,
    NON_PLAYBACK_URL_HOSTS,
    NON_PLAYBACK_URL_PATH_PATTERN,
    NOT_LIVE_EVENT_PATTERN,
    OPEN_EXCHANGE_REGISTRATION_URL_PATTERN,
    OpenAIVisionSelector,
    PLAY_TEXT_PATTERN,
    Q4_EVENT_GATE_PATTERN,
    Q4_GUEST_REGISTRATION_PATTERN,
    RECIPE_LIFECYCLES,
    REGISTRATION_BARRIER_PATTERN,
    REGISTRATION_CONSENT_NEGATIVE_PATTERN,
    REGISTRATION_CONSENT_POSITIVE_PATTERN,
    REGISTRATION_EMAIL_ERROR_PATTERN,
    REGISTRATION_FORM_CONTAINER_SELECTORS,
    REGISTRATION_FORM_TEXT_PATTERN,
    REGISTRATION_SENSITIVE_QUERY_KEYS,
    REPLAY_ARCHIVE_NAVIGATION_LABELS,
    REPLAY_ARCHIVE_PRESENTATIONS_PATH_PATTERN,
    REPLAY_ARCHIVE_VIEW_PATTERN,
    REPLAY_EXPANSION_LABEL_PATTERN,
    REPLAY_LOGIN_PATH_PATTERN,
    REPLAY_PROXY_DOCUMENT_PATTERN,
    REPLAY_PROXY_LINK_PATTERN,
    REPO_ROOT,
    RESOURCE_NOT_FOUND_PATTERN,
    SUBSCRIPTION_PAGE_PATTERN,
    SURVEY_TEXT_PATTERN,
    WEBCASTS_REGISTRATION_FIELD_SELECTORS,
    WEBCASTS_REGISTRATION_FORM_SELECTOR,
    WEBCASTS_REGISTRATION_SUBMIT_SELECTOR,
    WEBCAST_TEXT_PATTERN,
    WebcastCandidate,
    WebcastDiscoveryResult,
    WebcastRecipe,
    _load_env,
    access_fallback_urls,
    archive_navigation_url,
    artifact_paths,
    candidate_identity_mismatch,
    choose_heuristic_candidate,
    choose_replay_training_candidate,
    choose_replay_training_surface_candidate,
    default_chromium_executable,
    domain_for_url,
    event_date_from_text,
    live_candidate_identity_confirmation,
    live_event_identity_confirmation,
    future_event_date_reason,
    is_audio_priming_player_url,
    is_direct_player_url,
    is_event_specific_replay_recipe,
    is_existing_webinar_login_surface,
    is_media_candidate_url,
    is_news_article_without_playback_label,
    is_non_playback_home_url,
    is_non_playback_product_surface_url,
    is_non_playback_surface_url,
    is_non_replay_navigation_link,
    is_nonessential_popup_url,
    is_open_exchange_registration_url,
    is_playback_control_label,
    is_positive_registration_consent_text,
    is_q4_custom_registration_text,
    is_q4_followup_registration_text,
    is_q4_guest_registration_text,
    is_replay_proxy_link,
    is_replay_training_candidate,
    is_webcast_player_url,
    load_project_env,
    load_registration_approval_manifest,
    make_generalized_patterns,
    make_recipe,
    non_earnings_event_reason,
    provider_archive_navigation_url,
    redact_registration_url,
    registration_url_identity,
    replay_candidate_rejection_reason,
    replay_page_number,
    write_snapshot_metadata,
)


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
    parser.add_argument("--discovery-only", action="store_true",
                        help="Discover a confirmed URL without registration, playback or audio.")
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
        discovery_only=args.discovery_only,
    )
    result = await agent.run()
    if result.discovery_only:
        print("WEBCAST_DISCOVERY_RESULT=" + json.dumps(asdict(result), ensure_ascii=False))
        return 0 if result.success else 1
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
