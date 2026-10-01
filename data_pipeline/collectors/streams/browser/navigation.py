"""Bounded IR navigation and read-only live link discovery.

Navigation never authenticates an event. A separately scoped, dated proof is
required before a discovered route can be promoted to registration/playback.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from data_pipeline.live_telemetry import emit_live_event
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse

from .rules import (
    WebcastDiscoveryResult, is_nonessential_popup_url,
    is_non_playback_surface_url, is_webcast_player_url,
)
from ...schedules.event_routes import (
    is_event_navigation as _shared_event_navigation, issuer_listing_fallbacks,
)
from ..webcast_learning import (
    WebcastCandidate, candidate_identity_mismatch, event_identity_text,
    live_event_identity_confirmation, non_primary_live_event_reason,
)


NAVIGATION_LABEL = re.compile(
    r"^(?:(?:investor\s+)?(?:events?|webcasts)(?:\s*(?:&|and)\s*presentations)?|"
    r"upcoming(?:\s+(?:events?|webcasts?))?|current(?:\s+events?)?|"
    r"(?:quarterly|financial)\s+results|earnings(?:\s+(?:results|calls))?|"
    r"event\s+calendar|all\s+events|investor\s+relations|"
    r"past(?:\s+(?:events?|webcasts?))?|today|"
    r"(?:previous|next)(?:\s+(?:events?|month|week|page))?)$", re.I,
)
NAVIGATION_PATH = re.compile(r"/(?:events?(?:-and-presentations)?|quarterly-results|financial-results)(?:/|$)", re.I)


def is_event_navigation(url: str, *labels: str) -> bool:
    """Share schedule route classification and recognize browser-only tabs."""
    clean_labels = [" ".join(str(value or "").split()) for value in labels]
    return bool(
        _shared_event_navigation(url)
        or any(_shared_event_navigation(url, label) or NAVIGATION_LABEL.fullmatch(label)
               for label in clean_labels if label)
    )


def official_listing_recovery_urls(start_url: str, current_url: str) -> tuple[str, ...]:
    """Recover only same-origin event-list ancestors, never guessed web URLs.

    A bare event-details path (or a stale deep detail) can be a saved IR URL.
    Its existing path hierarchy supplies a bounded fallback without external
    search. Navigating there conveys no event proof or playback permission.
    """
    start, current = urlparse(start_url), urlparse(current_url)
    if (start.scheme not in {"http", "https"} or current.scheme not in {"http", "https"}
            or not start.hostname or start.username or start.password
            or current.username or current.password
            or (start.scheme, start.netloc.lower()) != (current.scheme, current.netloc.lower())):
        return ()
    segments = [value for value in current.path.split("/") if value]
    if any(value in {".", ".."} or "%" in value for value in segments):
        return ()
    return tuple(issuer_listing_fallbacks(current_url))


def provider_event_id(url: str) -> str | None:
    """Known provider identifiers, never a guess based on a session token."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    query = dict(parse_qsl(parsed.query))
    if host in {"app.webinar.net", "webinar.net"}:
        match = re.fullmatch(r"/([A-Za-z0-9_-]{5,})(?:/(?:live|replay|register|registration))?/?", parsed.path)
        return f"webinar:{match.group(1)}" if match else None
    if host == "webcasts.com" or host.endswith(".webcasts.com"):
        return f"webcasts:{query['ei']}" if query.get("ei") else None
    if host == "on24.com" or host.endswith(".on24.com"):
        event = query.get("eventid") or query.get("eventId")
        path_event = re.fullmatch(r"/wcc/(?:r|eh|ehload)/(\d+)(?:/[^/]+)?/?", parsed.path)
        event = event or (path_event.group(1) if path_event else None)
        return f"on24:{event}" if event else None
    if host == "events.q4inc.com":
        # Q4 changes the same numeric event from registration to its guest
        # player with History API; no redirect request proves that transition.
        match = re.fullmatch(r"/attendee/(\d+)(?:/guest)?/?", parsed.path)
        return f"q4:{match.group(1)}" if match else None
    if host == "edge.media-server.com":
        # The Angular player canonicalizes this exact event path by adding
        # a slash with History API, without an HTTP redirect to observe.
        match = re.fullmatch(r"/mmc/p/([A-Za-z0-9_-]{5,})/?", parsed.path)
        return f"media-server:{match.group(1)}" if match else None
    return None


