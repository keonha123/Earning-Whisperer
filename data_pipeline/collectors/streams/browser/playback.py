"""Player activation and direct media audio fallbacks."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any
from data_pipeline.live_telemetry import emit_live_event
from urllib.parse import urlparse
from .rules import (
    EXPIRED_MEDIA_PATH_PATTERN,
    NON_PLAYBACK_MEDIA_PATH_PATTERN,
    domain_for_url,
    is_audio_priming_player_url,
    is_direct_player_url,
    is_playback_control_label,
)


async def _activate_playback_with_human(
    agent,
    context: Any,
    page: Any,
    *,
    timeout_error_type: type[Exception],
    reason: str,
) -> tuple[bool, Any]:
    """Activate playback and keep the human loop recoverable."""
    current_page = page
    playback_triggered, current_page = await agent._activate_registered_playback(
        context,
        current_page,
    )
    if not playback_triggered and getattr(agent, "_not_live_reason", None):
        return False, current_page
    # Some providers redirect from their event root to a registration
    # route only after the initial player scan. Give that late form one
    # automatic chance before handing control to a human or failing.
    if not playback_triggered:
        late_registration_page = agent._registration_target_page or current_page
        if await agent.has_registration_form(late_registration_page, wait_seconds=2.0):
            form_success, current_page = await agent._complete_registration_with_human(
                late_registration_page,
                timeout_error_type,
            )
            if form_success:
                playback_triggered, current_page = await agent._activate_registered_playback(
                    context,
                    current_page,
                )
                if playback_triggered:
                    return True, current_page
    for _ in range(agent.human_retry_limit):
        if playback_triggered:
            return True, current_page
        if not await agent._human_handoff(
            current_page,
            stage="playback",
            reason=reason,
        ):
            break
        current_page = agent._page_after_human_handoff(current_page)
        playback_triggered, current_page = await agent._activate_registered_playback(
            context,
            current_page,
        )
    return playback_triggered, current_page


async def _activate_registered_playback(
    agent,
    context: Any,
    page: Any,
) -> tuple[bool, Any]:
    """Re-scan the player after a registration redirect or delayed render.

    Registration providers commonly accept the form before opening the
    player tab, or render the player inside a new iframe a few seconds
    later.  A single immediate control scan turns those valid flows into
    false failures, so each observed page is retried while its player is
    still being mounted.
    """
    emit_live_event("playback", "activation_started", status="waiting_for_player",
                    ticker=agent.ticker, url=str(page.url))
    wait_seconds = agent.post_registration_playback_wait_seconds
    agent._not_live_reason = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    retry_interval_seconds = max(
        1.0,
        float(os.getenv("WEBCAST_PLAYBACK_RETRY_INTERVAL_SECONDS", "5")),
    )
    attempted_pages: dict[int, float] = {}
    media_fallback_attempted = False
    print(
        f"[{agent.ticker}] waiting up to {wait_seconds:g}s for registered player",
        flush=True,
    )

    while True:
        current_page = agent._registration_target_page or page
        try:
            known_pages = list(context.pages)
        except Exception:
            known_pages = []
        open_pages: list[Any] = []
        for candidate in known_pages:
            try:
                if candidate.is_closed():
                    continue
            except Exception:
                pass
            open_pages.append(candidate)

        # Prefer the newest/registration target page, but keep every open
        # page in the scan. Some providers open the player before the
        # registration dispatcher starts, while others render it in-place
        # without creating a new tab. Filtering by an "opened after start"
        # snapshot can therefore hide the only playable page.
        context_pages: list[Any] = []
        for candidate in [current_page, *reversed(open_pages)]:
            if candidate is None or any(candidate is seen for seen in context_pages):
                continue
            context_pages.append(candidate)

        # New tabs are appended by Playwright. Inspect the newest page
        # first, while retaining the source page for iframe-based players.
        for candidate_page in context_pages:
            try:
                if candidate_page.is_closed():
                    continue
            except Exception:
                pass
            try:
                await agent._wait_for_dynamic_page(candidate_page)
                await agent.accept_cookie_banners(candidate_page)
            except Exception:
                pass
            if await agent._submit_metameetings_privacy_consent(candidate_page):
                await agent._wait_for_dynamic_page(candidate_page)
            access_barrier = await agent._detect_access_barrier(candidate_page)
            if access_barrier:
                agent._page_barrier = access_barrier
                print(
                    f"[{agent.ticker}] registered player page is access blocked: "
                    f"{access_barrier}",
                    flush=True,
                )
                return False, candidate_page
            if getattr(agent, "lifecycle", None) == "live":
                wait_reason = await agent._detect_not_live_event(candidate_page)
                if wait_reason:
                    agent._not_live_reason = wait_reason
                    emit_live_event("playback", "waiting_room", status="waiting_for_start",
                                    ticker=agent.ticker, url=str(candidate_page.url), reason=wait_reason)
                    print(f"[{agent.ticker}] NOT_LIVE_YET {wait_reason}", flush=True)
                    # Preserve the accepted registration for the next watch.
                    await agent._save_storage_state(context)
                    from .diagnostics import capture_diagnostics
                    await capture_diagnostics(agent, context, "waiting_for_start")
                    return False, candidate_page
            candidate_page, workflow_applied = await agent._apply_human_workflow(
                candidate_page,
                stage="playback",
            )
            if workflow_applied:
                print(
                    f"[{agent.ticker}] replayed verified human playback workflow",
                    flush=True,
                )
            active_reason = await agent.detect_active_playback(
                candidate_page,
                include_context_pages=False,
            )
            if active_reason:
                print(
                    f"[{agent.ticker}] registered playback already active: "
                    f"{active_reason}",
                    flush=True,
                )
                return True, candidate_page

            page_id = id(candidate_page)
            now = loop.time()
            last_attempt = attempted_pages.get(page_id)
            if last_attempt is not None and now - last_attempt < retry_interval_seconds:
                continue
            attempted_pages[page_id] = now
            if last_attempt is not None:
                print(
                    f"[{agent.ticker}] retrying playback activation after late player render",
                    flush=True,
                )
            if await agent.trigger_media_playback(
                candidate_page,
                page_scope_only=True,
                require_active_confirmation=True,
            ):
                return True, candidate_page

        if not media_fallback_attempted:
            media_fallback_attempted = True
            media_page = await agent._try_media_candidate_playback(context)
            if media_page:
                return True, media_page

        if asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(1)

    print(
        f"[{agent.ticker}] registered player did not become active within "
        f"{wait_seconds:g}s",
        flush=True,
    )
    from .diagnostics import capture_diagnostics
    artifact = await capture_diagnostics(agent, context, "playback_activation_failed")
    emit_live_event("playback", "activation_timeout", status="player_not_active",
                    ticker=agent.ticker, timeout_seconds=wait_seconds, artifact_path=artifact)
    return False, agent._registration_target_page or page


async def detect_active_playback(
    agent,
    page: Any,
    *,
    include_context_pages: bool = True,
) -> str | None:
    """Observe clock progress separately from a control-only playback hint.

    Keep control hints compatible with providers hiding their media elements;
    the supervisor's OS audio probe remains the final audibility check. A
    single non-zero currentTime is never recorded as clock progress.
    """
    script = """async ({ lifecycle, replaySeekSeconds }) => {
        let stationary = null;
        let controlHint = null;
        const inspectRoot = async root => {
            const media = Array.from(root.querySelectorAll('video, audio'));
            const samples = [];
            for (const element of media) {
                const currentTime = Number(element.currentTime || 0);
                const readyState = Number(element.readyState || 0);
                if (
                    !element.paused && !element.ended &&
                    (readyState >= 2 || currentTime > 0.25)
                ) {
                    element.muted = false;
                    element.volume = 1;
                    samples.push({element, currentTime});
                }
            }
            if (samples.length) {
                // One shared interval per root, not a delay for every media
                // element. Do not seek between these two observations.
                await new Promise(resolve => setTimeout(resolve, 200));
                for (const {element, currentTime} of samples) {
                    const after = Number(element.currentTime || 0);
                    const observation = {
                        stage: 'clock_stalled', before: currentTime, after,
                        paused: Boolean(element.paused), ended: Boolean(element.ended),
                        muted: Boolean(element.muted), volume: Number(element.volume),
                        ready_state: Number(element.readyState),
                    };
                    if (!element.isConnected || element.paused || element.ended
                        || element.seeking || after - currentTime <= 0.02) {
                        stationary = observation;
                        continue;
                    }
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
                    observation.stage = 'clock_progressing';
                    observation.reason = element.tagName.toLowerCase() +
                        ' element is playing unmuted volume=' + element.volume +
                        ' time=' + Math.round(after) +
                        (seeked ? ' seeked' : '');
                    return observation;
                }
            }
            const controls = Array.from(root.querySelectorAll(
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
                    controlHint = {stage: 'control_seen', reason: 'visible pause control'};
                }
            }
            return null;
        };

        const directReason = await inspectRoot(document);
        if (directReason) return directReason;

        // Several custom-element players keep the media and controls in an
        // open shadow root, which document.querySelectorAll cannot see.
        // Only walk shadow roots after the inexpensive document scan fails.
        const pending = [];
        for (const node of document.querySelectorAll('*')) {
            if (node.shadowRoot) pending.push(node.shadowRoot);
        }
        while (pending.length) {
            const root = pending.shift();
            const reason = await inspectRoot(root);
            if (reason) return reason;
            for (const node of root.querySelectorAll('*')) {
                if (node.shadowRoot) pending.push(node.shadowRoot);
            }
        }
        return controlHint || stationary;
    }"""
    observations: list[dict[str, Any]] = []
    agent._playback_observations = observations
    control_hint: str | None = None
    pages = agent._playback_pages(page) if include_context_pages else [page]
    for candidate_page in pages:
        for frame in candidate_page.frames:
            try:
                observation = await asyncio.wait_for(
                    frame.evaluate(
                        script,
                        {
                            "lifecycle": agent.lifecycle,
                            "replaySeekSeconds": agent.replay_seek_seconds,
                        },
                    ),
                    timeout=3,
                )
            except Exception:
                continue
            if isinstance(observation, dict):
                observations.append(observation)
                stage = observation.get("stage")
                emit_live_event("playback", "activation_observation", status=stage,
                                progress=stage == "clock_progressing", ticker=getattr(agent, "ticker", ""),
                                url=str(getattr(candidate_page, "url", "")), observation=observation)
                if stage == "clock_progressing":
                    return str(observation["reason"])
                if stage == "control_seen":
                    control_hint = str(observation["reason"])
            elif observation:
                # Compatibility for replaceable browser stages/test doubles.
                return str(observation)
    return control_hint


async def _has_visible_media_element(
    agent,
    page: Any,
    *,
    include_context_pages: bool = True,
) -> bool:
    pages = agent._playback_pages(page) if include_context_pages else [page]
    for candidate_page in pages:
        for frame in candidate_page.frames:
            try:
                media = frame.locator("video, audio")
                for index in range(await media.count()):
                    if await media.nth(index).is_visible():
                        return True
            except Exception:
                continue
    return False


async def _has_visible_player_entrypoint(
    agent,
    page: Any,
    *,
    include_context_pages: bool = True,
) -> bool:
    """Keep a real player page from being replaced by a weaker side link."""
    selectors = (
        "button.shaka-load-player-btn",
        "button[class*='shaka-load-player-btn']",
        "[data-shaka-player] button[aria-label*='play' i]",
        "[data-player] button[aria-label*='play' i]",
    )
    pages = (
        agent._playback_pages(page)
        if include_context_pages
        else [page]
    )
    for candidate_page in pages:
        for frame in getattr(candidate_page, "frames", []):
            for selector in selectors:
                try:
                    controls = frame.locator(selector)
                    for index in range(await controls.count()):
                        if await controls.nth(index).is_visible():
                            return True
                except Exception:
                    continue
    return await agent._has_visible_media_element(page)


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
    agent,
    page: Any,
    *,
    attempts: int,
    include_context_pages: bool = True,
) -> str | None:
    for _ in range(max(1, attempts)):
        await asyncio.sleep(1)
        active_reason = await agent.detect_active_playback(
            page,
            include_context_pages=include_context_pages,
        )
        if active_reason:
            return active_reason
    return None


async def _try_media_candidate_playback(agent, context: Any) -> Any | None:
    """Play a captured media URL when the provider exposes no clickable control."""
    direct_media_pattern = re.compile(
        r"\.(?:m3u8|mpd|mp4|m4a|mp3|aac|wav)(?:$|[?#])",
        re.IGNORECASE,
    )
    for media_url in tuple(agent.media_candidates[:5]):
        if not direct_media_pattern.search(media_url):
            continue
        media_path = urlparse(media_url).path
        if (
            NON_PLAYBACK_MEDIA_PATH_PATTERN.search(media_path)
            or EXPIRED_MEDIA_PATH_PATTERN.search(media_path)
        ):
            print(
                f"[{agent.ticker}] skipping non-playable media candidate: "
                f"{media_url[:160]}",
                flush=True,
            )
            continue
        try:
            media_page = await context.new_page()
            agent._attach_media_watchers(media_page)
            await media_page.goto(
                media_url,
                wait_until="domcontentloaded",
                timeout=agent.page_ready_timeout_ms,
            )
            await agent._wait_for_dynamic_page(media_page)
            if not await agent._has_visible_media_element(media_page):
                await media_page.close()
                continue
            playback_triggered = await agent.trigger_media_playback(
                media_page,
                allow_control_scan=False,
            )
            if playback_triggered:
                print(
                    f"[{agent.ticker}] direct media candidate became active: "
                    f"{media_url[:160]}",
                    flush=True,
                )
                return media_page
            await media_page.close()
        except Exception as exc:
            print(
                f"[{agent.ticker}] direct media candidate skipped: "
                f"{str(exc)[:120]}",
                flush=True,
            )
            try:
                await media_page.close()
            except Exception:
                pass
    return None


async def _prime_direct_player_audio(
    agent,
    page: Any,
    *,
    include_context_pages: bool = True,
) -> None:
    """Use trusted media clicks so direct HTML5 players create a PulseAudio sink-input."""
    pages = agent._playback_pages(page) if include_context_pages else [page]
    for candidate_page in pages:
        url = str(candidate_page.url)
        if not is_audio_priming_player_url(url) or url in agent._direct_audio_primed_urls:
            continue
        try:
            is_youtube = is_direct_player_url(url)
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
                agent._direct_audio_primed_urls.add(url)
                print(
                    f"[{agent.ticker}] primed HTML5 direct-player audio with a trusted video click",
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
            agent._direct_audio_primed_urls.add(url)
            print(
                f"[{agent.ticker}] primed direct-player audio with trusted "
                f"mute and video clicks was_playing={was_playing}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[{agent.ticker}] direct-player audio priming skipped: "
                f"{str(exc)[:120]}",
                flush=True,
            )


async def _prime_media_audio(
    agent,
    page: Any,
    *,
    include_context_pages: bool = True,
) -> None:
    """Unmute visible media and enable audio tracks before checking playback."""
    pages = agent._playback_pages(page) if include_context_pages else [page]
    for candidate_page in pages:
        page_frames = getattr(candidate_page, "frames", None)
        if not isinstance(page_frames, (list, tuple)):
            page_frames = [getattr(candidate_page, "main_frame", candidate_page)]
        for frame in page_frames:
            try:
                primed = await asyncio.wait_for(
                    frame.evaluate(
                        """async () => {
                        const media = Array.from(document.querySelectorAll('video, audio'));
                        let primed = 0;
                        for (const element of media) {
                            const rect = element.getBoundingClientRect();
                            const style = window.getComputedStyle(element);
                            if (style.display === 'none' || style.visibility === 'hidden' ||
                                rect.width <= 2 || rect.height <= 2) continue;
                            element.muted = false;
                            element.volume = 1;
                            if (element.audioTracks) {
                                for (let index = 0; index < element.audioTracks.length; index += 1) {
                                    element.audioTracks[index].enabled = true;
                                }
                            }
                            try { await element.play(); } catch (_) {}
                            primed += 1;
                        }
                        return primed;
                    }"""
                    ),
                    timeout=6,
                )
                if primed:
                    print(
                        f"[{agent.ticker}] primed visible media audio elements={primed}",
                        flush=True,
                    )
            except Exception:
                continue


async def _click_playback_control(agent, control: Any, label: str) -> bool:
    """Click a player control after bringing it into the active viewport.

    Embedded players can render a visible button inside a scrollable frame
    while Playwright still considers its hit target outside the viewport.
    The DOM click fallback is limited to the same verified control.
    """
    try:
        await control.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    try:
        await asyncio.wait_for(control.click(force=True, timeout=5000), timeout=6)
        return True
    except Exception as exc:
        print(
            f"[{agent.ticker}] player control click retry: {label[:80]} "
            f"({str(exc)[:120]})",
            flush=True,
        )
    try:
        await asyncio.wait_for(
            control.evaluate(
                """element => {
                    element.scrollIntoView({block: 'center', inline: 'center'});
                    element.focus?.();
                    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup']) {
                        element.dispatchEvent(new MouseEvent(type, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                        }));
                    }
                    element.click();
                    return true;
                }"""
            ),
            timeout=4,
        )
        return True
    except Exception as exc:
        print(
            f"[{agent.ticker}] player control retry failed: {label[:80]} "
            f"({str(exc)[:120]})",
            flush=True,
        )
        return False


async def _retry_shaka_playback_control(
    agent,
    page: Any,
    *,
    include_context_pages: bool,
    timeout_seconds: float = 10.0,
) -> bool:
    """Re-scan late-created Shaka frames before declaring playback blocked."""
    deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
    while asyncio.get_running_loop().time() < deadline:
        pages = agent._playback_pages(page) if include_context_pages else [page]
        for candidate_page in pages:
            try:
                frames = list(candidate_page.frames)
            except Exception:
                frames = []
            for frame in frames:
                try:
                    controls = frame.locator(
                        "button.shaka-load-player-btn, "
                        "button[class*='shaka-load-player-btn']"
                    )
                    count = await asyncio.wait_for(controls.count(), timeout=2)
                except Exception:
                    continue
                for index in range(count):
                    try:
                        control = controls.nth(index)
                        if not await asyncio.wait_for(control.is_visible(), timeout=1):
                            continue
                        label = " ".join(
                            value.strip()
                            for value in (
                                await asyncio.wait_for(control.inner_text(), timeout=1),
                                await control.get_attribute("aria-label"),
                                await control.get_attribute("title"),
                            )
                            if value and value.strip()
                        ) or "Shaka playback button"
                        print(
                            f"[{agent.ticker}] retrying preferred player control: "
                            f"{label[:80]}",
                            flush=True,
                        )
                        if not await agent._click_playback_control(control, label):
                            continue
                        active_reason = await agent._wait_for_active_playback(
                            page,
                            attempts=6,
                            include_context_pages=include_context_pages,
                        )
                        if active_reason:
                            print(
                                f"[{agent.ticker}] playback became active after "
                                f"preferred retry: {active_reason}",
                                flush=True,
                            )
                            return True
                        # Some Shaka wrappers bind activation to keyboard
                        # events even when the visible button's DOM click
                        # is accepted. Retry the same verified control before
                        # scanning unrelated page elements.
                        for key in ("Space", "Enter"):
                            try:
                                await control.press(key, timeout=3000)
                            except Exception:
                                continue
                            active_reason = await agent._wait_for_active_playback(
                                page,
                                attempts=4,
                                include_context_pages=include_context_pages,
                            )
                            if active_reason:
                                print(
                                    f"[{agent.ticker}] playback became active after "
                                    f"preferred keyboard retry: {active_reason}",
                                    flush=True,
                                )
                                return True
                    except Exception:
                        # The provider may replace the iframe immediately after
                        # the click. Continue with the newest frame on next pass.
                        continue
        await asyncio.sleep(0.5)
    return False


async def trigger_media_playback(
    agent,
    page: Any,
    *,
    allow_control_scan: bool = True,
    page_scope_only: bool = False,
    require_active_confirmation: bool = False,
) -> bool:
    try:
        return await asyncio.wait_for(
            agent._trigger_media_playback(
                page,
                allow_control_scan=allow_control_scan,
                page_scope_only=page_scope_only,
                require_active_confirmation=require_active_confirmation,
            ),
            timeout=agent.playback_control_timeout_seconds,
        )
    except asyncio.TimeoutError:
        print(
            f"[{agent.ticker}] player control search timed out after "
            f"{agent.playback_control_timeout_seconds:g}s",
            flush=True,
        )
        return False


async def _trigger_media_playback(
    agent,
    page: Any,
    *,
    allow_control_scan: bool,
    page_scope_only: bool,
    require_active_confirmation: bool,
) -> bool:
    include_context_pages = not page_scope_only
    try:
        await asyncio.wait_for(
            agent._prime_direct_player_audio(
                page,
                include_context_pages=include_context_pages,
            ),
            timeout=min(8.0, agent.playback_control_timeout_seconds / 2),
        )
    except asyncio.TimeoutError:
        print(f"[{agent.ticker}] direct-player audio priming timed out; checking playback", flush=True)
    try:
        await asyncio.wait_for(
            agent._prime_media_audio(
                page,
                include_context_pages=include_context_pages,
            ),
            timeout=min(8.0, agent.playback_control_timeout_seconds / 2),
        )
    except asyncio.TimeoutError:
        print(f"[{agent.ticker}] media audio priming timed out; checking playback", flush=True)
    active_reason = await agent.detect_active_playback(
        page,
        include_context_pages=include_context_pages,
    )
    if active_reason:
        print(f"[{agent.ticker}] playback already active: {active_reason}", flush=True)
        return True

    print(f"[{agent.ticker}] waiting for player to become active", flush=True)
    active_reason = await agent._wait_for_active_playback(
        page,
        attempts=8,
        include_context_pages=include_context_pages,
    )
    if active_reason:
        print(f"[{agent.ticker}] playback became active: {active_reason}", flush=True)
        return True

    try:
        control_clicked = False
        if allow_control_scan:
            print(f"[{agent.ticker}] searching for player controls", flush=True)
            try:
                await page.wait_for_selector(
                    "button, a, div[role='button']",
                    state="visible",
                    timeout=8000,
                )
            except Exception:
                pass

            pages = [page] if page_scope_only else agent._playback_pages(page)
            for candidate_page in pages:
                for frame in candidate_page.frames:
                    # Shaka's load button is the actual player entry point.
                    # Handle it before broad icon scanning so an analytics
                    # or overlay SVG cannot detach the media frame first.
                    preferred_controls = frame.locator(
                        "button.shaka-load-player-btn, "
                        "button[class*='shaka-load-player-btn']"
                    )
                    preferred_count = await asyncio.wait_for(
                        preferred_controls.count(), timeout=3
                    )
                    for index in range(preferred_count):
                        button = preferred_controls.nth(index)
                        if not await asyncio.wait_for(button.is_visible(), timeout=2):
                            continue
                        label = " ".join(
                            value.strip()
                            for value in (
                                await asyncio.wait_for(button.inner_text(), timeout=2),
                                await button.get_attribute("aria-label"),
                                await button.get_attribute("title"),
                            )
                            if value and value.strip()
                        ) or "Shaka playback button"
                        print(
                            f"[{agent.ticker}] clicking preferred player control: "
                            f"{label[:80]}",
                            flush=True,
                        )
                        if not await agent._click_playback_control(button, label):
                            continue
                        control_clicked = True
                        active_reason = await agent._wait_for_active_playback(
                            page,
                            attempts=12,
                            include_context_pages=include_context_pages,
                        )
                        if active_reason:
                            print(
                                f"[{agent.ticker}] playback became active after click: "
                                f"{active_reason}",
                                flush=True,
                            )
                            return True
                        print(
                            f"[{agent.ticker}] preferred control did not activate playback: "
                            f"{label[:80]}",
                            flush=True,
                        )

                    if await agent._retry_shaka_playback_control(
                        page,
                        include_context_pages=include_context_pages,
                        timeout_seconds=8.0,
                    ):
                        return True

                    # A large number of webcast players expose only an
                    # aria-label or title on icon buttons, so text filtering
                    # alone misses them. Keep selectors keyword-scoped.
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
                        class_name = (
                            await button.get_attribute("class") or ""
                        ).lower()
                        if "shaka-load-player-btn" in class_name:
                            continue
                        if await asyncio.wait_for(button.is_visible(), timeout=2):
                            # IR pages often contain ordinary links whose
                            # text includes "webcast", "listen", or
                            # "replay". They are navigation candidates,
                            # not player controls. Only consider anchors
                            # that are actually scoped to a media/player
                            # container; real player buttons continue
                            # through the existing label and SVG checks.
                            try:
                                unscoped_anchor = bool(
                                    await asyncio.wait_for(
                                        button.evaluate(
                                            """element => {
                                                if (element.tagName.toLowerCase() !== 'a') {
                                                    return false;
                                                }
                                                return !element.closest(
                                                    '[data-shaka-player], [data-player], '
                                                    + '[class*="player" i], [id*="player" i], '
                                                    + '[class*="video" i], [id*="video" i], '
                                                    + '[class*="media" i], [id*="media" i], '
                                                    + '[class*="webcast" i], [id*="webcast" i]'
                                                );
                                            }"""
                                        ),
                                        timeout=2,
                                    )
                                )
                            except Exception:
                                unscoped_anchor = False
                            if unscoped_anchor:
                                continue
                            label = " ".join(
                                value.strip()
                                for value in (
                                    await asyncio.wait_for(button.inner_text(), timeout=2),
                                    await button.get_attribute("aria-label"),
                                    await button.get_attribute("title"),
                                )
                                if value and value.strip()
                            ) or "player control"
                            unlabeled_icon_control = False
                            if not is_playback_control_label(label):
                                try:
                                    unlabeled_icon_control = bool(
                                        await asyncio.wait_for(
                                            button.evaluate(
                                                """element => {
                                                    if (!element.querySelector('svg, use, path')) {
                                                        return false;
                                                    }
                                                    const rect = element.getBoundingClientRect();
                                                    if (rect.width <= 0 || rect.height <= 0) return false;
                                                    const parts = [];
                                                    let current = element;
                                                    for (let depth = 0; current && depth < 6; depth += 1) {
                                                        parts.push(current.id, current.className);
                                                        current = current.parentElement;
                                                    }
                                                    const context = parts.filter(Boolean).join(' ');
                                                    if (/registration|register|login|form|email|company|logout/i.test(context)) {
                                                        return false;
                                                    }
                                                    const playerContainer = element.closest(
                                                        '[data-shaka-player], [data-player], '
                                                        + '[class*="player" i], [id*="player" i], '
                                                        + '[class*="video" i], [id*="video" i], '
                                                        + '[class*="media" i], [id*="media" i], '
                                                        + '[class*="webcast" i], [id*="webcast" i]'
                                                    );
                                                    if (!playerContainer) return false;
                                                    const lowerViewport = rect.top >= window.innerHeight * 0.45;
                                                    return lowerViewport || /player|video|media|playback|webcast|shaka/i.test(context);
                                                }"""
                                            ),
                                            timeout=2,
                                        )
                                    )
                                except Exception:
                                    unlabeled_icon_control = False
                                if not unlabeled_icon_control:
                                    continue
                                label = "unlabeled playback icon"
                            if not is_playback_control_label(label) and not unlabeled_icon_control:
                                continue
                            print(
                                f"[{agent.ticker}] clicking player control: {label[:80]}",
                                flush=True,
                            )
                            if not await agent._click_playback_control(button, label):
                                continue
                            control_clicked = True
                            active_reason = await agent._wait_for_active_playback(
                                page,
                                attempts=12,
                                include_context_pages=include_context_pages,
                            )
                            if active_reason:
                                print(
                                    f"[{agent.ticker}] playback became active after click: "
                                    f"{active_reason}",
                                    flush=True,
                                )
                                return True
                            print(
                                f"[{agent.ticker}] control did not activate playback: "
                                f"{label[:80]}",
                                flush=True,
                            )

        if control_clicked:
            if require_active_confirmation:
                print(
                    f"[{agent.ticker}] player control click was not confirmed by "
                    "the target page",
                    flush=True,
                )
                return False
            print(
                f"[{agent.ticker}] playback control clicked; deferring final "
                "confirmation to media and OS audio checks",
                flush=True,
            )

        pages = [page] if page_scope_only else agent._playback_pages(page)
        for candidate_page in pages:
            page_frames = getattr(candidate_page, "frames", None)
            if not isinstance(page_frames, (list, tuple)):
                page_frames = [getattr(candidate_page, "main_frame", candidate_page)]
            for frame in page_frames:
                try:
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
                except Exception:
                    continue
                if started:
                    active_reason = await agent._wait_for_active_playback(
                        page,
                        attempts=5,
                        include_context_pages=include_context_pages,
                    )
                    if active_reason:
                        print(
                            f"[{agent.ticker}] started HTML media element: "
                            f"{active_reason}",
                            flush=True,
                        )
                        return True
                    print(
                        f"[{agent.ticker}] media.play() resolved; deferring final "
                        "confirmation to the OS audio probe",
                        flush=True,
                    )
                    return True
        if control_clicked:
            return True
        print(f"[{agent.ticker}] no active media or playable control found", flush=True)
        return False
    except Exception as exc:
        print(f"[{agent.ticker}] media playback trigger skipped: {str(exc)[:120]}")
        return False
