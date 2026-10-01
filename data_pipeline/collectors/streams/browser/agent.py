"""Browser session state and end-to-end navigation."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from .rules import (
    DATA_PIPELINE_ROOT,
    InvestorProfile,
    LearningSnapshot,
    OpenAIVisionSelector,
    RECIPE_LIFECYCLES,
    WebcastCandidate,
    WebcastDiscoveryResult,
    WebcastRecipe,
    default_chromium_executable,
    is_direct_player_url,
    live_candidate_identity_confirmation,
    live_event_identity_confirmation,
    load_registration_approval_manifest,
)
from . import discovery, human, learning, playback, registration, session
from .stages import BrowserStages


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BrowserWebcastAgent:
    def __init__(
        self,
        ticker: str,
        ir_url: str,
        *,
        stages: BrowserStages | None = None,
        headless: bool = True,
        storage_state_path: str | None = None,
        save_storage_state_path: str | None = None,
        hold_seconds: float = 0,
        executable_path: str | None = None,
        profile: InvestorProfile | None = None,
        target_year: int | None = None,
        target_quarter: str | None = None,
        discovery_only: bool = False,
    ) -> None:
        self.stages = stages if stages is not None else BrowserStages()
        self.ticker = ticker.upper()
        self.ir_url = ir_url
        self.headless = headless
        self.storage_state_path = storage_state_path or os.getenv(
            "WEBCAST_STORAGE_STATE",
            str(DATA_PIPELINE_ROOT / ".state" / "q4_auth.json"),
        )
        self.save_storage_state_path = save_storage_state_path or os.getenv(
            "WEBCAST_SAVE_STORAGE_STATE",
            self.storage_state_path,
        )
        self.hold_seconds = hold_seconds
        self.discovery_only = discovery_only or os.getenv("WEBCAST_DISCOVERY_ONLY", "").lower() in {
            "1", "true", "yes", "on",
        }
        self._live_redirect_edges: set[tuple[str, str]] = set()
        self.live_target_proof: dict[str, Any] | None = None
        configured_year = os.getenv("WEBCAST_TARGET_YEAR", "").strip()
        self.target_year = target_year
        if self.target_year is None and configured_year.isdigit():
            self.target_year = int(configured_year)
        self.target_quarter = (
            target_quarter
            or os.getenv("WEBCAST_TARGET_QUARTER", "").strip()
            or None
        )
        target_time_text = os.getenv("WEBCAST_TARGET_TIME_UTC", "").strip()
        try:
            parsed_target_time = datetime.fromisoformat(
                target_time_text.replace("Z", "+00:00")
            )
            self.target_time_utc = (
                parsed_target_time.replace(tzinfo=timezone.utc)
                if parsed_target_time.tzinfo is None
                else parsed_target_time.astimezone(timezone.utc)
            )
        except ValueError:
            self.target_time_utc = None
        self.direct_target_url = os.getenv("WEBCAST_DIRECT_TARGET_URL", "").strip()
        capture_manifest_path = os.getenv("WEBCAST_CAPTURE_MANIFEST_FILE", "").strip()
        capture_manifest: dict[str, Any] = {}
        if capture_manifest_path:
            try:
                manifest_value = json.loads(
                    Path(capture_manifest_path).read_text(encoding="utf-8")
                )
                if isinstance(manifest_value, dict):
                    capture_manifest = manifest_value
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
        manifest_target = str(capture_manifest.get("final_target_url") or "").strip()
        if manifest_target and not self.direct_target_url:
            self.direct_target_url = manifest_target
        target_date_text = os.getenv("WEBCAST_TARGET_DATE", "").strip()
        try:
            self.target_date = date.fromisoformat(target_date_text) if target_date_text else None
        except ValueError:
            self.target_date = None
        configured_excluded_urls = [
            value.strip()
            for value in os.getenv("WEBCAST_LIVE_EXCLUDED_URLS", "").split(",")
            if value.strip()
        ]
        configured_excluded_urls.extend(
            str(value).strip()
            for value in capture_manifest.get("excluded_urls", [])
            if str(value).strip()
        )
        self.live_excluded_urls = tuple(dict.fromkeys(configured_excluded_urls))
        self.executable_path = executable_path or default_chromium_executable()
        self.profile = profile or InvestorProfile.from_env()
        requested_lifecycle = os.getenv("WEBCAST_LIFECYCLE", "unknown").strip().lower()
        self.lifecycle = requested_lifecycle if requested_lifecycle in RECIPE_LIFECYCLES else "unknown"
        self.require_live_target_confirmation = (
            os.getenv("WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION", "true").lower()
            in {"1", "true", "yes", "on"}
        )
        live_entrypoint_setting = os.getenv(
            "WEBCAST_LIVE_ENTRYPOINT_VERIFIED",
            "",
        ).strip()
        if live_entrypoint_setting:
            self.live_entrypoint_identity_verified = (
                live_entrypoint_setting.lower() in {"1", "true", "yes", "on"}
            )
        else:
            self.live_entrypoint_identity_verified = bool(
                capture_manifest.get("target_identity_verified") is True
            )
        self.live_target_identity_confirmed = self.live_entrypoint_identity_verified
        self.live_target_identity_evidence = (
            "pre-resolved official entrypoint"
            if self.live_target_identity_confirmed
            else None
        )
        from .navigation import is_event_navigation, make_target_proof, proof_is_fresh, same_event_route
        supplied_proof = os.getenv("WEBCAST_LIVE_IDENTITY_PROOF", "").strip()
        if supplied_proof:
            try:
                parsed_proof = json.loads(supplied_proof)
            except (ValueError, TypeError):
                parsed_proof = None
            if (
                proof_is_fresh(self, parsed_proof)
                and parsed_proof.get("verified") is True
                and same_event_route(parsed_proof.get("target_url", ""),
                                     self.direct_target_url or self.ir_url)
            ):
                self.live_target_proof = parsed_proof
                self.live_target_identity_confirmed = True
                self.live_entrypoint_identity_verified = True
            else:
                self.live_target_identity_confirmed = False
                self.live_entrypoint_identity_verified = False
        elif self.live_entrypoint_identity_verified:
            self.live_target_proof = make_target_proof(
                self, self.ir_url, self.direct_target_url or self.ir_url,
                "pre-resolved official entrypoint",
            )
        if self.lifecycle == "live" and is_event_navigation(self.direct_target_url or self.ir_url):
            # Old stored proofs may have promoted a calendar/list as an event.
            # Re-enter strict discovery instead of inheriting that authority.
            self.live_target_proof = None
            self.live_target_identity_confirmed = False
            self.live_entrypoint_identity_verified = False
            self.live_target_identity_evidence = None
        self._entrypoint_target_proof = self.live_target_proof
        manual_ready_file = os.getenv("WEBCAST_MANUAL_READY_FILE", "").strip()
        self.manual_ready_path = Path(manual_ready_file) if manual_ready_file else None
        self.manual_ready_timeout_seconds = float(
            os.getenv("WEBCAST_MANUAL_READY_TIMEOUT_SECONDS", "900")
        )
        self.page_ready_timeout_ms = max(
            1_000,
            int(float(os.getenv("WEBCAST_PAGE_READY_TIMEOUT_SECONDS", "20")) * 1_000),
        )
        self.direct_target_navigation_timeout_ms = max(
            self.page_ready_timeout_ms,
            int(
                float(
                    os.getenv(
                        "WEBCAST_DIRECT_TARGET_NAVIGATION_TIMEOUT_SECONDS",
                        "30",
                    )
                )
                * 1_000
            ),
        )
        self.playback_control_timeout_seconds = max(
            10.0,
            float(os.getenv("WEBCAST_CONTROL_TIMEOUT_SECONDS", "45")),
        )
        self.registration_timeout_seconds = max(
            10.0,
            float(os.getenv("WEBCAST_REGISTRATION_TIMEOUT_SECONDS", "120")),
        )
        self.post_registration_playback_wait_seconds = max(
            5.0,
            float(
                os.getenv(
                    "WEBCAST_POST_REGISTRATION_PLAYBACK_WAIT_SECONDS",
                    "30",
                )
            ),
        )
        # Normal webcast capture uses the configured attendee profile without
        # a per-ticker approval step. Explicit read-only modes always win,
        # including when the caller inherits an enabled privacy flag.
        self.registration_preview_only = _env_flag("WEBCAST_REGISTRATION_PREVIEW_ONLY")
        submission_read_only = self.discovery_only or self.registration_preview_only
        self.allow_registration_submission = (
            _env_flag("WEBCAST_ALLOW_REGISTRATION_SUBMISSION", True)
            and not submission_read_only
        )
        self.registration_approval_file = os.getenv(
            "WEBCAST_REGISTRATION_APPROVAL_FILE", ""
        ).strip()
        self.require_registration_approval = _env_flag("WEBCAST_REGISTRATION_REQUIRE_APPROVAL")
        self.registration_approval_manifest = load_registration_approval_manifest(
            self.registration_approval_file
        )
        # Privacy controls are part of the same registration action; a stale
        # privacy override must not bypass an explicit submission disable.
        self.allow_privacy_consent_submission = (
            self.allow_registration_submission
            and _env_flag("WEBCAST_ALLOW_PRIVACY_CONSENT_SUBMISSION", True)
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
        last_target_url_file = os.getenv(
            "WEBCAST_LAST_TARGET_URL_FILE",
            "",
        ).strip()
        self.last_target_url_path = (
            Path(last_target_url_file) if last_target_url_file else None
        )
        media_candidates_file = os.getenv(
            "WEBCAST_MEDIA_CANDIDATES_FILE",
            "",
        ).strip()
        self.media_candidates_path = (
            Path(media_candidates_file) if media_candidates_file else None
        )
        target_identity_ready_file = os.getenv(
            "WEBCAST_TARGET_IDENTITY_READY_FILE",
            "",
        ).strip()
        self.target_identity_ready_path = (
            Path(target_identity_ready_file) if target_identity_ready_file else None
        )
        if self.live_target_identity_confirmed:
            self._signal_live_target_identity_ready()
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
        self._training_proxy_event: str | None = None
        self._direct_audio_primed_urls: set[str] = set()
        self._followed_webcast_disclosures: set[str] = set()
        self._watched_page_ids: set[int] = set()
        self._replay_archive_year_page_ids: set[int] = set()
        self.human_loop_enabled = (
            os.getenv("WEBCAST_HUMAN_LOOP_ENABLED", "false").lower() == "true"
        )
        human_resume_file = os.getenv("WEBCAST_HUMAN_RESUME_FILE", "").strip()
        self.human_resume_path = Path(human_resume_file) if human_resume_file else None
        human_handoff_file = os.getenv("WEBCAST_HUMAN_HANDOFF_FILE", "").strip()
        self.human_handoff_path = Path(human_handoff_file) if human_handoff_file else None
        human_action_log_file = os.getenv("WEBCAST_HUMAN_ACTION_LOG_FILE", "").strip()
        self.human_action_log_path = (
            Path(human_action_log_file) if human_action_log_file else None
        )
        self.human_handoff_timeout_seconds = max(
            30.0,
            float(os.getenv("WEBCAST_HUMAN_HANDOFF_TIMEOUT_SECONDS", "900")),
        )
        self.human_retry_limit = max(
            1,
            int(os.getenv("WEBCAST_HUMAN_RETRY_LIMIT", "5")),
        )
        self._human_handoff_count = 0
        self._pending_human_recipe: WebcastRecipe | None = None
        self._human_capture_active = False
        self._human_action_buffer: list[dict[str, Any]] = []
        self._human_action_seen: set[str] = set()
        self._human_actions_by_handoff: dict[int, list[dict[str, Any]]] = {}
        self._pending_human_workflows: dict[str, dict[str, Any]] = {}
        self._last_human_action_page: Any | None = None
        self._last_human_action_at = 0.0
        self._human_return_page: Any | None = None

    async def run(self) -> WebcastDiscoveryResult:
        if self.discovery_only:
            from .navigation import run_discovery_only
            timeout = max(5.0, float(os.getenv("WEBCAST_DISCOVERY_TIMEOUT_SECONDS", "35")))
            try:
                return await asyncio.wait_for(run_discovery_only(self), timeout=timeout)
            except TimeoutError:
                return WebcastDiscoveryResult(
                    ticker=self.ticker, ir_url=self.ir_url, success=False,
                    clicked_text=None, final_url=None, playback_triggered=False,
                    media_candidates=[], discovery_only=True,
                    error="DISCOVERY_TIMEOUT bounded discovery budget exhausted",
                    retry_state="transient_network",
                )
        return await self.stages.flow.run(self)

    async def _validate_live_target_page(self, page: Any) -> bool:
        from .navigation import validate_target_page
        verified = await validate_target_page(self, page)
        if verified and self.lifecycle == 'live' and self.target_identity_ready_path:
            from data_pipeline.live_end import write_bound_target_proof
            try:
                write_bound_target_proof(self.target_identity_ready_path, self.live_target_proof,
                                         validated_url=str(page.url))
            except OSError:
                pass
        return verified

    async def _try_verified_player_fallback(
        self,
        source_page: Any,
        timeout_error: Any,
    ) -> Any | None:
        return await self.stages.session._try_verified_player_fallback(self, source_page, timeout_error)

    async def _try_verified_player_fallback_in_context(
        self,
        context: Any,
        source_url: str,
        timeout_error: Any,
    ) -> Any | None:
        return await self.stages.session._try_verified_player_fallback_in_context(self, context, source_url, timeout_error)

    def _context_options(self) -> dict[str, Any]:
        return self.stages.session._context_options(self)

    async def _open_ir_page(self, context: Any) -> Any:
        return await self.stages.session._open_ir_page(self, context)

    async def _open_direct_target_page(self, context: Any, target_url: str) -> Any:
        return await self.stages.session._open_direct_target_page(self, context, target_url)

    async def _wait_for_dynamic_page(self, page: Any) -> None:
        return await self.stages.session._wait_for_dynamic_page(self, page)

    async def _detect_access_barrier(self, page: Any) -> str | None:
        return await self.stages.session._detect_access_barrier(self, page)

    async def _detect_registration_barrier(self, page: Any) -> str | None:
        return await self.stages.session._detect_registration_barrier(self, page)

    async def _detect_expired_event(self, page: Any) -> str | None:
        return await self.stages.session._detect_expired_event(self, page)

    async def _detect_not_live_event(
        self, page: Any, *, selected_event_evidence: str | None = None,
    ) -> str | None:
        return await self.stages.session._detect_not_live_event(
            self, page, selected_event_evidence=selected_event_evidence,
        )

    async def _detect_non_earnings_event(
        self,
        page: Any,
        clicked_text: str = "",
    ) -> str | None:
        return await self.stages.session._detect_non_earnings_event(self, page, clicked_text)

    async def _accept_replay_training_proxy(
        self,
        page: Any,
        event_reason: str,
    ) -> bool:
        return await self.stages.session._accept_replay_training_proxy(self, page, event_reason)

    def _replay_training_proxy_mode(self) -> bool:
        return self.stages.session._replay_training_proxy_mode(self)

    def _mark_replay_training_proxy(self, page: Any, event_reason: str) -> None:
        return self.stages.session._mark_replay_training_proxy(self, page, event_reason)

    async def _detect_missing_resource(self, page: Any) -> str | None:
        return await self.stages.session._detect_missing_resource(self, page)

    async def _wait_for_missing_resource(self, page: Any) -> str | None:
        return await self.stages.session._wait_for_missing_resource(self, page)

    def _signal_playback_ready(self, active_url: str | None = None) -> None:
        return self.stages.session._signal_playback_ready(self, active_url)

    def _record_target_url(self, target_url: str | None) -> None:
        return self.stages.session._record_target_url(self, target_url)

    async def _save_storage_state(self, context: Any) -> None:
        return await self.stages.session._save_storage_state(self, context)

    def _attach_media_watchers(self, page: Any) -> None:
        self.stages.session._attach_media_watchers(self, page)
        from .source_observation import attach_source_observer
        attach_source_observer(self, page)

    async def accept_cookie_banners(self, page: Any) -> None:
        return await self.stages.session.accept_cookie_banners(self, page)

    async def _wait_for_clicked_target(
        self,
        context: Any,
        *,
        source_page: Any,
        source_url: str,
        pages_before_click: tuple[Any, ...],
    ) -> Any:
        return await self.stages.session._wait_for_clicked_target(self, context, source_page=source_page, source_url=source_url, pages_before_click=pages_before_click)

    async def _wait_for_manual_ready(self, page: Any) -> str | None:
        return await self.stages.human._wait_for_manual_ready(self, page)

    async def _install_human_action_capture(self, context: Any) -> None:
        return await self.stages.human._install_human_action_capture(self, context)

    def _receive_human_action(self, source: Any, value: Any) -> None:
        return self.stages.human._receive_human_action(self, source, value)

    @staticmethod
    def _human_action_fingerprint(action: dict[str, Any]) -> str:
        return human._human_action_fingerprint(action)

    def _persist_human_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.stages.human._persist_human_actions(self, actions)

    async def _drain_human_actions(self, page: Any) -> list[dict[str, Any]]:
        return await self.stages.human._drain_human_actions(self, page)

    async def _clear_human_action_queue(self, page: Any) -> None:
        return await self.stages.human._clear_human_action_queue(self, page)

    @staticmethod
    def _human_workflow_stage(stage: str) -> str:
        return human._human_workflow_stage(stage)

    @staticmethod
    def _is_human_playback_click(action: dict[str, Any]) -> bool:
        return human._is_human_playback_click(action)

    def _human_workflow_return_stage(
        self,
        requested_stage: str,
        assessment: HumanPageAssessment,
        actions: list[dict[str, Any]],
    ) -> str:
        return self.stages.human._human_workflow_return_stage(self, requested_stage, assessment, actions)

    def _human_workflow_steps(self, handoff: int) -> list[dict[str, Any]]:
        return self.stages.human._human_workflow_steps(self, handoff)

    async def _classify_human_page(self, page: Any) -> HumanPageAssessment:
        return await self.stages.human._classify_human_page(self, page)

    @staticmethod
    def _workflow_checkpoint_succeeded(
        stage: str,
        assessment: HumanPageAssessment,
        steps: list[dict[str, Any]],
    ) -> bool:
        return human._workflow_checkpoint_succeeded(stage, assessment, steps)

    async def _checkpoint_human_workflow(
        self,
        *,
        stage: str,
        source_url: str,
        page: Any,
    ) -> HumanPageAssessment:
        return await self.stages.human._checkpoint_human_workflow(self, stage=stage, source_url=source_url, page=page)

    def _promote_pending_human_workflows(
        self,
        assessment: HumanPageAssessment,
    ) -> None:
        return self.stages.human._promote_pending_human_workflows(self, assessment)

    def _save_human_workflow(self, pending: dict[str, Any]) -> int | None:
        return self.stages.human._save_human_workflow(self, pending)

    @staticmethod
    def _latest_context_page(page: Any) -> Any:
        return human._latest_context_page(page)

    @staticmethod
    def _usable_context_pages(page: Any) -> list[Any]:
        return human._usable_context_pages(page)

    def _human_return_target_page(
        self,
        page: Any,
        pages_before_handoff: set[int],
    ) -> Any:
        return self.stages.human._human_return_target_page(self, page, pages_before_handoff)

    def _page_after_human_handoff(self, fallback: Any) -> Any:
        return self.stages.human._page_after_human_handoff(self, fallback)

    def _write_human_handoff(self, payload: dict[str, Any]) -> None:
        return self.stages.human._write_human_handoff(self, payload)

    async def _human_handoff(self, page: Any, *, stage: str, reason: str) -> bool:
        return await self.stages.human._human_handoff(self, page, stage=stage, reason=reason)

    async def find_webcast_button(self, page: Any) -> Any | None:
        return await self.stages.discovery.find_webcast_button(self, page)

    def _is_live_excluded_url(self, value: str | None, base_url: str | None = None) -> bool:
        return self.stages.discovery._is_live_excluded_url(self, value, base_url)

    async def _is_live_excluded_locator(self, locator: Any, page_url: str) -> bool:
        return await self.stages.discovery._is_live_excluded_locator(self, locator, page_url)

    async def _find_embedded_playback_link(self, page: Any) -> Any | None:
        return await self.stages.discovery._find_embedded_playback_link(self, page)

    def _replay_minimum_age_days(self) -> int:
        # Replay training is deliberately allowed to use the newest archived
        # event. Live monitoring still keeps the conservative default so a
        # scheduled event is not mistaken for an available replay.
        return self.stages.discovery._replay_minimum_age_days(self)

    async def _replay_candidate_rejection(
        self,
        locator: Any,
        page_url: str,
    ) -> str | None:
        return await self.stages.discovery._replay_candidate_rejection(self, locator, page_url)

    async def _find_replay_event_detail_link(self, page: Any) -> Any | None:
        return await self.stages.discovery._find_replay_event_detail_link(self, page)

    async def find_webcast_button_with_archive_fallback(self, page: Any) -> tuple[Any | None, Any]:
        return await self.stages.discovery.find_webcast_button_with_archive_fallback(self, page)

    async def _expand_replay_event_rows(self, page: Any) -> bool:
        return await self.stages.discovery._expand_replay_event_rows(self, page)

    async def _page_has_earnings_context(self, page: Any) -> bool:
        return await self.stages.discovery._page_has_earnings_context(self, page)

    async def _page_has_replay_training_candidate(self, page: Any) -> bool:
        return await self.stages.discovery._page_has_replay_training_candidate(self, page)

    async def _try_replay_training_surface_links(
        self,
        page: Any,
        *,
        max_links: int = 6,
    ) -> tuple[Any | None, Any]:
        return await self.stages.discovery._try_replay_training_surface_links(self, page, max_links=max_links)

    async def _recover_replay_archive_page(self, page: Any) -> Any:
        return await self.stages.discovery._recover_replay_archive_page(self, page)

    async def _replay_pagination_controls(self, page: Any) -> list[dict[str, Any]]:
        return await self.stages.discovery._replay_pagination_controls(self, page)

    async def _replay_pagination_locators(self, page: Any) -> list[dict[str, Any]]:
        return await self.stages.discovery._replay_pagination_locators(self, page)

    async def _scan_replay_pagination(
        self,
        page: Any,
        *,
        max_pages: int = 8,
        force: bool = False,
    ) -> bool:
        return await self.stages.discovery._scan_replay_pagination(self, page, max_pages=max_pages, force=force)

    async def _prepare_replay_history(self, page: Any) -> None:
        return await self.stages.discovery._prepare_replay_history(self, page)

    async def _activate_replay_archive_view(self, page: Any) -> bool:
        return await self.stages.discovery._activate_replay_archive_view(self, page)

    async def _activate_replay_archive_year(self, page: Any) -> bool:
        return await self.stages.discovery._activate_replay_archive_year(self, page)

    async def _capture_learning_snapshot(self, page: Any) -> LearningSnapshot:
        return await self.stages.learning._capture_learning_snapshot(self, page)

    async def _capture_failure_snapshot(self, page: Any) -> None:
        return await self.stages.learning._capture_failure_snapshot(self, page)

    async def _collect_candidates(
        self,
        page: Any,
        *,
        include_hidden: bool = False,
    ) -> list[WebcastCandidate]:
        return await self.stages.learning._collect_candidates(self, page, include_hidden=include_hidden)

    async def _choose_learning_candidate(
        self,
        page: Any,
        snapshot: LearningSnapshot,
    ) -> tuple[WebcastCandidate | None, str, float, str | None]:
        return await self.stages.learning._choose_learning_candidate(self, page, snapshot)

    def _live_candidate_date_mismatch(
        self,
        candidate: WebcastCandidate,
    ) -> bool:
        return self.stages.learning._live_candidate_date_mismatch(self, candidate)

    def _live_candidate_identity_mismatch(
        self,
        candidate: WebcastCandidate,
    ) -> str | None:
        return self.stages.learning._live_candidate_identity_mismatch(self, candidate)

    def _live_target_confirmation_required(self) -> bool:
        return bool(
            self.lifecycle == "live"
            and self.require_live_target_confirmation
            and not self.live_target_identity_confirmed
        )

    def _live_candidate_identity_confirmation(
        self,
        candidate: WebcastCandidate,
    ) -> str | None:
        if self.lifecycle != "live":
            return None
        from .navigation import is_event_navigation
        if is_event_navigation(candidate.href or candidate.href_path or "",
                               candidate.text, candidate.aria_label, candidate.title):
            return None
        return live_candidate_identity_confirmation(
            candidate,
            target_ticker=self.ticker,
            target_date=self.target_date,
            target_time_utc=self.target_time_utc,
        )

    def _live_evidence_identity_confirmation(self, evidence: str) -> str | None:
        if self.lifecycle != "live":
            return None
        return live_event_identity_confirmation(
            evidence,
            target_date=self.target_date,
            target_time_utc=self.target_time_utc,
        )

    def _mark_live_target_identity_confirmed(
        self, evidence: str, *, source_url: str | None = None,
        target_url: str | None = None,
    ) -> None:
        if self.lifecycle != "live":
            return
        self.live_target_identity_confirmed = True
        self.live_target_identity_evidence = evidence[:500]
        if source_url and target_url:
            from .navigation import make_target_proof, proof_is_fresh, same_event_route
            previous = getattr(self, 'schedule_observation', None)
            previous_proof = previous.get('identity_proof') if isinstance(previous, dict) else None
            same_target = bool(proof_is_fresh(self, previous_proof) and
                same_event_route(str(previous_proof.get('target_url') or ''), target_url))
            if not same_target:
                self.schedule_observation = None
            previous_route = self.live_target_proof
            self.live_target_proof = make_target_proof(
                self, source_url, target_url, evidence,
            )
            # Keep source readings only while selection extends the same
            # event route. An abandoned candidate must not veto a new route's
            # clock merely by remaining in this browser's in-memory ledger.
            from ...schedules.browser_observation import observe_browser_time, proof_extends_route
            if (isinstance(previous_route, dict) and not proof_extends_route(
                    previous_route, self.live_target_proof, now=datetime.now(timezone.utc))):
                self.schedule_clock_observations = []
            observe_browser_time(self, evidence, evidence_url=source_url)
        self._signal_live_target_identity_ready()
        print(
            f"[{self.ticker}] live target identity confirmed: {evidence[:160]}",
            flush=True,
        )

    def _reset_live_target_identity_confirmation(self) -> None:
        self.schedule_observation = None
        self.schedule_clock_observations = []
        if self.lifecycle == 'live':
            from data_pipeline.live_telemetry import emit_live_event
            emit_live_event('schedule', 'browser_target_reset', status='unverified', observation=None)
        if self.lifecycle != "live":
            return
        self.live_target_identity_confirmed = self.live_entrypoint_identity_verified
        self.live_target_proof = self._entrypoint_target_proof
        self.live_target_identity_evidence = (
            "pre-resolved official entrypoint"
            if self.live_entrypoint_identity_verified
            else None
        )
        if self.live_entrypoint_identity_verified:
            self._signal_live_target_identity_ready()
        elif self.target_identity_ready_path:
            try:
                self.target_identity_ready_path.unlink(missing_ok=True)
                Path(str(self.target_identity_ready_path) + '.proof.json').unlink(missing_ok=True)
            except OSError:
                pass

    def _signal_live_target_identity_ready(self) -> None:
        if self.lifecycle != "live" or not self.target_identity_ready_path:
            return
        try:
            self.target_identity_ready_path.parent.mkdir(parents=True, exist_ok=True)
            self.target_identity_ready_path.write_text(
                self.live_target_identity_evidence or "verified",
                encoding="utf-8",
            )
            from data_pipeline.live_end import write_bound_target_proof
            write_bound_target_proof(self.target_identity_ready_path, self.live_target_proof)
        except OSError as exc:
            print(
                f"[{self.ticker}] live target identity signal failed: {exc}",
                flush=True,
            )

    async def _candidate_at_page_point(
        self,
        page: Any,
        x: float,
        y: float,
    ) -> WebcastCandidate | None:
        return await self.stages.learning._candidate_at_page_point(self, page, x, y)

    async def _find_recipe_button(self, page: Any, recipe: WebcastRecipe) -> Any | None:
        return await self.stages.learning._find_recipe_button(self, page, recipe)

    def _load_verified_human_workflows(
        self,
        page_url: str,
        *,
        stage: str,
    ) -> list[WebcastRecipe]:
        return self.stages.learning._load_verified_human_workflows(self, page_url, stage=stage)

    async def _find_human_workflow_step(
        self,
        page: Any,
        step: dict[str, Any],
    ) -> Any | None:
        return await self.stages.learning._find_human_workflow_step(self, page, step)

    async def _apply_human_workflow(
        self,
        page: Any,
        *,
        stage: str,
    ) -> tuple[Any, bool]:
        return await self.stages.learning._apply_human_workflow(self, page, stage=stage)

    def _load_verified_recipes(self, page_url: str) -> list[WebcastRecipe]:
        return self.stages.learning._load_verified_recipes(self, page_url)

    def _compatible_recipe_lifecycles(self) -> tuple[str, ...]:
        return self.stages.learning._compatible_recipe_lifecycles(self)

    def _save_recipe(self, recipe: WebcastRecipe) -> int | None:
        return self.stages.learning._save_recipe(self, recipe)

    def _recipe_context_path(self) -> Path:
        return self.stages.learning._recipe_context_path(self)

    def _clear_recipe_context(self) -> None:
        return self.stages.learning._clear_recipe_context(self)

    def _write_recipe_context(self) -> None:
        return self.stages.learning._write_recipe_context(self)

    def _recipe_id(self) -> int | None:
        return self.stages.learning._recipe_id(self)

    def _recipe_strategy(self) -> str | None:
        return self.stages.learning._recipe_strategy(self)

    def _artifact_path(self) -> str | None:
        return self.stages.learning._artifact_path(self)

    async def _is_navigation_element(self, element: Any) -> bool:
        return await self.stages.learning._is_navigation_element(self, element)

    def _registration_approval_error(
        self,
        page_url: str,
        prepared_fields: list[str],
        consent_selected: bool,
    ) -> str | None:
        return self.stages.registration._registration_approval_error(self, page_url, prepared_fields, consent_selected)

    async def fill_registration_form(self, page: Any, timeout_error_type: type[Exception]) -> bool:
        return await self.stages.registration.fill_registration_form(self, page, timeout_error_type)

    async def handle_registration_form(
        self,
        page: Any,
        timeout_error_type: type[Exception],
    ) -> bool:
        if self.lifecycle == "live" and not await self._validate_live_target_page(page):
            self._registration_failure_error = "LIVE_TARGET_UNCONFIRMED registration route changed"
            return False
        from .navigation import begin_registration_transition, finish_registration_transition
        transition = await begin_registration_transition(self, page)
        succeeded = False
        try:
            succeeded = await self.stages.registration.handle_registration_form(self, page, timeout_error_type)
            return succeeded
        finally:
            await finish_registration_transition(
                self, transition, self._registration_target_page or page, succeeded,
            )

    def _registration_error(self) -> str:
        return self.stages.registration._registration_error(self)

    async def _resolve_registration_barrier_with_human(
        self,
        page: Any,
    ) -> tuple[str | None, Any]:
        return await self.stages.registration._resolve_registration_barrier_with_human(self, page)

    async def _complete_registration_with_human(
        self,
        page: Any,
        timeout_error_type: type[Exception],
    ) -> tuple[bool, Any]:
        if self.lifecycle == "live" and not await self._validate_live_target_page(page):
            self._registration_failure_error = "LIVE_TARGET_UNCONFIRMED registration route changed"
            return False, page
        from .navigation import begin_registration_transition, finish_registration_transition
        transition = await begin_registration_transition(self, page)
        succeeded, target = False, page
        try:
            succeeded, target = await self.stages.registration._complete_registration_with_human(self, page, timeout_error_type)
            return succeeded, target
        finally:
            await finish_registration_transition(self, transition, target, succeeded)

    async def _submit_metameetings_privacy_consent(self, page: Any) -> bool:
        return await self.stages.registration._submit_metameetings_privacy_consent(self, page)

    @staticmethod
    def _registration_targets(page: Any) -> list[Any]:
        return registration._registration_targets(page)

    async def _has_registration_form_in_target(self, target: Any) -> bool:
        return await self.stages.registration._has_registration_form_in_target(self, target)

    async def _find_registration_target(self, page: Any) -> Any | None:
        return await self.stages.registration._find_registration_target(self, page)

    async def has_registration_form(
        self,
        page: Any,
        *,
        wait_seconds: float = 0.0,
    ) -> bool:
        return await self.stages.registration.has_registration_form(self, page, wait_seconds=wait_seconds)

    async def _find_registration_target_across_pages(
        self,
        page: Any,
        *,
        wait_seconds: float = 0.0,
    ) -> tuple[Any, Any] | None:
        return await self.stages.registration._find_registration_target_across_pages(self, page, wait_seconds=wait_seconds)

    async def _fill_generic_registration_form(
        self,
        page: Any,
        timeout_error_type: type[Exception],
        owner_page: Any | None = None,
        submission_depth: int = 0,
    ) -> bool:
        return await self.stages.registration._fill_generic_registration_form(self, page, timeout_error_type, owner_page, submission_depth)

    async def _activate_playback_with_human(
        self,
        context: Any,
        page: Any,
        *,
        timeout_error_type: type[Exception],
        reason: str,
    ) -> tuple[bool, Any]:
        return await self.stages.playback._activate_playback_with_human(self, context, page, timeout_error_type=timeout_error_type, reason=reason)

    async def _activate_registered_playback(
        self,
        context: Any,
        page: Any,
    ) -> tuple[bool, Any]:
        return await self.stages.playback._activate_registered_playback(self, context, page)

    async def detect_active_playback(
        self,
        page: Any,
        *,
        include_context_pages: bool = True,
    ) -> str | None:
        return await self.stages.playback.detect_active_playback(self, page, include_context_pages=include_context_pages)

    async def _has_visible_media_element(
        self,
        page: Any,
        *,
        include_context_pages: bool = True,
    ) -> bool:
        return await self.stages.playback._has_visible_media_element(self, page, include_context_pages=include_context_pages)

    async def _has_visible_player_entrypoint(
        self,
        page: Any,
        *,
        include_context_pages: bool = True,
    ) -> bool:
        return await self.stages.playback._has_visible_player_entrypoint(self, page, include_context_pages=include_context_pages)

    @staticmethod
    def _playback_pages(page: Any) -> list[Any]:
        return playback._playback_pages(page)

    async def _wait_for_active_playback(
        self,
        page: Any,
        *,
        attempts: int,
        include_context_pages: bool = True,
    ) -> str | None:
        return await self.stages.playback._wait_for_active_playback(self, page, attempts=attempts, include_context_pages=include_context_pages)

    async def _try_media_candidate_playback(self, context: Any) -> Any | None:
        return await self.stages.playback._try_media_candidate_playback(self, context)

    async def _prime_direct_player_audio(
        self,
        page: Any,
        *,
        include_context_pages: bool = True,
    ) -> None:
        return await self.stages.playback._prime_direct_player_audio(self, page, include_context_pages=include_context_pages)

    async def _prime_media_audio(
        self,
        page: Any,
        *,
        include_context_pages: bool = True,
    ) -> None:
        return await self.stages.playback._prime_media_audio(self, page, include_context_pages=include_context_pages)

    async def _click_playback_control(self, control: Any, label: str) -> bool:
        return await self.stages.playback._click_playback_control(self, control, label)

    async def _retry_shaka_playback_control(
        self,
        page: Any,
        *,
        include_context_pages: bool,
        timeout_seconds: float = 10.0,
    ) -> bool:
        return await self.stages.playback._retry_shaka_playback_control(self, page, include_context_pages=include_context_pages, timeout_seconds=timeout_seconds)

    async def trigger_media_playback(
        self,
        page: Any,
        *,
        allow_control_scan: bool = True,
        page_scope_only: bool = False,
        require_active_confirmation: bool = False,
    ) -> bool:
        if self.lifecycle == "live" and not await self._validate_live_target_page(page):
            return False
        return await self.stages.playback.trigger_media_playback(self, page, allow_control_scan=allow_control_scan, page_scope_only=page_scope_only, require_active_confirmation=require_active_confirmation)

    async def _trigger_media_playback(
        self,
        page: Any,
        *,
        allow_control_scan: bool,
        page_scope_only: bool,
        require_active_confirmation: bool,
    ) -> bool:
        return await self.stages.playback._trigger_media_playback(self, page, allow_control_scan=allow_control_scan, page_scope_only=page_scope_only, require_active_confirmation=require_active_confirmation)