def same_event_route(expected: str, actual: str) -> bool:
    """Retain unknown/signed query semantics; only known event IDs generalize."""
    left, right = urlparse(expected), urlparse(actual)
    if left.scheme not in {"http", "https"} or right.scheme not in {"http", "https"}:
        return False
    if (left.hostname or "").lower() != (right.hostname or "").lower():
        return False
    left_id, right_id = provider_event_id(expected), provider_event_id(actual)
    if left_id or right_id:
        if any((identifier or "").startswith(("media-server:", "q4:"))
               for identifier in (left_id, right_id)):
            # Only documented path changes are equivalent. Signed/query values,
            # fragments and authority must not inherit a different route's
            # event proof merely because the public player hash matches.
            return bool(
                left_id and left_id == right_id
                and left.netloc.lower() == right.netloc.lower()
                and left.query == right.query
                and left.fragment == right.fragment
            )
        return bool(left_id and left_id == right_id)
    return urlunparse(left._replace(scheme=right.scheme)) == actual


def make_target_proof(agent, source_url: str, target_url: str, evidence: str,
                      *, transition_kind: str = 'selected_link') -> dict:
    previous = getattr(agent, 'live_target_proof', None)
    observed_at = datetime.now(timezone.utc).isoformat()
    result = {
        "verified": True,
        "call_ticker": agent.ticker,
        "target_date": agent.target_date.isoformat() if agent.target_date else None,
        "source_url": source_url,
        "target_url": target_url,
        "provider_event_id": provider_event_id(target_url),
        "target_kind": ('provider' if provider_event_id(target_url) or is_webcast_player_url(target_url)
                        else 'event_detail' if is_event_navigation(target_url) or re.search(
                            r'/(?:events?/[^?#]*|event-details?/[^?#]*)', urlparse(target_url).path, re.I)
                        else 'unknown'),
        "observed_at": observed_at,
        "evidence": evidence[:1200],
    }
    # A child control extends its selected parent event; it must not replace
    # the issuer source or refresh the age of the original issuer evidence.
    continues_parent = bool(proof_is_fresh(agent, previous) and (
        same_event_route(str(previous.get('target_url') or ''), source_url)
        or (previous.get('source_url') == source_url
            and same_event_route(str(previous.get('target_url') or ''), target_url))))
    if continues_parent:
        result.update(source_url=previous['source_url'],
                      source_observed_at=previous.get('source_observed_at') or previous['observed_at'])
        for key in ('call_id', 'schedule_revision'):
            if key in previous:
                result[key] = previous[key]
        lineage = list(previous.get('route_lineage') or [])
        if not same_event_route(str(previous['target_url']), target_url):
            lineage.append({'parent_target_url': previous['target_url'],
                            'target_url': target_url, 'observed_at': observed_at,
                            'kind': transition_kind})
        if len(lineage) <= 8:
            result['route_lineage'] = lineage
        else:
            # Do not truncate away the root that the scheduler must verify.
            return dict(previous)
    return result


def proof_is_fresh(agent, proof: dict | None) -> bool:
    if not isinstance(proof, dict):
        return False
    if proof.get("verified") is not True:
        return False
    if is_event_navigation(str(proof.get("target_url") or "")):
        return False
    if proof.get("call_ticker") != agent.ticker:
        return False
    if proof.get("target_date") != (agent.target_date.isoformat() if agent.target_date else None):
        return False
    try:
        now = datetime.now(timezone.utc)
        observed = datetime.fromisoformat(str(proof["observed_at"]))
        original = datetime.fromisoformat(str(proof.get('source_observed_at') or proof['observed_at']))
        ages = [(now - value).total_seconds() for value in (observed, original)]
    except (KeyError, ValueError, TypeError):
        return False
    return all(0 <= age <= max(60, int(os.getenv("WEBCAST_TARGET_PROOF_TTL_SECONDS", "21600"))) for age in ages)


