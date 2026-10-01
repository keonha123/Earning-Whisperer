"""End-to-end browser flow: coordinate the replaceable browser stages."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING
from data_pipeline.live_telemetry import emit_live_event
from urllib.parse import urljoin, urlparse
from .rules import WebcastDiscoveryResult, is_direct_player_url
from .diagnostics import capture_diagnostics
from .lifetime import hold_playback

if TYPE_CHECKING:
    from .agent import BrowserWebcastAgent


async def _selected_event_evidence(agent: BrowserWebcastAgent, element: Any) -> str:
    """Read the dated event row around a selected playback action."""
    try:
        evidence = await element.evaluate(
            r"""element => {
                const compact = value => (value || '').replace(/\s+/g, ' ').trim().slice(0, 1800);
                let fallback = '';
                let current = element;
                for (let depth = 0; current && depth < 9; depth += 1, current = current.parentElement) {
                    if (['BODY', 'MAIN'].includes(current.tagName)) break;
                    const text = compact(current.innerText || current.textContent || '');
                    if (!text || !/(?:earnings|conference call|webcast|results)/i.test(text)) continue;
                    if (!fallback) fallback = text;
                    const hasDate = /(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2})/i.test(text);
                    if (hasDate) return text;
                }
                return fallback;
            }"""
        )
        if str(evidence or "").strip():
            return str(evidence).strip()
    except Exception:
        pass

    recipe = getattr(agent, "_active_recipe", None)
    candidate = (getattr(recipe, "evidence", {}) or {}).get("candidate", {})
    if isinstance(candidate, dict):
        return " ".join(
            str(candidate.get(key) or "").strip()
            for key in ("text", "aria_label", "title", "context_text", "metadata_text")
            if str(candidate.get(key) or "").strip()
        )
    return ""


async def run(agent: BrowserWebcastAgent) -> WebcastDiscoveryResult:
    try:
        from playwright.async_api import (
            TimeoutError as PlaywrightTimeoutError,
            async_playwright,
        )
    except ImportError as exc:
        return WebcastDiscoveryResult(
            ticker=agent.ticker,
            ir_url=agent.ir_url,
            success=False,
            clicked_text=None,
            final_url=None,
            playback_triggered=False,
            media_candidates=[],
            error=f"playwright is not installed: {exc}",
        )

    emit_live_event("discovery", "browser_started", status="opening_page", ticker=agent.ticker,
                    url=agent.direct_target_url or agent.ir_url)
    agent._clear_recipe_context()
    if agent.human_loop_enabled and agent.human_resume_path:
        try:
            agent.human_resume_path.unlink(missing_ok=True)
        except OSError:
            pass
    async with async_playwright() as playwright:
        launch_options: dict[str, Any] = {
            "headless": agent.headless,
            # Playwright may add --mute-audio to Chromium's default args;
            # OS-level capture needs the browser's real audio output.
            "ignore_default_args": ["--mute-audio"],
            "args": [
                "--no-user-gesture-required",
                "--autoplay-policy=no-user-gesture-required",
                # A few IR hosts return malformed HTTP/2 responses to Chromium
                # while serving the same archive normally over HTTP/1.1.
                "--disable-http2",
            ],
        }
        if not agent.headless:
            # Docker Chromium is displayed through the host's XWayland server.
            # Keep the window on-screen and avoid GPU compositing, which can render
            # as a transparent surface on that path.
            browser_width = max(800, int(os.getenv("WEBCAST_BROWSER_WIDTH", "1280")))
            browser_height = max(700, int(os.getenv("WEBCAST_BROWSER_HEIGHT", "900")))
            launch_options["args"].extend(
                [
                    "--disable-gpu",
                    "--disable-gpu-compositing",
                    "--ozone-platform=x11",
                    "--window-position=80,60",
                    f"--window-size={browser_width},{browser_height}",
                ]
            )
        if agent.executable_path:
            launch_options["executable_path"] = agent.executable_path

        browser = await playwright.chromium.launch(**launch_options)
        context = None
        try:
            context_options = agent._context_options()
            context = await browser.new_context(**context_options)
            from .navigation import observe_redirect
            context.on("request", lambda request: observe_redirect(agent, request))
            if agent.human_loop_enabled:
                await agent._install_human_action_capture(context)
            context.on("page", agent._attach_media_watchers)
            verified_page = None
            if not agent.direct_target_url:
                verified_page = await agent._try_verified_player_fallback_in_context(
                    context,
                    agent.ir_url,
                    PlaywrightTimeoutError,
                )
            if verified_page:
                agent._signal_playback_ready(verified_page.url)
                await capture_diagnostics(agent, context, "playback_ready")
                await agent._save_storage_state(context)
                await hold_playback(agent, verified_page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=True,
                    clicked_text="verified player shortcut",
                    final_url=verified_page.url,
                    playback_triggered=True,
                    media_candidates=agent.media_candidates,
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                )

            if agent._not_live_reason:
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=None,
                    final_url=None,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=f"NOT_LIVE_YET {agent._not_live_reason}",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                )

            if agent.direct_target_url:
                page = await agent._open_direct_target_page(
                    context,
                    agent.direct_target_url,
                )
            else:
                page = await agent._open_ir_page(context)

            manual_error = await agent._wait_for_manual_ready(page)
            if manual_error:
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=None,
                    final_url=page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=manual_error,
                )

            if agent._page_barrier:
                agent._learning_snapshot = await agent._capture_learning_snapshot(page)
                fallback_page = await agent._try_verified_player_fallback(
                    page,
                    PlaywrightTimeoutError,
                )
                if fallback_page:
                    agent._signal_playback_ready(fallback_page.url)
                    await capture_diagnostics(agent, context, "playback_ready")
                    await agent._save_storage_state(context)
                    await hold_playback(agent, fallback_page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=True,
                        clicked_text="verified player fallback",
                        final_url=fallback_page.url,
                        playback_triggered=True,
                        media_candidates=agent.media_candidates,
                        recipe_id=agent._recipe_id(),
                        recipe_strategy=agent._recipe_strategy(),
                        learning_artifact_path=agent._artifact_path(),
                    )
                for _ in range(agent.human_retry_limit):
                    if not agent._page_barrier:
                        break
                    if not await agent._human_handoff(
                        page,
                        stage="access",
                        reason=f"IR 페이지 접근이 막혔습니다: {agent._page_barrier}",
                    ):
                        break
                    page = agent._page_after_human_handoff(page)
                    agent._page_barrier = await agent._detect_access_barrier(page)
                if not agent._page_barrier:
                    await agent._wait_for_dynamic_page(page)
                else:
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=f"page access blocked: {agent._page_barrier}",
                        learning_artifact_path=agent._artifact_path(),
                    )

            page, human_workflow_applied = await agent._apply_human_workflow(
                page,
                stage="event_selection",
            )
            if (
                agent.lifecycle == "replay"
                and not human_workflow_applied
                and not agent.direct_target_url
            ):
                await agent._prepare_replay_history(page)

            missing_resource = await agent._wait_for_missing_resource(page)
            if missing_resource:
                await agent._capture_failure_snapshot(page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=None,
                    final_url=page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=f"RESOURCE_NOT_FOUND {missing_resource}",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            # A replay probe must keep going even when the entry page only
            # describes a future event or says that no live webcast is open.
            # Historical pages are the training surface for the later
            # registration/player/audio stages.
            not_live_reason = (
                None
                if agent.lifecycle == "replay"
                else await agent._detect_not_live_event(page)
            )
            if not_live_reason:
                await agent._capture_failure_snapshot(page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=None,
                    final_url=page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=f"NOT_LIVE_YET {not_live_reason}",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            non_earnings_event = await agent._detect_non_earnings_event(page)
            if non_earnings_event and agent._replay_training_proxy_mode():
                agent._mark_replay_training_proxy(page, non_earnings_event)
                non_earnings_event = None
            elif non_earnings_event and await agent._accept_replay_training_proxy(
                page,
                non_earnings_event,
            ):
                non_earnings_event = None
            if non_earnings_event:
                if agent.lifecycle == "replay":
                    print(
                        f"[{agent.ticker}] current event is non-earnings; "
                        "forcing historical archive pagination",
                        flush=True,
                    )
                    await agent._scan_replay_pagination(page, force=True)
                    page = agent._latest_context_page(page)
                    non_earnings_event = await agent._detect_non_earnings_event(page)
                for _ in range(agent.human_retry_limit):
                    if not non_earnings_event:
                        break
                    if not await agent._human_handoff(
                        page,
                        stage="event_selection",
                        reason=f"현재 페이지는 어닝콜이 아닌 이벤트입니다: {non_earnings_event}",
                    ):
                        break
                    page = agent._page_after_human_handoff(page)
                    non_earnings_event = await agent._detect_non_earnings_event(page)
                    if non_earnings_event and await agent._accept_replay_training_proxy(
                        page,
                        non_earnings_event,
                    ):
                        non_earnings_event = None
                    elif non_earnings_event and agent.lifecycle == "replay":
                        page = await agent._recover_replay_archive_page(page)
                        non_earnings_event = await agent._detect_non_earnings_event(
                            page
                        )
                if non_earnings_event:
                    await agent._capture_failure_snapshot(page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=f"NON_TARGET_EVENT {non_earnings_event}",
                        recipe_id=agent._recipe_id(),
                        recipe_strategy=agent._recipe_strategy(),
                        learning_artifact_path=agent._artifact_path(),
                    )

            if is_direct_player_url(page.url):
                if agent.lifecycle == "live" and not await agent._validate_live_target_page(page):
                    await agent._capture_failure_snapshot(page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text="direct player",
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=(
                            "LIVE_TARGET_UNCONFIRMED direct player has no "
                            "target-date evidence"
                        ),
                        learning_artifact_path=agent._artifact_path(),
                    )
                page, workflow_applied = await agent._apply_human_workflow(
                    page,
                    stage="playback",
                )
                if workflow_applied:
                    print(
                        f"[{agent.ticker}] replayed verified human playback workflow",
                        flush=True,
                    )
                playback_triggered = await agent.trigger_media_playback(
                    page,
                    allow_control_scan=True,
                    page_scope_only=True,
                )
                for _ in range(agent.human_retry_limit):
                    if playback_triggered:
                        break
                    if not await agent._human_handoff(
                        page,
                        stage="playback",
                        reason="직접 플레이어의 재생 활성화를 확인하지 못했습니다.",
                    ):
                        break
                    page = agent._page_after_human_handoff(page)
                    playback_triggered = await agent.trigger_media_playback(
                        page,
                        allow_control_scan=True,
                        page_scope_only=True,
                    )
                if not playback_triggered:
                    await agent._capture_failure_snapshot(page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text="direct player",
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error="direct player did not become active",
                        learning_artifact_path=agent._artifact_path(),
                    )
                agent._signal_playback_ready(page.url)
                await capture_diagnostics(agent, context, "playback_ready")
                await agent._save_storage_state(context)
                await hold_playback(agent, page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=True,
                    clicked_text="direct player",
                    final_url=page.url,
                    playback_triggered=True,
                    media_candidates=agent.media_candidates,
                    learning_artifact_path=agent._artifact_path(),
                )

            # On a proven provider registration page there need not be a
            # Webcast link. Route directly to the existing form handler below;
            # do not rank Register controls as event-discovery candidates.
            registration_entry = (agent.lifecycle == 'live'
                and await agent._validate_live_target_page(page)
                and await agent.has_registration_form(page, wait_seconds=1.0))
            if registration_entry:
                found_el = None
                emit_live_event('discovery', 'registration_surface_selected',
                                status='registration_required', ticker=agent.ticker, url=str(page.url))
            else:
                found_el, page = await agent.find_webcast_button_with_archive_fallback(page)
            if not found_el:
                if agent.lifecycle == "live" and not await agent._validate_live_target_page(page):
                    await agent._capture_failure_snapshot(page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=(
                            "LIVE_TARGET_UNCONFIRMED no candidate carried the "
                            "scheduled date and earnings context"
                        ),
                        learning_artifact_path=agent._artifact_path(),
                    )
                playback_reason = await agent.detect_active_playback(page)
                if playback_reason:
                    print(
                        f"[{agent.ticker}] active playback detected: {playback_reason}",
                        flush=True,
                    )
                    agent._signal_playback_ready(page.url)
                    await capture_diagnostics(agent, context, "playback_ready")
                    await hold_playback(agent, page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=True,
                        clicked_text="active player",
                        final_url=page.url,
                        playback_triggered=True,
                        media_candidates=agent.media_candidates,
                        learning_artifact_path=agent._artifact_path(),
                    )
                if await agent._has_visible_media_element(page):
                    playback_triggered, page = await agent._activate_registered_playback(
                        context,
                        page,
                    )
                    if playback_triggered:
                        agent._signal_playback_ready(page.url)
                        await capture_diagnostics(agent, context, "playback_ready")
                        await hold_playback(agent, page)
                        return WebcastDiscoveryResult(
                            ticker=agent.ticker,
                            ir_url=agent.ir_url,
                            success=True,
                            clicked_text="media element",
                            final_url=page.url,
                            playback_triggered=True,
                            media_candidates=agent.media_candidates,
                            learning_artifact_path=agent._artifact_path(),
                        )
                media_page = await agent._try_media_candidate_playback(context)
                if media_page:
                    agent._signal_playback_ready(media_page.url)
                    await capture_diagnostics(agent, context, "playback_ready")
                    await agent._save_storage_state(context)
                    await hold_playback(agent, media_page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=True,
                        clicked_text="direct media candidate",
                        final_url=media_page.url,
                        playback_triggered=True,
                        media_candidates=agent.media_candidates,
                        recipe_id=agent._recipe_id(),
                        recipe_strategy=agent._recipe_strategy(),
                        learning_artifact_path=agent._artifact_path(),
                    )
                registration_barrier = await agent._detect_registration_barrier(page)
                if registration_barrier:
                    registration_barrier, page = (
                        await agent._resolve_registration_barrier_with_human(
                            page,
                        )
                    )
                    if registration_barrier:
                        await agent._capture_failure_snapshot(page)
                        return WebcastDiscoveryResult(
                            ticker=agent.ticker,
                            ir_url=agent.ir_url,
                            success=False,
                            clicked_text="registration form",
                            final_url=page.url,
                            playback_triggered=False,
                            media_candidates=agent.media_candidates,
                            error=f"REGISTRATION_BLOCKED {registration_barrier}",
                            learning_artifact_path=agent._artifact_path(),
                        )
                if await agent.has_registration_form(page):
                    clicked_text = "registration form"
                    print(f"[{agent.ticker}] registration form detected", flush=True)
                    form_success, page = await agent._complete_registration_with_human(
                        page,
                        PlaywrightTimeoutError,
                    )
                    if not form_success:
                        await agent._capture_failure_snapshot(page)
                        return WebcastDiscoveryResult(
                            ticker=agent.ticker,
                            ir_url=agent.ir_url,
                            success=False,
                            clicked_text=clicked_text,
                            final_url=page.url,
                            playback_triggered=False,
                            media_candidates=agent.media_candidates,
                            error=agent._registration_error(),
                            learning_artifact_path=agent._artifact_path(),
                        )
                    playback_triggered, page = await agent._activate_playback_with_human(
                        context,
                        page,
                        timeout_error_type=PlaywrightTimeoutError,
                        reason="등록폼 통과 후 플레이어가 활성화되지 않았습니다.",
                    )
                    if not playback_triggered:
                        access_barrier = await agent._detect_access_barrier(page)
                        not_live_reason = await agent._detect_not_live_event(page)
                        missing_resource = await agent._detect_missing_resource(page)
                        await agent._capture_failure_snapshot(page)
                        return WebcastDiscoveryResult(
                            ticker=agent.ticker,
                            ir_url=agent.ir_url,
                            success=False,
                            clicked_text=clicked_text,
                            final_url=page.url,
                            playback_triggered=False,
                            media_candidates=agent.media_candidates,
                            error=(
                                f"ACCESS_BLOCKED {access_barrier}"
                                if access_barrier
                                else f"NOT_LIVE_YET {not_live_reason}"
                                if not_live_reason
                                else f"RESOURCE_NOT_FOUND {missing_resource}"
                                if missing_resource
                                else "registration completed but playback was not detected"
                            ),
                            learning_artifact_path=agent._artifact_path(),
                        )
                    agent._signal_playback_ready(page.url)
                    await capture_diagnostics(agent, context, "playback_ready")
                    await agent._save_storage_state(context)
                    await hold_playback(agent, page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=True,
                        clicked_text=clicked_text,
                        final_url=page.url,
                        playback_triggered=playback_triggered,
                        media_candidates=agent.media_candidates,
                        learning_artifact_path=agent._artifact_path(),
                    )
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=None,
                    final_url=page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error="webcast button not found",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            # A newly learned selector must survive a clean context before it is trusted.
            if agent._recipe_origin == "learned" and agent._active_recipe:
                await context.close()
                context = await browser.new_context(**context_options)
                context.on("request", lambda request: observe_redirect(agent, request))
                if agent.human_loop_enabled:
                    await agent._install_human_action_capture(context)
                context.on("page", agent._attach_media_watchers)
                page = await agent._open_ir_page(context)
                # Re-prove event identity in the clean context. Otherwise a
                # successful first scan could let an unrelated cached recipe
                # pass merely because the in-memory flag remained true.
                agent._reset_live_target_identity_confirmation()
                found_el, page = await agent.find_webcast_button_with_archive_fallback(page)
                if not found_el:
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=None,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error="learned recipe did not replay in a fresh browser context",
                        recipe_id=agent._active_recipe.recipe_id,
                        recipe_strategy=agent._active_recipe.strategy,
                        learning_artifact_path=agent._artifact_path(),
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
            if agent.lifecycle == "live":
                event_evidence = await _selected_event_evidence(agent, found_el)
                wait_reason = await agent._detect_not_live_event(
                    page, selected_event_evidence=event_evidence,
                )
                if wait_reason:
                    print(
                        f"[{agent.ticker}] NOT_LIVE_YET {wait_reason}",
                        flush=True,
                    )
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=f"NOT_LIVE_YET {wait_reason}",
                        recipe_id=agent._recipe_id(),
                        recipe_strategy=agent._recipe_strategy(),
                        learning_artifact_path=agent._artifact_path(),
                    )
            try:
                await found_el.scroll_into_view_if_needed(timeout=5000)
            except Exception as exc:
                # Some provider pages keep icon-only links in a virtualized
                # or cross-frame layout. The href is still usable even when
                # Playwright cannot scroll the locator into view.
                print(
                    f"[{agent.ticker}] candidate scroll skipped; "
                    f"continuing with click/href fallback: {str(exc)[:120]}",
                    flush=True,
                )
            agent._write_recipe_context()
            emit_live_event("discovery", "candidate_click", status="opening_target", ticker=agent.ticker,
                            source_url=str(page.url), destination=urljoin(clicked_base_url, clicked_href or ""))
            print(f"[{agent.ticker}] clicking webcast candidate: {clicked_text[:120]}", flush=True)

            target_page = page
            source_url = page.url
            pages_before_click = tuple(context.pages)
            click_failed = False
            try:
                await found_el.click(force=True, timeout=8000)
            except Exception as exc:
                click_failed = True
                emit_live_event("discovery", "candidate_click_failed", status="navigation_retry",
                                ticker=agent.ticker, error_type=type(exc).__name__,
                                next_action="open_same_selected_href")
                print(
                    f"[{agent.ticker}] candidate click failed; "
                    f"trying href fallback: {str(exc)[:160]}",
                    flush=True,
                )
            if not click_failed:
                target_page = await agent._wait_for_clicked_target(
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
                        f"[{agent.ticker}] click produced no navigation; "
                        f"opening candidate href directly: {fallback_url}",
                        flush=True,
                    )
                    if target_is_blank_popup:
                        try:
                            await target_page.close()
                        except Exception:
                            pass
                    # Use the same commit-time loader as stored replay
                    # candidates. Waiting for the full DOM event here can
                    # discard a usable provider page when its analytics or
                    # player iframe keeps the load event open.
                    target_page = await agent._open_direct_target_page(
                        context,
                        fallback_url,
                    )

            emit_live_event("discovery", "target_opened", status="validating_target", progress=True,
                            ticker=agent.ticker, url=str(target_page.url))
            print(
                f"[{agent.ticker}] webcast target opened: {target_page.url}",
                flush=True,
            )
            if str(target_page.url) in {"", "about:blank"}:
                await agent._capture_failure_snapshot(page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=clicked_text,
                    final_url=target_page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=(
                        "CANDIDATE_NAVIGATION_FAILED selected webcast target "
                        "did not commit a document"
                    ),
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )
            # Preserve the concrete event/provider page even when the
            # first playback attempt fails. A later replay retry can then
            # start from this page instead of rediscovering it from IR.
            if str(target_page.url) != source_url:
                agent._record_target_url(str(target_page.url))
            try:
                await target_page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=15000,
                )
            except PlaywrightTimeoutError:
                print(
                    f"[{agent.ticker}] target load timed out; inspecting rendered DOM",
                    flush=True,
                )
            await agent._wait_for_dynamic_page(target_page)
            await agent.accept_cookie_banners(target_page)
            if agent.lifecycle == "live" and not await agent._validate_live_target_page(target_page):
                artifact = await capture_diagnostics(agent, context, "destination_mismatch")
                emit_live_event("discovery", "destination_mismatch", status="identity_unconfirmed",
                                ticker=agent.ticker, url=str(target_page.url), artifact_path=artifact)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker, ir_url=agent.ir_url, success=False,
                    clicked_text=clicked_text, final_url=target_page.url,
                    playback_triggered=False, media_candidates=[],
                    error="LIVE_TARGET_UNCONFIRMED destination does not match selected event",
                )
            agent._page_barrier = await agent._detect_access_barrier(target_page)
            if agent._page_barrier:
                await agent._capture_failure_snapshot(target_page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=clicked_text,
                    final_url=target_page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=f"ACCESS_BLOCKED {agent._page_barrier}",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            non_earnings_event = await agent._detect_non_earnings_event(
                target_page,
                clicked_text,
            )
            if non_earnings_event and agent._replay_training_proxy_mode():
                agent._mark_replay_training_proxy(target_page, non_earnings_event)
                non_earnings_event = None
            elif non_earnings_event and await agent._accept_replay_training_proxy(
                target_page,
                non_earnings_event,
            ):
                non_earnings_event = None
            if non_earnings_event:
                if agent.lifecycle == "replay":
                    await agent._scan_replay_pagination(target_page, force=True)
                    target_page = agent._latest_context_page(target_page)
                    non_earnings_event = await agent._detect_non_earnings_event(
                        target_page,
                    )
                for _ in range(agent.human_retry_limit):
                    if not non_earnings_event:
                        break
                    if not await agent._human_handoff(
                        target_page,
                        stage="event_selection",
                        reason=f"현재 페이지는 어닝콜이 아닌 이벤트입니다: {non_earnings_event}",
                    ):
                        break
                    target_page = agent._page_after_human_handoff(target_page)
                    non_earnings_event = await agent._detect_non_earnings_event(
                        target_page,
                    )
                    if non_earnings_event and await agent._accept_replay_training_proxy(
                        target_page,
                        non_earnings_event,
                    ):
                        non_earnings_event = None
                    elif non_earnings_event and agent.lifecycle == "replay":
                        target_page = await agent._recover_replay_archive_page(
                            target_page
                        )
                        non_earnings_event = await agent._detect_non_earnings_event(
                            target_page
                        )
                if non_earnings_event:
                    await agent._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=f"NON_TARGET_EVENT {non_earnings_event}",
                        recipe_id=agent._recipe_id(),
                        recipe_strategy=agent._recipe_strategy(),
                        learning_artifact_path=agent._artifact_path(),
                    )

            # Inspect explicit provider links first. Some event-detail
            # templates expose a lightweight media shell or an unrelated
            # media element before the actual Webcast anchor is followed;
            # treating that shell as a complete player strands the probe
            # on the detail page.
            embedded_link = await agent._find_embedded_playback_link(target_page)
            if not embedded_link and await agent._has_visible_player_entrypoint(
                target_page,
                include_context_pages=False,
            ):
                print(
                    f"[{agent.ticker}] keeping current page because a player entrypoint is visible",
                    flush=True,
                )
            if embedded_link:
                embedded_href = (await embedded_link.get_attribute("href") or "").strip()
                embedded_url = urljoin(target_page.url, embedded_href)
                print(
                    f"[{agent.ticker}] opening embedded webcast link from event detail: {embedded_url}",
                    flush=True,
                )
                try:
                    embedded_page = await context.new_page()
                    agent._attach_media_watchers(embedded_page)
                    await embedded_page.goto(
                        embedded_url,
                        wait_until="domcontentloaded",
                        timeout=agent.page_ready_timeout_ms,
                    )
                    target_page = embedded_page
                    try:
                        await target_page.wait_for_load_state(
                            "domcontentloaded",
                            timeout=15000,
                        )
                    except PlaywrightTimeoutError:
                        print(
                            f"[{agent.ticker}] embedded player load timed out; inspecting rendered DOM",
                            flush=True,
                        )
                    await agent._wait_for_dynamic_page(target_page)
                    await agent.accept_cookie_banners(target_page)
                    # A hidden inline disclosure can open the declared
                    # webcast URL in a fresh tab. Continue playback
                    # detection on that new tab, not on the hash template.
                    target_page = agent._latest_context_page(target_page)
                    print(
                        f"[{agent.ticker}] embedded webcast target opened: {target_page.url}",
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        f"[{agent.ticker}] embedded webcast link click skipped: {str(exc)[:120]}",
                        flush=True,
                    )

            expired_reason = await agent._detect_expired_event(target_page)
            if expired_reason:
                await agent._capture_failure_snapshot(target_page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=clicked_text,
                    final_url=target_page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=f"EXPIRED_EVENT {expired_reason}",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            not_live_reason = (
                None
                if agent.lifecycle == "replay"
                else await agent._detect_not_live_event(target_page)
            )
            if not_live_reason:
                await agent._capture_failure_snapshot(target_page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=clicked_text,
                    final_url=target_page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=f"NOT_LIVE_YET {not_live_reason}",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            missing_resource = await agent._detect_missing_resource(target_page)
            if missing_resource:
                await agent._capture_failure_snapshot(target_page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=clicked_text,
                    final_url=target_page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=f"RESOURCE_NOT_FOUND {missing_resource}",
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            media_page = await agent._try_media_candidate_playback(context)
            if media_page:
                agent._signal_playback_ready(media_page.url)
                await capture_diagnostics(agent, context, "playback_ready")
                await agent._save_storage_state(context)
                await hold_playback(agent, media_page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=True,
                    clicked_text=clicked_text or "direct media candidate",
                    final_url=media_page.url,
                    playback_triggered=True,
                    media_candidates=agent.media_candidates,
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )

            registration_barrier = await agent._detect_registration_barrier(target_page)
            if registration_barrier:
                registration_barrier, target_page = (
                    await agent._resolve_registration_barrier_with_human(
                        target_page,
                    )
                )
                if registration_barrier:
                    await agent._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=f"REGISTRATION_BLOCKED {registration_barrier}",
                        recipe_id=agent._recipe_id(),
                        recipe_strategy=agent._recipe_strategy(),
                        learning_artifact_path=agent._artifact_path(),
                    )

            if await agent.has_registration_form(target_page, wait_seconds=5.0):
                form_success, target_page = await agent._complete_registration_with_human(
                    target_page,
                    PlaywrightTimeoutError,
                )
                if not form_success:
                    await agent._capture_failure_snapshot(target_page)
                    return WebcastDiscoveryResult(
                        ticker=agent.ticker,
                        ir_url=agent.ir_url,
                        success=False,
                        clicked_text=clicked_text,
                        final_url=target_page.url,
                        playback_triggered=False,
                        media_candidates=agent.media_candidates,
                        error=agent._registration_error(),
                        recipe_id=agent._recipe_id(),
                        recipe_strategy=agent._recipe_strategy(),
                        learning_artifact_path=agent._artifact_path(),
                    )
            else:
                print(
                    f"[{agent.ticker}] no registration form; continuing to playback",
                    flush=True,
                )

            playback_triggered, target_page = await agent._activate_playback_with_human(
                context,
                target_page,
                timeout_error_type=PlaywrightTimeoutError,
                reason="어닝콜 페이지는 열렸지만 플레이어가 활성화되지 않았습니다.",
            )
            if not playback_triggered:
                access_barrier = await agent._detect_access_barrier(target_page)
                not_live_reason = await agent._detect_not_live_event(target_page)
                missing_resource = await agent._detect_missing_resource(target_page)
                await agent._capture_failure_snapshot(target_page)
                return WebcastDiscoveryResult(
                    ticker=agent.ticker,
                    ir_url=agent.ir_url,
                    success=False,
                    clicked_text=clicked_text,
                    final_url=target_page.url,
                    playback_triggered=False,
                    media_candidates=agent.media_candidates,
                    error=(
                        f"ACCESS_BLOCKED {access_barrier}"
                        if access_barrier
                        else
                        f"NOT_LIVE_YET {not_live_reason}"
                        if not_live_reason
                        else f"RESOURCE_NOT_FOUND {missing_resource}"
                        if missing_resource
                        else "webcast opened but playback was not detected"
                    ),
                    recipe_id=agent._recipe_id(),
                    recipe_strategy=agent._recipe_strategy(),
                    learning_artifact_path=agent._artifact_path(),
                )
            agent._signal_playback_ready(target_page.url)
            await capture_diagnostics(agent, context, "playback_ready")
            await agent._save_storage_state(context)

            await hold_playback(agent, target_page)

            return WebcastDiscoveryResult(
                ticker=agent.ticker,
                ir_url=agent.ir_url,
                success=True,
                clicked_text=clicked_text,
                final_url=target_page.url,
                playback_triggered=playback_triggered,
                media_candidates=agent.media_candidates,
                recipe_id=agent._recipe_id(),
                recipe_strategy=agent._recipe_strategy(),
                learning_artifact_path=agent._artifact_path(),
            )
        except Exception as exc:
            artifact = await capture_diagnostics(agent, context, "browser_exception")
            emit_live_event("discovery", "browser_exception", status="failed", ticker=agent.ticker,
                            error=str(exc), artifact_path=artifact)
            return WebcastDiscoveryResult(
                ticker=agent.ticker,
                ir_url=agent.ir_url,
                success=False,
                clicked_text=None,
                final_url=None,
                playback_triggered=False,
                media_candidates=agent.media_candidates,
                error=str(exc),
                recipe_id=agent._recipe_id(),
                recipe_strategy=agent._recipe_strategy(),
                learning_artifact_path=agent._artifact_path(),
            )
        finally:
            await browser.close()
