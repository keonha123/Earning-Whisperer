"""Browser navigation, cookies, barriers and session persistence."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from .rules import (
    ACCESS_BARRIER_PATTERN,
    AUTHENTICATION_FORM_TEXT_PATTERN,
    AUTHENTICATION_SURFACE_URL_PATTERN,
    COOKIE_CONSENT_TEXT_PATTERN,
    DISCLOSURE_AGREEMENT_PAGE_PATTERN,
    DYNAMIC_LOADING_PATTERN,
    EXPIRED_EVENT_PATTERN,
    HTTP_ACCESS_BARRIER_STATUSES,
    HumanPageAssessment,
    LEGAL_OVERLAY_TEXT_PATTERN,
    MISSING_RESOURCE_URL_PATTERN,
    NON_PLAYBACK_DOCUMENT_PATTERN,
    NON_PLAYBACK_URL_HOSTS,
    NON_PLAYBACK_URL_PATH_PATTERN,
    NOT_LIVE_EVENT_PATTERN,
    RESOURCE_NOT_FOUND_PATTERN,
    SURVEY_TEXT_PATTERN,
    access_fallback_urls,
    future_event_date_reason,
    is_direct_player_url,
    is_webcast_player_url,
    is_media_candidate_url,
    is_nonessential_popup_url,
    non_earnings_event_reason,
)


async def _try_verified_player_fallback(
    agent,
    source_page: Any,
    timeout_error: Any,
) -> Any | None:
    """Use an audio-verified external player when the IR entry page is blocked."""
    return await agent._try_verified_player_fallback_in_context(
        source_page.context,
        source_page.url,
        timeout_error,
    )


async def _try_verified_player_fallback_in_context(
    agent,
    context: Any,
    source_url: str,
    timeout_error: Any,
) -> Any | None:
    """Open a verified external player before or after an IR page barrier."""
    if agent.lifecycle != "replay":
        return None

    for recipe in agent._load_verified_recipes(source_url):
        verified_url = str(recipe.evidence.get("verified_player_url") or "").strip()
        parsed_url = urlparse(verified_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue

        target_page = await context.new_page()
        agent._attach_media_watchers(target_page)
        agent._active_recipe = recipe
        agent._recipe_origin = "verified"
        agent._write_recipe_context()
        print(
            f"[{agent.ticker}] opening verified player route: {verified_url}",
            flush=True,
        )
        try:
            try:
                await target_page.goto(
                    verified_url,
                    wait_until="commit",
                    timeout=agent.page_ready_timeout_ms,
                )
                try:
                    await target_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=min(agent.page_ready_timeout_ms, 5000),
                    )
                except Exception:
                    pass
            except Exception as exc:
                if await target_page.locator("body").count() == 0:
                    print(
                        f"[{agent.ticker}] verified player unavailable: {str(exc)[:160]}",
                        flush=True,
                    )
                    await target_page.close()
                    continue
                print(
                    f"[{agent.ticker}] verified player navigation timed out; inspecting DOM",
                    flush=True,
                )

            await asyncio.sleep(1)
            await agent._wait_for_dynamic_page(target_page)
            await agent.accept_cookie_banners(target_page)
            agent._registration_target_page = None
            if await agent._detect_access_barrier(target_page):
                await target_page.close()
                continue
            not_live_reason = await agent._detect_not_live_event(target_page)
            if not_live_reason:
                agent._not_live_reason = not_live_reason
                await target_page.close()
                return None

            form_success = await agent.handle_registration_form(
                target_page,
                timeout_error,
            )
            target_page = agent._registration_target_page or target_page
            if not form_success:
                await target_page.close()
                continue

            if await agent.trigger_media_playback(
                target_page,
                allow_control_scan=True,
                page_scope_only=True,
            ):
                print(
                    f"[{agent.ticker}] verified player fallback became audible-ready",
                    flush=True,
                )
                return target_page
        except Exception as exc:
            print(
                f"[{agent.ticker}] verified player fallback failed: {str(exc)[:160]}",
                flush=True,
            )
        try:
            if not target_page.is_closed():
                await target_page.close()
        except Exception:
            pass
    return None


def _context_options(agent) -> dict[str, Any]:
    context_options: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 1000},
        "locale": "en-US",
    }
    if agent.storage_state_path and Path(agent.storage_state_path).exists():
        context_options["storage_state"] = agent.storage_state_path
    return context_options


async def _open_ir_page(agent, context: Any) -> Any:
    page = await context.new_page()
    agent._attach_media_watchers(page)
    entrypoints = (agent.ir_url, *access_fallback_urls(agent.ir_url))
    last_navigation_error: Exception | None = None

    for entrypoint_index, entrypoint in enumerate(entrypoints):
        if entrypoint_index == 0:
            print(f"[{agent.ticker}] opening IR page: {entrypoint}", flush=True)
        else:
            print(
                f"[{agent.ticker}] access barrier on primary entrypoint; "
                f"trying fallback: {entrypoint}",
                flush=True,
            )

        # Investor pages commonly leave analytics/media requests pending
        # even though their interactive DOM is already available.
        navigation_timed_out = False
        agent._page_http_status = None
        last_navigation_error = None
        try:
            response = await asyncio.wait_for(
                page.goto(
                    entrypoint,
                    wait_until="commit",
                    timeout=agent.page_ready_timeout_ms,
                ),
                timeout=(agent.page_ready_timeout_ms / 1000) + 3,
            )
            agent._page_http_status = response.status if response else None
            try:
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=min(agent.page_ready_timeout_ms, 5000),
                )
            except Exception:
                print(
                    f"[{agent.ticker}] DOMContentLoaded delayed; inspecting rendered DOM",
                    flush=True,
                )
        except asyncio.TimeoutError:
            navigation_timed_out = True
            print(
                f"[{agent.ticker}] IR navigation exceeded the local timeout; "
                "checking verified player fallback",
                flush=True,
            )
        except Exception as exc:
            last_navigation_error = exc
            if await page.locator("body").count() == 0 and entrypoint_index == len(entrypoints) - 1:
                raise
            print(
                f"[{agent.ticker}] navigation timed out; inspecting rendered DOM: "
                f"{str(exc)[:120]}",
                flush=True,
            )

        await asyncio.sleep(0.5 if navigation_timed_out else 2)
        await agent._wait_for_dynamic_page(page)
        if not navigation_timed_out:
            await agent.accept_cookie_banners(page)
        agent._page_barrier = await agent._detect_access_barrier(page)
        if navigation_timed_out and not agent._page_barrier:
            agent._page_barrier = "IR navigation timeout"

        if not agent._page_barrier:
            if entrypoint_index:
                print(
                    f"[{agent.ticker}] access fallback opened successfully: {entrypoint}",
                    flush=True,
                )
            return page

        if entrypoint_index < len(entrypoints) - 1:
            await asyncio.sleep(
                max(0.0, float(os.getenv("WEBCAST_ACCESS_RETRY_DELAY_SECONDS", "1")))
            )

    if last_navigation_error and await page.locator("body").count() == 0:
        raise last_navigation_error
    print(
        f"[{agent.ticker}] access fallback routes exhausted: {agent._page_barrier}",
        flush=True,
    )
    return page


async def _open_direct_target_page(agent, context: Any, target_url: str) -> Any:
    """Open a stored replay candidate without treating it as an IR archive.

    Candidate retries deliberately preserve the original IR URL for audit
    reporting. This method is the boundary that turns the separate replay
    target into the browser's actual starting page.
    """
    print(f"[{agent.ticker}] opening direct replay candidate: {target_url}", flush=True)
    # Preserve the candidate before navigation. Providers can leave a blank
    # page or time out before the browser writes any later handshake file.
    agent._record_target_url(target_url)
    page = None
    retry_count = max(
        1,
        int(os.getenv("WEBCAST_DIRECT_TARGET_RETRIES", "2")),
    )
    for attempt in range(retry_count):
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        page = await context.new_page()
        agent._attach_media_watchers(page)
        agent._page_http_status = None
        try:
            response = await asyncio.wait_for(
                page.goto(
                    target_url,
                    wait_until="commit",
                    timeout=agent.direct_target_navigation_timeout_ms,
                ),
                timeout=(agent.direct_target_navigation_timeout_ms / 1000) + 3,
            )
            agent._page_http_status = response.status if response else None
            break
        except asyncio.TimeoutError:
            print(
                f"[{agent.ticker}] direct replay candidate navigation timed out "
                f"(attempt {attempt + 1}/{retry_count}); inspecting rendered DOM",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[{agent.ticker}] direct replay candidate navigation warning "
                f"(attempt {attempt + 1}/{retry_count}): {str(exc)[:160]}",
                flush=True,
            )
        current_url = str(getattr(page, "url", ""))
        if current_url not in {"", "about:blank"}:
            # A slow provider may commit the navigation after Playwright's
            # deadline. Keep that page for DOM/player discovery instead of
            # replacing it with a fresh blank tab on the next retry.
            agent._record_target_url(current_url)
            print(
                f"[{agent.ticker}] retaining direct replay page after navigation warning: "
                f"{current_url}",
                flush=True,
            )
            break
        if attempt + 1 < retry_count:
            await asyncio.sleep(
                max(0.0, float(os.getenv("WEBCAST_DIRECT_TARGET_RETRY_DELAY_SECONDS", "1")))
            )

    assert page is not None
    try:
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=min(agent.page_ready_timeout_ms, 5000),
        )
    except Exception:
        pass
    await asyncio.sleep(0.5)
    await agent._wait_for_dynamic_page(page)
    await agent.accept_cookie_banners(page)
    agent._page_barrier = await agent._detect_access_barrier(page)
    return page


async def _wait_for_dynamic_page(agent, page: Any) -> None:
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
        f"[{agent.ticker}] provider is still loading; waiting up to "
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
            print(f"[{agent.ticker}] provider loading shell resolved", flush=True)
            return


async def _detect_access_barrier(agent, page: Any) -> str | None:
    from .access_barriers import flow_surfaces, inspect_flow_surfaces, record_barrier_evidence

    status = getattr(agent, '_page_http_status', None)
    if status in HTTP_ACCESS_BARRIER_STATUSES:
        barrier = f"HTTP {status}"
        record_barrier_evidence(agent, 'access', [{'surface': page, 'kind': 'main',
            'visible': True, 'relevant': True, 'reason': 'main_response', 'rule': barrier}], barrier)
        return barrier
    if AUTHENTICATION_SURFACE_URL_PATTERN.search(str(getattr(page, "url", ""))):
        barrier = "AUTH_REQUIRED authentication/login surface"
        record_barrier_evidence(agent, 'access', [{'surface': page, 'kind': 'main',
            'visible': True, 'relevant': True, 'reason': 'main_route', 'rule': 'authentication_route'}], barrier)
        return barrier
    surfaces = await flow_surfaces(page)
    evidence_by_surface = await inspect_flow_surfaces(surfaces)
    barrier = None
    for item, evidence in zip(surfaces, evidence_by_surface):
        if evidence is None:
            continue
        item.update({key: evidence[key] for key in ('text_available', 'visible_challenge_control') if key in evidence})
        body_text = evidence['body_text']
        if evidence['captcha_gate']:
            item['rule'] = 'visible_human_challenge'
            barrier = "anti-bot captcha requires manual verification"
        elif AUTHENTICATION_FORM_TEXT_PATTERN.search(body_text):
            item['rule'] = 'authentication_form'
            barrier = "AUTH_REQUIRED authentication/login form"
        else:
            # CAPTCHA attribution is not proof that this event requires a
            # human challenge. Actual controls/instructions are checked above.
            matches = (m for m in ACCESS_BARRIER_PATTERN.finditer(body_text)
                       if m.group(0).lower() != 'captcha')
            match = next(matches, None)
            if match:
                item['rule'] = 'visible_access_denial'
                barrier = match.group(0)
        if barrier:
            break
    record_barrier_evidence(agent, 'access', surfaces, barrier)
    return barrier


async def _detect_registration_barrier(agent, page: Any) -> str | None:
    """Recognize visible, flow-relevant gates without interacting with them."""
    from .access_barriers import flow_surfaces, inspect_flow_surfaces, record_barrier_evidence

    surfaces = await flow_surfaces(page)
    evidence_by_surface = await inspect_flow_surfaces(surfaces)
    barrier = None
    for item, evidence in zip(surfaces, evidence_by_surface):
        if evidence is None:
            continue
        item.update({key: evidence[key] for key in ('text_available', 'visible_challenge_control') if key in evidence})
        body_text = evidence['body_text']
        if evidence['captcha_gate']:
            item['rule'] = 'visible_human_challenge'
            barrier = "anti-bot captcha requires manual verification"
        elif re.search(r"acceptance of the .* terms of use|privacy policy.*this field is required", body_text, re.I):
            item['rule'] = 'mandatory_consent'
            barrier = "mandatory terms/privacy consent is required"
        if barrier:
            break
    record_barrier_evidence(agent, 'registration', surfaces, barrier)
    return barrier


async def _detect_expired_event(agent, page: Any) -> str | None:
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


async def _detect_not_live_event(
    agent, page: Any, *, selected_event_evidence: str | None = None,
) -> str | None:
    """Only a selected, matching event may delay a live probe.

    IR indexes and player shells can also contain next quarter's event or an
    unrelated waiting-room message. Their body text is not schedule evidence.
    """
    if agent.lifecycle == "live":
        from .rules import live_event_wait_reason

        if selected_event_evidence:
            from ...schedules.browser_observation import observe_browser_time
            observe_browser_time(agent, selected_event_evidence)
            return live_event_wait_reason(
                selected_event_evidence, target_date=agent.target_date,
                target_time_utc=agent.target_time_utc,
            )
        # Registration can reveal the dated waiting room only after submitting.
        # Inspect it only on a proven player route, never the issuer's IR index.
        page_url = str(getattr(page, 'url', '') or '')
        parsed = urlparse(page_url)
        webinar_player = (
            (parsed.hostname or '').lower() in {'app.webinar.net', 'webinar.net'}
            and re.fullmatch(r'/[A-Za-z0-9_-]+/live/?', parsed.path) is not None
        )
        from .navigation import provider_event_id
        if not (webinar_player or provider_event_id(page_url) or is_webcast_player_url(page_url)):
            return None
        if not await agent._validate_live_target_page(page):
            return None
        # Reuse the already-open, authenticated event page; no extra browser,
        # form submission or playback is needed to learn its precise clock.
        try:
            from ...schedules.browser_observation import observe_browser_time
            body = await page.locator('body').inner_text(timeout=1500)
            observe_browser_time(agent, body[:12000], evidence_url=page_url)
        except Exception:
            pass
        try:
            # Keep the bounded DOM prefilter and final classification on one
            # vocabulary. A second JS regex used to discard valid provider
            # notices (e.g. "return to this page ... before the start") before
            # the event/date guards below could inspect them.
            evidence_blocks = await asyncio.wait_for(page.evaluate("""pattern => {
                const waiting = new RegExp(pattern, 'i');
                const visible = e => {const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                    return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';};
                const blocks = Array.from(document.querySelectorAll(
                    '[role="dialog"],[aria-modal="true"],dialog,section,article,div'
                )).slice(0,2000).filter(visible).map(e=>({
                    text:(e.innerText || '').replace(/\\s+/g,' ').trim(),
                    modal:e.matches('[role="dialog"],[aria-modal="true"],dialog')
                })).filter(b=>b.text.length>15 && b.text.length<2000 && waiting.test(b.text));
                return blocks.sort((a,b)=>a.text.length-b.text.length).slice(0,20);
            }""", NOT_LIVE_EVENT_PATTERN.pattern), timeout=2)
        except Exception:
            return None
        from ..webcast_learning import (
            EVENT_DATE_PATTERN, DAY_FIRST_EVENT_DATE_PATTERN, NUMERIC_EVENT_DATE_PATTERN,
            SHORT_NUMERIC_EVENT_DATE_PATTERN, ISO_EVENT_DATE_PATTERN, COMPACT_EVENT_DATE_PATTERN,
            event_date_from_text, event_identity_text,
            WebcastCandidate, candidate_identity_mismatch,
        )
        for block in evidence_blocks:
            evidence = block.get("text", "") if isinstance(block, dict) else block
            if not isinstance(evidence, str) or not NOT_LIVE_EVENT_PATTERN.search(evidence):
                continue
            candidate = WebcastCandidate(
                "waiting-status", (), None, evidence, "", "", None, "dialog", {},
            )
            if candidate_identity_mismatch(
                candidate, target_ticker=agent.ticker,
                target_year=getattr(agent, "target_year", None),
                target_quarter=getattr(agent, "target_quarter", None),
                target_date=agent.target_date,
            ):
                continue
            # A container mixing today's call and another dated event cannot
            # authorize waiting, even on an otherwise verified player URL.
            dates = {event_date_from_text(match.group(0)) for pattern in (
                EVENT_DATE_PATTERN, DAY_FIRST_EVENT_DATE_PATTERN, NUMERIC_EVENT_DATE_PATTERN,
                SHORT_NUMERIC_EVENT_DATE_PATTERN, ISO_EVENT_DATE_PATTERN, COMPACT_EVENT_DATE_PATTERN,
            ) for match in pattern.finditer(event_identity_text(evidence))}
            dates.discard(None)
            # Some webinar.net waiting modals omit the date after registration.
            # The current event's fresh, exact provider-route proof above can
            # authenticate that explicit modal; generic undated page containers
            # cannot. This does not infer or change a scheduled start time.
            if (not dates and webinar_player and isinstance(block, dict)
                    and block.get("modal") is True):
                from .rules import non_earnings_event_reason
                # "Webinar" is generic provider UI here, not an event type;
                # explicit investor-day/conference labels still contradict us.
                event_label = re.sub(r"\bwebinar\b", "", evidence, flags=re.I)
                if not non_earnings_event_reason(event_label):
                    return NOT_LIVE_EVENT_PATTERN.search(evidence).group(0)
            if dates != {agent.target_date}:
                continue
            reason = live_event_wait_reason(
                evidence, target_date=agent.target_date, target_time_utc=agent.target_time_utc,
            )
            if reason:
                return reason
        return None
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


async def _detect_non_earnings_event(
    agent,
    page: Any,
    clicked_text: str = "",
) -> str | None:
    """Avoid treating a playable investor-day recording as this earnings call."""
    # The selected row is the strongest event identity signal. Provider
    # player shells often contain generic "earnings" copy unrelated to the
    # event currently being played, so do not let that copy override a
    # clearly non-earnings row title.
    label_reason = non_earnings_event_reason(clicked_text)
    if label_reason:
        return label_reason

    # Event identity belongs to the selected/current tab. Including every
    # context tab lets stale archive copy (for example, a technology
    # conference left open behind an earnings registration form) poison the
    # classification after a human baton return.
    text_parts: list[str] = []
    page_frames = getattr(page, "frames", None)
    if not isinstance(page_frames, (list, tuple)):
        page_frames = [getattr(page, "main_frame", page)]
    for frame in page_frames:
        try:
            text_parts.append((await frame.locator("body").inner_text(timeout=2000))[:5000])
        except Exception:
            continue
    return non_earnings_event_reason(" ".join(text_parts))


async def _accept_replay_training_proxy(
    agent,
    page: Any,
    event_reason: str,
) -> bool:
    """Use a historical non-earnings webcast to train downstream stages only."""
    if agent.lifecycle != "replay":
        return False

    registration_barrier = await agent._detect_registration_barrier(page)
    has_registration = await agent.has_registration_form(page)
    has_player = (
        is_direct_player_url(str(page.url))
        or await agent._has_visible_media_element(
            page,
            include_context_pages=False,
        )
        or bool(
            await agent.detect_active_playback(
                page,
                include_context_pages=False,
            )
        )
        or bool(agent.media_candidates)
    )
    if not any((registration_barrier, has_registration, has_player)):
        return False

    agent._mark_replay_training_proxy(page, event_reason)
    return True


def _replay_training_proxy_mode(agent) -> bool:
    return (
        agent.lifecycle == "replay"
        and os.getenv("WEBCAST_REPLAY_TRAINING_PROXY", "false").lower()
        in {"1", "true", "yes", "on"}
    )


def _mark_replay_training_proxy(agent, page: Any, event_reason: str) -> None:
    agent._training_proxy_event = event_reason
    print(
        f"[{agent.ticker}] REPLAY_TRAINING_PROXY event={event_reason} "
        f"url={page.url}",
        flush=True,
    )


async def _detect_missing_resource(agent, page: Any) -> str | None:
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


async def _wait_for_missing_resource(agent, page: Any) -> str | None:
    """Give slow SPA video routes time to render their terminal 404 state."""
    missing_resource = await agent._detect_missing_resource(page)
    if missing_resource:
        return missing_resource
    page_url = str(page.url).lower()
    if "rev.vbrick.com" not in page_url and "#/videos/" not in page_url:
        return None
    for _ in range(6):
        await asyncio.sleep(1)
        missing_resource = await agent._detect_missing_resource(page)
        if missing_resource:
            return missing_resource
    return None


def _signal_playback_ready(agent, active_url: str | None = None) -> None:
    agent._promote_pending_human_workflows(
        HumanPageAssessment("playback", "playback ready signal"),
    )
    if agent._pending_human_recipe:
        agent._pending_human_recipe.recipe_id = agent._save_recipe(
            agent._pending_human_recipe
        )
        agent._active_recipe = agent._pending_human_recipe
        agent._recipe_origin = "human"
        agent._write_recipe_context()
        print(
            f"[{agent.ticker}] HUMAN_RECIPE_LEARNED "
            f"recipe_id={agent._pending_human_recipe.recipe_id}",
            flush=True,
        )
        agent._pending_human_recipe = None
    agent._record_target_url(active_url)
    if agent.active_player_url_path and active_url:
        agent.active_player_url_path.parent.mkdir(parents=True, exist_ok=True)
        agent.active_player_url_path.write_text(active_url, encoding="utf-8")
    if agent.media_candidates_path:
        agent.media_candidates_path.parent.mkdir(parents=True, exist_ok=True)
        agent.media_candidates_path.write_text(
            json.dumps(agent.media_candidates, ensure_ascii=True),
            encoding="utf-8",
        )
    if agent.playback_ready_path:
        agent.playback_ready_path.parent.mkdir(parents=True, exist_ok=True)
        agent.playback_ready_path.touch()
        print(f"[{agent.ticker}] PLAYBACK_READY path={agent.playback_ready_path}", flush=True)


def _record_target_url(agent, target_url: str | None) -> None:
    """Persist a navigated event/player URL for a later retry.

    This is intentionally broader than the audio-success signal: reaching a
    provider page is useful navigation evidence even when the page is
    currently expired, not live, or fails its audio probe.
    """
    if not agent.last_target_url_path or not target_url:
        return
    parsed = urlparse(str(target_url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return
    if NON_PLAYBACK_DOCUMENT_PATTERN.search(parsed.path):
        return
    hostname = (parsed.hostname or "").lower()
    if any(hostname == host or hostname.endswith(f".{host}") for host in NON_PLAYBACK_URL_HOSTS):
        return
    if NON_PLAYBACK_URL_PATH_PATTERN.search(parsed.path) or "external_share" in parsed.query.lower():
        return
    agent.last_target_url_path.parent.mkdir(parents=True, exist_ok=True)
    agent.last_target_url_path.write_text(str(target_url).strip(), encoding="utf-8")


async def _save_storage_state(agent, context: Any) -> None:
    if not agent.save_storage_state_path:
        return
    path = Path(agent.save_storage_state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await asyncio.wait_for(context.storage_state(path=str(path)), timeout=5)
        print(f"[{agent.ticker}] browser session state saved", flush=True)
    except Exception as exc:
        print(
            f"[{agent.ticker}] browser session state save skipped: "
            f"{str(exc)[:120] or 'timeout'}",
            flush=True,
        )


def _attach_media_watchers(agent, page: Any) -> None:
    page_id = id(page)
    if page_id in agent._watched_page_ids:
        return
    agent._watched_page_ids.add(page_id)

    def remember_url(url: str) -> None:
        if is_media_candidate_url(url) and url not in agent.media_candidates:
            agent.media_candidates.append(url)

    page.on("request", lambda request: remember_url(request.url))

    def remember_response(response: Any) -> None:
        remember_url(response.url)
        if "registration/submit" in response.url.lower():
            print(
                f"[{agent.ticker}] registration response "
                f"status={response.status} url={response.url}",
                flush=True,
            )

    page.on("response", remember_response)


async def accept_cookie_banners(agent, page: Any) -> None:
    cookie_selectors = [
        "#onetrust-accept-btn-handler",
        "#onetrust-reject-all-handler",
        ".onetrust-close-btn-handler",
        "#CookieReportsBanner a[href='#']",
        "#onetrust-pc-sdk button:has-text('Save Preference')",
        "#onetrust-pc-sdk button:has-text('Do not accept')",
    ]

    for candidate_page in agent._playback_pages(page):
        if candidate_page is page or not is_nonessential_popup_url(str(candidate_page.url)):
            continue
        try:
            await candidate_page.close()
            print(
                f"[{agent.ticker}] dismissed nonessential survey tab: "
                f"{candidate_page.url}",
                flush=True,
            )
        except Exception:
            continue

    for candidate_page in agent._playback_pages(page):
        for frame in candidate_page.frames:
            try:
                body_text = await frame.locator("body").inner_text(timeout=1500)
            except Exception:
                continue
            body_excerpt = body_text[:6000]
            if DISCLOSURE_AGREEMENT_PAGE_PATTERN.search(body_excerpt):
                print(
                    f"[{agent.ticker}] disclosure agreement detected; "
                    "leaving agreement controls untouched",
                    flush=True,
                )
                continue

            for selector in cookie_selectors:
                try:
                    button = frame.locator(selector).first
                    if await button.count() > 0 and await button.is_visible():
                        await button.click(force=True)
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue

            # Some issuer templates use a small custom banner instead of
            # OneTrust. Limit this to an explicit cookie context and
            # cookie-specific affirmative labels so registration or legal
            # agreement buttons on the same page are never clicked here.
            if COOKIE_CONSENT_TEXT_PATTERN.search(body_excerpt):
                try:
                    cookie_accept = frame.get_by_role(
                        "button",
                        name=re.compile(
                            r"^(?:i\s+accept|accept\s+(?:all|cookies?)|allow\s+all)$",
                            re.IGNORECASE,
                        ),
                    ).first
                    if (
                        await cookie_accept.count() > 0
                        and await cookie_accept.is_visible()
                    ):
                        await cookie_accept.click(force=True)
                        print(
                            f"[{agent.ticker}] accepted cookie banner",
                            flush=True,
                        )
                        await asyncio.sleep(0.3)
                        continue
                except Exception:
                    pass

            is_survey = bool(SURVEY_TEXT_PATTERN.search(body_excerpt))
            is_hidden_webcast_disclosure = False
            if "#webcast-popup-" in str(candidate_page.url):
                try:
                    is_hidden_webcast_disclosure = (
                        await frame.locator("[data-webcast-url]").count() > 0
                    )
                except Exception:
                    pass
            is_legal_overlay = bool(
                LEGAL_OVERLAY_TEXT_PATTERN.search(body_excerpt)
            ) or is_hidden_webcast_disclosure
            if not (is_survey or is_legal_overlay):
                continue

            # Several IR sites put the webcast URL behind a legal
            # disclosure dialog.  The dialog looks like a dismissible
            # overlay, but closing it skips the only transition to the
            # actual player tab.  Follow that explicit continuation first.
            if is_legal_overlay:
                try:
                    continuation = frame.locator("[data-webcast-url]").first
                    if await continuation.count() > 0:
                        webcast_url = (
                            await continuation.get_attribute("data-webcast-url")
                            or ""
                        ).strip()
                        label = " ".join(
                            value.strip()
                            for value in (
                                await continuation.inner_text(),
                                await continuation.get_attribute("aria-label"),
                                await continuation.get_attribute("title"),
                            )
                            if value and value.strip()
                        )
                        disclosure_key = f"{candidate_page.url}|{webcast_url}"
                        if (
                            webcast_url.startswith(("http://", "https://"))
                            and disclosure_key not in agent._followed_webcast_disclosures
                            and re.search(
                                r"continue|proceed|webcast|listen|view",
                                label,
                                re.IGNORECASE,
                            )
                        ):
                            agent._followed_webcast_disclosures.add(disclosure_key)
                            if await continuation.is_visible():
                                await continuation.click(force=True)
                            elif "#webcast-popup-" in str(candidate_page.url):
                                # Some inline-dialog libraries only update
                                # the hash and leave the source template
                                # hidden. Opening the declared target is
                                # equivalent to the provider's _blank
                                # Continue handler and avoids a dead hash.
                                target_page = await candidate_page.context.new_page()
                                agent._attach_media_watchers(target_page)
                                await target_page.goto(
                                    webcast_url,
                                    wait_until="domcontentloaded",
                                    timeout=agent.page_ready_timeout_ms,
                                )
                                print(
                                    f"[{agent.ticker}] opened hidden webcast disclosure target",
                                    flush=True,
                                )
                            else:
                                agent._followed_webcast_disclosures.discard(disclosure_key)
                                continue
                            print(
                                f"[{agent.ticker}] followed webcast disclosure: "
                                f"{label[:80] or 'continue'}",
                                flush=True,
                            )
                            await asyncio.sleep(0.3)
                            continue
                except Exception:
                    pass

                # Some IR pages require affirmative acknowledgement of the
                # legal notice and provide only Accept/Agree plus Cancel.
                # Closing that modal leaves the event page unusable, while
                # accepting it is the provider's intended route onward.
                try:
                    legal_accept = frame.get_by_role(
                        "button",
                        name=re.compile(
                            r"^(?:accept|agree|i\s+accept|i\s+agree|continue)$",
                            re.IGNORECASE,
                        ),
                    ).first
                    if (
                        await legal_accept.count() > 0
                        and await legal_accept.is_visible()
                    ):
                        await legal_accept.click(force=True)
                        print(
                            f"[{agent.ticker}] accepted legal disclosure",
                            flush=True,
                        )
                        await asyncio.sleep(0.3)
                        continue
                except Exception:
                    pass

            if is_survey:
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
                        print(f"[{agent.ticker}] dismissed survey prompt", flush=True)
                        await asyncio.sleep(0.3)
                        continue
                except Exception:
                    pass

            for selector in (
                "[aria-label*='Close' i]",
                "button[title*='Close' i]",
                "button[class*='close' i]",
                "[role='button'][class*='close' i]",
                "[data-fancybox-close]:visible",
            ):
                try:
                    close_button = frame.locator(selector).first
                    if await close_button.count() > 0 and await close_button.is_visible():
                        await close_button.click(force=True)
                        if is_legal_overlay:
                            # Standard HTML dialogs do not expose the
                            # Fancybox API. Some IR pages leave the
                            # disclosure open after the button click, so
                            # close only dialogs whose text is the
                            # non-consent legal overlay we just detected.
                            try:
                                await frame.evaluate(
                                    """() => {
                                        for (const dialog of document.querySelectorAll('dialog[open]')) {
                                            const text = (dialog.innerText || dialog.textContent || '').toLowerCase();
                                            if (!/(forward-looking statements|non-gaap|legal disclaimer)/i.test(text)) {
                                                continue;
                                            }
                                            if (dialog.querySelector('[data-webcast-url]')) {
                                                continue;
                                            }
                                            if (typeof dialog.close === 'function') dialog.close();
                                            if (dialog.open) dialog.remove();
                                        }
                                    }"""
                                )
                            except Exception:
                                pass
                            # Fortive's page uses Fancybox 3.5 and its
                            # data attribute is present even when the
                            # delegated click handler is not attached in
                            # a delayed frame. Close through the provider
                            # API, then remove only the matching legal
                            # slide as a final DOM fallback.
                            try:
                                await frame.evaluate(
                                    """() => {
                                        if (window.jQuery && window.jQuery.fancybox) {
                                            window.jQuery.fancybox.close();
                                        }
                                    }"""
                                )
                            except Exception:
                                pass
                            try:
                                await frame.evaluate(
                                    """() => {
                                        for (const slide of document.querySelectorAll('.fancybox-slide')) {
                                            const text = (slide.innerText || '').toLowerCase();
                                            if (/(forward-looking statements|non-gaap|legal disclaimer)/i.test(text)) {
                                                slide.remove();
                                            }
                                        }
                                        document.body.classList.remove('fancybox-active');
                                    }"""
                                )
                            except Exception:
                                pass
                        message = "legal overlay" if is_legal_overlay else "survey prompt"
                        print(f"[{agent.ticker}] dismissed {message}", flush=True)
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue


async def _wait_for_clicked_target(
    agent,
    context: Any,
    *,
    source_page: Any,
    source_url: str,
    pages_before_click: tuple[Any, ...],
) -> Any:
    """Follow a click through popup creation and delayed provider redirects."""
    deadline = (
        asyncio.get_running_loop().time()
        + agent.target_navigation_timeout_seconds
    )
    target_page = source_page
    stable_signature: tuple[int, str] | None = None
    stable_count = 0

    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.5)
        await agent.accept_cookie_banners(source_page)

        open_pages = []
        for candidate in context.pages:
            try:
                if candidate.is_closed():
                    continue
            except Exception:
                pass
            if is_nonessential_popup_url(str(candidate.url)):
                continue
            agent._attach_media_watchers(candidate)
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
                agent._record_target_url(target_url)
                print(
                    f"[{agent.ticker}] click target stabilized: {target_url}",
                    flush=True,
                )
                return target_page

    print(
        f"[{agent.ticker}] click target settle timed out; "
        f"continuing with {target_page.url}",
        flush=True,
    )
    return target_page