async def validate_target_page(agent, page: Any) -> bool:
    """Validate route continuity; an undated provider shell is allowed by proof."""
    if agent.lifecycle != "live":
        return True
    proof = getattr(agent, "live_target_proof", None)
    if not proof_is_fresh(agent, proof):
        return False
    expected, actual = str(proof.get("target_url") or ""), str(page.url)
    if is_event_navigation(actual):
        return False
    # Event IDs explicitly contradicting each other may not inherit a redirect.
    expected_id, actual_id = provider_event_id(expected), provider_event_id(actual)
    if expected_id and actual_id and expected_id != actual_id:
        return False
    route_matches = same_event_route(expected, actual)
    chain = getattr(agent, "_live_redirect_edges", set())
    reachable = {expected}
    paths = {expected: []}
    for _ in range(8):
        expanded = {end for start, end in chain if start in reachable}
        for start, end in chain:
            if start in paths and end not in paths:
                paths[end] = paths[start] + [(start, end)]
        if expanded <= reachable:
            break
        reachable |= expanded
    route_matches = route_matches or actual in reachable
    if not route_matches:
        return False
    # Inspect event heading/local date, never unrelated dates in the whole body.
    try:
        heading = await page.locator("h1").first.inner_text(timeout=1000)
    except Exception:
        heading = ""
    if not heading:
        try:
            heading = await page.title()
        except Exception:
            pass
    if heading:
        if non_primary_live_event_reason(heading):
            return False
        candidate = WebcastCandidate(
            candidate_id="destination-heading", selectors=(), frame_hostname=None,
            text=event_identity_text(heading), aria_label="", title="",
            href_path=None, tag_name="h1", rect={},
        )
        if candidate_identity_mismatch(candidate, target_ticker=agent.ticker,
                                       target_date=agent.target_date):
            return False
    if not same_event_route(expected, actual):
        # A concrete navigation chain, not hostname similarity, advances the
        # proof consumed by registration, source observation and clock storage.
        for start, end in paths.get(actual, []):
            agent.live_target_proof = make_target_proof(agent, start, end,
                str(proof.get('evidence') or ''), transition_kind='observed_redirect')
    return True


def observe_redirect(agent, request: Any) -> None:
    try:
        previous = request.redirected_from
        if previous and request.is_navigation_request():
            agent._live_redirect_edges.add((str(previous.url), str(request.url)))
        elif request.is_navigation_request() and request.frame == request.frame.page.main_frame:
            # Issuers also use a JavaScript redirect/goto document. Record only
            # a navigation from the exact proven redirect endpoint to a known
            # event provider. Arbitrary links and unrelated frames add no edge.
            proof = getattr(agent, 'live_target_proof', None)
            source = str(request.frame.url)
            parsed = urlparse(source)
            if (proof_is_fresh(agent, proof)
                    and source == proof.get('target_url')
                    and re.search(r'/(?:redirect|redirect/goto)/?$', parsed.path, re.I)
                    and parsed.query and provider_event_id(str(request.url))):
                agent._live_redirect_edges.add((source, str(request.url)))
    except Exception:
        pass


async def begin_registration_transition(agent, page: Any) -> dict | None:
    """Observe a real form submission from the already verified event page."""
    if agent.lifecycle != "live" or not await validate_target_page(agent, page):
        return None
    try:
        actions = await page.locator("form").evaluate_all(
            "forms => forms.map(form => ({url: form.action || location.href,"
            "method: (form.method || 'get').toUpperCase()}))"
        )
    except Exception:
        actions = []
    state = {"page": page, "source_url": str(page.url), "actions": actions}
    def submitted(request):
        try:
            if not request.is_navigation_request() or request.frame != page.main_frame:
                return
            destination = urlparse(request.url)
            for action in actions:
                expected = urlparse(action["url"])
                if (
                    request.method == action["method"]
                    and (destination.scheme, destination.netloc, destination.path)
                    == (expected.scheme, expected.netloc, expected.path)
                ):
                    agent._live_redirect_edges.add((state["source_url"], str(request.url)))
        except Exception:
            pass
    state["listener"] = submitted
    page.on("request", submitted)
    return state


async def finish_registration_transition(agent, state: dict | None, target_page: Any,
                                         succeeded: bool) -> None:
    """Bind a successful same-provider JS transition or causally opened popup."""
    if state is None:
        return
    source_page = state["page"]
    try:
        source_page.remove_listener("request", state["listener"])
    except Exception:
        pass
    if not succeeded:
        return
    source, destination = state["source_url"], str(target_page.url)
    if source == destination or is_nonessential_popup_url(destination) or is_non_playback_surface_url(destination):
        return
    if re.search(r"(?:^|[/_.-])(?:survey|feedback|privacy|terms|subscribe)(?:[/_.?-]|$)",
                 urlparse(destination).path, re.I):
        return
    if provider_event_id(source) and provider_event_id(destination) and provider_event_id(source) != provider_event_id(destination):
        return
    # A POST to the declared action has already been joined to its redirect
    # chain. JS transitions must remain on this provider and in the submitted
    # page (or a popup whose opener is that exact page), never an arbitrary tab.
    if urlparse(source).hostname != urlparse(destination).hostname:
        return
    try:
        causally_opened = target_page is source_page or await target_page.opener() is source_page
    except Exception:
        causally_opened = target_page is source_page
    if causally_opened and state["actions"]:
        agent._live_redirect_edges.add((source, destination))


async def is_navigation_control(element: Any) -> bool:
    """Tabs/expanders are read-only discovery actions, not webcast controls."""
    try:
        if is_event_navigation(
            await element.get_attribute("href") or "", await element.inner_text(),
            await element.get_attribute("aria-label") or "",
            await element.get_attribute("title") or "",
        ):
            return True
        return await element.evaluate("""el => {
            const label = (el.innerText || el.getAttribute('aria-label') || '').trim();
            return !/play|watch|listen|register|join/i.test(label) &&
                (el.getAttribute('role') === 'tab' ||
                 el.hasAttribute('aria-expanded') || el.hasAttribute('aria-controls'));
        }""")
    except Exception:
        return False


async def _next_navigation(agent, page: Any, visited: set[str]) -> Any | None:
    origin_host = (urlparse(agent.ir_url).hostname or "").lower()
    candidates = await agent._collect_candidates(page)
    for candidate in candidates:
        label = next((value.strip() for value in (
            candidate.text, candidate.aria_label, candidate.title,
        ) if value.strip()), "")
        # Generic navigation is not an event assertion: dates from a surrounding
        # list must not stop opening Events. Dated detail shortcuts stay strict.
        if (not NAVIGATION_LABEL.fullmatch(label)
                and agent._live_candidate_identity_mismatch(candidate)):
            continue
        href = candidate.href
        if not href:
            for selector in candidate.selectors:
                match = re.fullmatch(r'a\[href=("(?:[^"\\]|\\.)*")\]', selector)
                if match:
                    href = urljoin(page.url, json.loads(match.group(1)))
                    break
        if href:
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != origin_host:
                continue
            if not (NAVIGATION_LABEL.fullmatch(label) or NAVIGATION_PATH.search(parsed.path)):
                continue
            key = href
        else:
            if not NAVIGATION_LABEL.fullmatch(label):
                continue
            key = f"{page.url}|{candidate.frame_hostname}|{candidate.selectors}"
        if key in visited:
            continue
        frames = [page.main_frame] if not candidate.frame_hostname else [
            frame for frame in page.frames
            if (urlparse(frame.url).hostname or "") == candidate.frame_hostname
        ]
        for frame in frames:
            for selector in candidate.selectors:
                try:
                    elements = await frame.locator(selector).element_handles()
                    for element in elements:
                        if not await element.is_visible():
                            continue
                        if href:
                            actual = await element.evaluate("el => el.href || ''")
                            if actual != href:
                                continue
                        # Explicitly exclude submit controls, even if mislabelled.
                        if await element.evaluate(
                            "el => !!el.closest('form') && "
                            "(el.type === 'submit' || el.type === 'image')"
                        ):
                            continue
                        visited.add(key)
                        return element
                except Exception:
                    continue
    return None


async def _goto_discovery_page(agent, page: Any, destination: str, *, timeout: int) -> None:
    """Associate the access decision with this navigation's main response."""
    agent._page_http_status = None
    response = await page.goto(destination, wait_until="domcontentloaded", timeout=timeout)
    agent._page_http_status = response.status if response is not None else None


async def find_live_target(agent, page: Any) -> tuple[Any | None, Any]:
    """Bounded navigation before the existing strict candidate selector."""
    visited: set[str] = set()
    rendered_retry: set[str] = set()
    recovery_visited: set[str] = set()
    agent._live_navigation_barrier = None
    limit = max(0, min(8, int(os.getenv("WEBCAST_LIVE_NAVIGATION_STEPS", "4"))))
    for step in range(limit + 1):
        barrier = await agent._detect_access_barrier(page)
        if barrier:
            agent._live_navigation_barrier = barrier
            emit_live_event("discovery", "navigation_blocked", status="access_denied",
                            ticker=agent.ticker, url=str(page.url), barrier=barrier)
            return None, page
        emit_live_event("discovery", "page_scan", status="scanning", ticker=agent.ticker,
                        url=str(page.url), navigation_step=step)
        target = await agent.find_webcast_button(page)
        if target and not await is_navigation_control(target):
            return target, page
        if step == limit:
            break
        navigation = target or await _next_navigation(agent, page, visited)
        if navigation is None:
            # Client-rendered lists can appear after DOMContentLoaded without
            # any loading label. Give each page one bounded rescan before the
            # scheduler takes over; repeatedly reloading too early can miss it
            # forever even though the external event is already published.
            page_key = str(page.url)
            if page_key not in rendered_retry:
                rendered_retry.add(page_key)
                await asyncio.sleep(max(0, min(3, float(os.getenv(
                    "WEBCAST_LIVE_RENDER_GRACE_SECONDS", "2",
                )))))
                continue
            recovery = next((url for url in official_listing_recovery_urls(
                agent.ir_url, str(page.url),
            ) if url not in recovery_visited and url not in visited), None)
            if recovery:
                recovery_visited.add(recovery)
                visited.add(recovery)
                agent._reset_live_target_identity_confirmation()
                emit_live_event("discovery", "listing_recovery_started", status="opening_page",
                                ticker=agent.ticker, destination=recovery,
                                reason="event_detail_exhausted", navigation_step=step)
                try:
                    await _goto_discovery_page(agent, page, recovery, timeout=8000)
                    await agent.accept_cookie_banners(page)
                except Exception as exc:
                    emit_live_event("discovery", "listing_recovery_failed", status="navigation_retry",
                                    ticker=agent.ticker, destination=recovery,
                                    error_type=type(exc).__name__)
                continue
            break
        if target:
            key = await target.evaluate("el => location.href + '|' + el.outerHTML.slice(0,600)")
            if key in visited:
                break
            visited.add(key)
            # Expanding the event row cannot authorize later unrelated links.
            agent._reset_live_target_identity_confirmation()
        try:
            href = await navigation.get_attribute("href")
            if href and not href.startswith("#"):
                destination = urljoin(page.url, href)
                if (
                    urlparse(destination).scheme not in {"http", "https"}
                    or urlparse(destination).hostname != urlparse(agent.ir_url).hostname
                ):
                    break
                emit_live_event("discovery", "navigation_started", status="opening_page",
                                ticker=agent.ticker, destination=destination)
                await _goto_discovery_page(agent, page, destination, timeout=8000)
            else:
                await navigation.click(timeout=3000)
            emit_live_event("discovery", "navigation_completed", status="page_loaded", progress=True,
                            ticker=agent.ticker, url=str(page.url), navigation_step=step)
            await asyncio.sleep(0.25)
            await agent.accept_cookie_banners(page)
        except Exception:
            continue
    return None, page


async def run_discovery_only(agent) -> WebcastDiscoveryResult:
    """Discover a dated route without launching audio, registration or STT."""
    result = WebcastDiscoveryResult(
        ticker=agent.ticker, ir_url=agent.ir_url, success=False, clicked_text=None,
        final_url=None, playback_triggered=False, media_candidates=[],
        discovery_only=True, retry_state="target_not_found",
    )
    emit_live_event("discovery", "discovery_started", status="opening_page", ticker=agent.ticker,
                    url=agent.direct_target_url or agent.ir_url)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            options = {"headless": agent.headless, "args": ["--disable-http2"]}
            if agent.executable_path:
                options["executable_path"] = agent.executable_path
            browser = await playwright.chromium.launch(**options)
            context = None
            try:
                context = await browser.new_context(**agent._context_options())
                # Block media requests: discovery must not trigger capture or an
                # auto-playing provider advertisement as a side effect.
                await context.route("**/*", lambda route: (
                    route.abort() if route.request.resource_type == "media"
                    else route.continue_()
                ))
                context.on("request", lambda request: observe_redirect(agent, request))
                page = await context.new_page()
                await _goto_discovery_page(agent, page, agent.direct_target_url or agent.ir_url,
                                           timeout=15000)
                emit_live_event("discovery", "page_loaded", status="inspecting_page", progress=True,
                                ticker=agent.ticker, url=str(page.url))
                await agent.accept_cookie_banners(page)
                barrier = await agent._detect_access_barrier(page)
                if barrier:
                    result.error = f"ACCESS_BLOCKED {barrier}"
                    result.retry_state = "access_denied"
                    return result
                if await validate_target_page(agent, page):
                    target_url = str(page.url)
                else:
                    element, page = await find_live_target(agent, page)
                    if element is None:
                        navigation_barrier = getattr(agent, "_live_navigation_barrier", None)
                        if navigation_barrier:
                            result.error = f"ACCESS_BLOCKED {navigation_barrier}"
                            result.retry_state = "access_denied"
                        else:
                            result.error = "LIVE_TARGET_UNCONFIRMED no dated target candidate"
                        return result
                    href = await element.get_attribute("href")
                    if not href:
                        # A JS-only launch remains a heavy probe; avoid clicking
                        # what may itself start playback in lightweight discovery.
                        result.error = "DISCOVERY_REQUIRES_BROWSER_ACTION target has no URL"
                        result.retry_state = "browser_action_required"
                        return result
                    target_url = await element.evaluate("el => el.href")
                    if urlparse(target_url).scheme not in {"http", "https"}:
                        result.error = "LIVE_TARGET_UNCONFIRMED invalid target scheme"
                        return result
                proof = getattr(agent, "live_target_proof", None)
                if not proof_is_fresh(agent, proof):
                    result.error = "LIVE_TARGET_UNCONFIRMED target proof missing"
                    return result
                result.success = True
                result.discovered_url = target_url
                result.final_url = str(page.url)
                result.target_identity_verified = True
                result.event_identity = proof
                result.retry_state = "target_found"
                return result
            finally:
                result.schedule_observation = getattr(agent, 'schedule_observation', None)
                from .diagnostics import capture_diagnostics
                artifact = await capture_diagnostics(agent, context, "discovery_found" if result.success else "discovery_failed")
                emit_live_event("discovery", "discovery_completed", status=result.retry_state,
                                progress=bool(result.success), ticker=agent.ticker,
                                error=result.error, destination=result.discovered_url,
                                artifact_path=artifact,
                                **getattr(agent, "_last_candidate_inventory", {}))
                await browser.close()
    except Exception as exc:
        result.error = f"DISCOVERY_TRANSIENT_ERROR {type(exc).__name__}: {str(exc)[:180]}"
        result.retry_state = "transient_network"
        emit_live_event("discovery", "discovery_exception", status="transient_network",
                        ticker=agent.ticker, error=result.error)
        return result
