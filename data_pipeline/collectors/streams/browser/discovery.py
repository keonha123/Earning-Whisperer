"""Webcast candidates, archives and pagination."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse
from . import learning
from data_pipeline.live_telemetry import emit_live_event
from ..webcast_learning import event_identity_text
from .rules import (
    EARNINGS_EVENT_CONTEXT_PATTERN,
    NEWS_ARTICLE_PATH_PATTERN,
    NON_PLAYBACK_DOCUMENT_PATTERN,
    REPLAY_ARCHIVE_NAVIGATION_LABELS,
    REPLAY_ARCHIVE_PRESENTATIONS_PATH_PATTERN,
    REPLAY_ARCHIVE_VIEW_PATTERN,
    REPLAY_EXPANSION_LABEL_PATTERN,
    REPLAY_LOGIN_PATH_PATTERN,
    REPLAY_PROXY_DOCUMENT_PATTERN,
    REGISTRATION_SENSITIVE_QUERY_KEYS,
    WebcastCandidate,
    archive_navigation_url,
    choose_replay_training_candidate,
    choose_replay_training_surface_candidate,
    domain_for_url,
    event_date_from_text,
    is_direct_player_url,
    is_event_specific_replay_recipe,
    is_media_candidate_url,
    is_news_article_without_playback_label,
    is_non_playback_home_url,
    is_non_playback_product_surface_url,
    is_non_playback_surface_url,
    is_non_replay_navigation_link,
    is_playback_control_label,
    is_replay_proxy_link,
    is_replay_training_candidate,
    is_webcast_player_url,
    make_recipe,
    provider_archive_navigation_url,
    replay_candidate_rejection_reason,
    replay_page_number,
)


async def _diagnostic_destination(locator: Any) -> str | None:
    try:
        return await locator.get_attribute("href")
    except Exception:
        return None


async def find_webcast_button(agent, page: Any) -> Any | None:
    """Reuse an audio-verified recipe, or learn one from a visual/DOM snapshot."""
    print(f"[{agent.ticker}] inspecting page for webcast controls: {page.url}", flush=True)
    # Some consent managers render after the initial DOM-ready check and
    # otherwise leave a transparent overlay over the event cards.
    await agent.accept_cookie_banners(page)
    verified_recipes = agent._load_verified_recipes(page.url)
    if agent.lifecycle == "replay":
        current_replay_recipes = [
            recipe
            for recipe in verified_recipes
            if not is_event_specific_replay_recipe(recipe)
        ]
        skipped_count = len(verified_recipes) - len(current_replay_recipes)
        if skipped_count:
            print(
                f"[{agent.ticker}] skipping {skipped_count} event-specific replay "
                "recipe(s); selecting the newest current archive candidate",
                flush=True,
            )
        verified_recipes = current_replay_recipes

    for recipe in verified_recipes:
        live_confirmation = None
        if agent._live_target_confirmation_required():
            candidate_value = (recipe.evidence or {}).get("candidate", {})
            try:
                recipe_candidate = WebcastCandidate.from_dict(candidate_value)
            except (KeyError, TypeError, ValueError):
                recipe_candidate = None
            live_confirmation = (
                agent._live_candidate_identity_confirmation(recipe_candidate)
                if recipe_candidate
                else None
            )
            if not live_confirmation:
                print(
                    f"[{agent.ticker}] skipping unconfirmed live recipe "
                    f"id={recipe.recipe_id}",
                    flush=True,
                )
                continue
        button = await agent._find_recipe_button(page, recipe)
        if (
            button
            and not await agent._replay_candidate_rejection(button, page.url)
            and not await agent._is_live_excluded_locator(button, page.url)
        ):
            # _find_recipe_button revalidated the pinned node and persisted its
            # actual local title/date. Do not replace that evidence with the
            # saved recipe's generic identity verdict.
            agent._active_recipe = recipe
            agent._recipe_origin = "verified"
            emit_live_event("discovery", "candidate_selected", status="target_selected", progress=True,
                            ticker=agent.ticker, strategy="verified_recipe", recipe_id=recipe.recipe_id,
                            destination=await _diagnostic_destination(button))
            print(f"[{agent.ticker}] using verified recipe id={recipe.recipe_id}", flush=True)
            return button

    embedded_link = await agent._find_embedded_playback_link(page)
    if embedded_link:
        emit_live_event("discovery", "candidate_selected", status="target_selected", progress=True,
                        ticker=agent.ticker, strategy="embedded_link",
                        destination=await _diagnostic_destination(embedded_link))
        print(f"[{agent.ticker}] found embedded webcast link from surrounding document text", flush=True)
        return embedded_link

    snapshot = await agent._capture_learning_snapshot(page)
    agent._learning_snapshot = snapshot
    candidate, strategy, confidence, reason = await agent._choose_learning_candidate(page, snapshot)
    if not candidate and await agent._expand_replay_event_rows(page):
        print(
            f"[{agent.ticker}] replay event row expanded; rescanning webcast controls",
            flush=True,
        )
        snapshot = await agent._capture_learning_snapshot(page)
        agent._learning_snapshot = snapshot
        candidate, strategy, confidence, reason = await agent._choose_learning_candidate(
            page,
            snapshot,
        )
    if not candidate:
        emit_live_event("discovery", "selection_empty", status=("no_ranked_candidate" if getattr(agent, "_last_candidate_inventory", {}).get("eligible_count") else "no_eligible_candidate"),
                        ticker=agent.ticker, page_url=str(page.url),
                        **getattr(agent, "_last_candidate_inventory", {}))
        return None

    # A stale/excluded/ambiguous top locator must not discard the other dated
    # candidates on the same page. Each snapshot candidate is considered once.
    rejected_ids: set[str] = set()
    max_attempts = max(1, min(12, int(os.getenv("WEBCAST_CANDIDATE_SELECTION_ATTEMPTS", "8"))))
    for _ in range(max_attempts):
        if candidate is None or candidate.candidate_id in rejected_ids:
            break
        recipe = make_recipe(
            page.url, candidate, strategy=strategy, lifecycle=agent.lifecycle,
            confidence=confidence, snapshot=snapshot, vision_reason=reason,
        )
        agent._active_recipe = recipe
        agent._recipe_origin = "learned"
        button = await agent._find_recipe_button(page, recipe)
        rejection = None
        if button is None:
            rejection = "locator_stale_or_ambiguous"
        elif await agent._is_live_excluded_locator(button, page.url):
            rejection = "excluded_event"
        elif (await agent._replay_candidate_rejection(button, page.url)
              and recipe.strategy not in {"replay-training-surface-fallback", "replay-training-hidden-fallback"}):
            rejection = "replay_candidate_rejected"
        if rejection is None:
            recipe.recipe_id = agent._save_recipe(recipe)
            emit_live_event("discovery", "candidate_selected", status="target_selected",
                            progress=True, ticker=agent.ticker,
                            candidate_id=candidate.candidate_id, destination=candidate.href,
                            strategy=strategy, confidence=confidence)
            print(f"[{agent.ticker}] learned {strategy} recipe "
                  f"candidate={candidate.candidate_id} confidence={confidence:.2f}", flush=True)
            return button
        emit_live_event("discovery", "candidate_rejected", status=rejection,
                        ticker=agent.ticker, candidate_id=candidate.candidate_id,
                        destination=candidate.href, next_action="rank_next_candidate")
        rejected_ids.add(candidate.candidate_id)
        agent._active_recipe = None
        agent._recipe_origin = None
        agent._reset_live_target_identity_confirmation()
        remaining = type(snapshot)(
            screenshot_path=snapshot.screenshot_path, candidates_path=snapshot.candidates_path,
            candidates=tuple(item for item in snapshot.candidates if item.candidate_id not in rejected_ids),
        )
        previous_retry = getattr(agent, "_selection_retry", False)
        agent._selection_retry = True
        try:
            candidate, strategy, confidence, reason = await agent._choose_learning_candidate(page, remaining)
        finally:
            agent._selection_retry = previous_retry
    emit_live_event("discovery", "candidate_selection_exhausted", status="no_usable_candidate",
                    ticker=agent.ticker, rejected_count=len(rejected_ids),
                    candidate_count=len(snapshot.candidates))
    return None


def _is_live_excluded_url(agent, value: str | None, base_url: str | None = None) -> bool:
    """Exclude the same event, preserving query/fragment event identifiers."""
    if agent.lifecycle != "live" or not agent.live_excluded_urls or not value:
        return False
    resolved = urljoin(base_url or "", str(value).strip())
    resolved_parts = urlparse(resolved)
    if not resolved_parts.netloc or not resolved_parts.path:
        return False
    resolved_path = resolved_parts.path.rstrip("/") or "/"
    def event_query(parts):
        return sorted(
            (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in REGISTRATION_SENSITIVE_QUERY_KEYS
        )
    for excluded in agent.live_excluded_urls:
        excluded_parts = urlparse(excluded)
        if not excluded_parts.netloc:
            continue
        excluded_path = excluded_parts.path.rstrip("/") or "/"
        if (
            resolved_parts.scheme == excluded_parts.scheme
            and resolved_parts.netloc.lower() == excluded_parts.netloc.lower()
            and resolved_path == excluded_path
            and event_query(resolved_parts) == event_query(excluded_parts)
            and resolved_parts.fragment == excluded_parts.fragment
        ):
            return True
    return False


async def _is_live_excluded_locator(agent, locator: Any, page_url: str) -> bool:
    """Check the complete destination, including the provider's event ID."""
    try:
        href = (await locator.get_attribute("href") or "").strip()
    except Exception:
        return False
    return agent._is_live_excluded_url(href, page_url)


async def _find_embedded_playback_link(agent, page: Any) -> Any | None:
    """Find icon-only webcast anchors whose label lives in a sibling document span."""
    matches: list[tuple[int, int, int, str | None, Any]] = []
    sequence = 0
    replay_proxy_mode = agent._replay_training_proxy_mode()
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
                explicit_playback_label = bool(
                    re.search(
                        r"\b(?:listen|webcast|audio|replay|play|watch)\b",
                        link_label,
                        re.IGNORECASE,
                    )
                )
                type_hint = (await link.get_attribute("type") or "").strip()
                if not visible and not icon_visible and not explicit_playback_label:
                    continue
                if not icon_visible and not explicit_playback_label:
                    continue
                frame_base_url = frame.url if urlparse(frame.url).scheme in {"http", "https"} else page.url
                resolved_href = urljoin(frame_base_url, href)
                if agent.lifecycle == "live":
                    from .navigation import is_event_navigation
                    if is_event_navigation(resolved_href, link_label):
                        continue
                if resolved_href.rstrip("/") == str(page.url).rstrip("/"):
                    continue
                if agent._is_live_excluded_url(resolved_href, frame_base_url):
                    print(
                        f"[{agent.ticker}] skipping previously failed live target: "
                        f"{resolved_href}",
                        flush=True,
                    )
                    continue
                if is_non_playback_surface_url(resolved_href):
                    print(
                        f"[{agent.ticker}] skipping non-playback surface link: "
                        f"{resolved_href}",
                        flush=True,
                    )
                    continue
                if is_non_playback_product_surface_url(resolved_href, link_label):
                    print(
                        f"[{agent.ticker}] skipping product navigation link: "
                        f"{resolved_href}",
                        flush=True,
                    )
                    continue
                if is_non_playback_home_url(resolved_href, link_label):
                    print(
                        f"[{agent.ticker}] skipping homepage navigation link: "
                        f"{resolved_href}",
                        flush=True,
                    )
                    continue
                proxy_link = is_replay_proxy_link(
                    resolved_href,
                    link_label,
                    type_hint=type_hint,
                    icon_control=icon_visible,
                )
                if replay_proxy_mode and not proxy_link:
                    print(
                        f"[{agent.ticker}] skipping non-playable replay proxy link: "
                        f"{resolved_href}",
                        flush=True,
                    )
                    continue
                if NON_PLAYBACK_DOCUMENT_PATTERN.search(resolved_href):
                    continue
                if type_hint.lower() == "application/pdf":
                    continue
                evidence = await link.evaluate(
                    """element => {
                        const compact = value => (value || '').replace(/\\s+/g, ' ').trim();
                        let container = element;
                        let fallback = element.parentElement || element;
                        for (let depth = 0; container && depth < 8; depth += 1, container = container.parentElement) {
                            const text = compact(container.innerText || container.textContent);
                            if (text.length >= 20 && text.length <= 1800 &&
                                /(?:earnings|conference call|webcast|financial results|q[1-4].{0,30}results)/i.test(text) &&
                                /(?:20\\d{2}|January|February|March|April|May|June|July|August|September|October|November|December)/i.test(text)) {
                                fallback = container;
                                break;
                            }
                        }
                        return [
                            element.innerText,
                            element.getAttribute('aria-label'),
                            element.getAttribute('title'),
                            fallback.innerText,
                        ].filter(Boolean).join(' ');
                    }"""
                )
                if agent.lifecycle == "live":
                    # Apply the same card boundary and event-type checks as
                    # ranked discovery, including icon-only Webcast links.
                    from ..webcast_learning import candidate_event_evidence
                    current = await learning._live_element_candidate(link)
                    if agent._live_candidate_identity_mismatch(current):
                        continue
                    evidence = candidate_event_evidence(current)
                if (
                    re.search(r"\.(?:m4a|mp3|aac|wav)(?:$|[?#])", resolved_href, re.IGNORECASE)
                    and REPLAY_PROXY_DOCUMENT_PATTERN.search(evidence or "")
                    and not re.search(
                        r"\b(?:listen|replay|on[-\s]?demand|audio\s+recording|stream)\b",
                        link_label,
                        re.IGNORECASE,
                    )
                ):
                    print(
                        f"[{agent.ticker}] skipping document audio candidate: "
                        f"{resolved_href}",
                        flush=True,
                    )
                    continue
                if not replay_proxy_mode and not re.search(
                    r"\b(?:listen|webcast|audio|replay|play|watch)\b",
                    evidence or "",
                    re.IGNORECASE,
                ):
                    continue
                generic_label = " ".join(link_label.split())
                if (
                    re.fullmatch(
                        r"(?:watch|play|listen|view(?:\s+now)?)(?:\s+"
                        r"(?:watch|play|listen|view(?:\s+now)?))*",
                        generic_label,
                        re.IGNORECASE,
                    )
                    and not re.search(
                        r"\b(?:webcast|replay|audio|earnings|quarter(?:ly)?|"
                        r"financial\s+results|conference|presentation|event|"
                        r"call)\b",
                        evidence or "",
                        re.IGNORECASE,
                    )
                ):
                    continue
                if replay_proxy_mode or is_playback_control_label(evidence):
                    rejection = (
                        replay_candidate_rejection_reason(
                            evidence or "",
                            resolved_href,
                            minimum_age_days=agent._replay_minimum_age_days(),
                        )
                        if agent.lifecycle == "replay"
                        else None
                    )
                    if rejection:
                        print(
                            f"[{agent.ticker}] skipping embedded replay candidate: "
                            f"{rejection}",
                            flush=True,
                        )
                        continue
                    event_date = event_date_from_text(event_identity_text(
                        f"{evidence or ''} {resolved_href}"
                    ))
                    if (
                        agent.lifecycle == "live"
                        and agent.target_date
                        and event_date
                        and event_date != agent.target_date
                    ):
                        continue
                    live_confirmation = None
                    if agent._live_target_confirmation_required():
                        live_confirmation = agent._live_evidence_identity_confirmation(
                            f"{evidence or ''} {resolved_href}"
                        )
                        if not live_confirmation:
                            print(
                                f"[{agent.ticker}] skipping undated live playback link: "
                                f"{resolved_href}",
                                flush=True,
                            )
                            continue
                    score = 0
                    if is_media_candidate_url(resolved_href):
                        score += 100
                    if is_webcast_player_url(resolved_href):
                        score += 90
                    if re.search(
                        r"\b(?:webcast|replay|watch|listen|audio|video|play)\b",
                        link_label,
                        re.IGNORECASE,
                    ):
                        score += 70
                    if type_hint.lower().startswith(("audio/", "video/")):
                        score += 50
                    if icon_visible:
                        score += 20
                    # Virtualized IR pages often keep a hidden duplicate
                    # of the same webcast anchor in the DOM. Prefer the
                    # visible copy so the downstream click/href fallback
                    # does not bind to an off-screen stale row.
                    if visible:
                        score += 25
                    pinned_link = await link.element_handle()
                    if pinned_link is None or (await pinned_link.get_attribute("href") or "").strip() != href:
                        continue
                    if live_confirmation:
                        live_confirmation = await learning._live_element_confirmation(agent, pinned_link)
                        if not live_confirmation:
                            continue
                    matches.append(
                        (
                            score,
                            event_date.toordinal() if event_date else 0,
                            -sequence,
                            live_confirmation,
                            pinned_link,
                        )
                    )
                    sequence += 1
            except Exception:
                continue
    if not matches:
        return None
    matches.sort(key=lambda item: item[:3], reverse=True)
    live_confirmation = matches[0][3]
    if (not live_confirmation and agent.lifecycle == "live"
            and hasattr(agent, "_validate_live_target_page")
            and await agent._validate_live_target_page(page)):
        live_confirmation = agent.live_target_identity_evidence or "linked from confirmed event"
    if live_confirmation:
        chosen = matches[0][4]
        destination = await chosen.evaluate("el => el.href")
        agent._mark_live_target_identity_confirmed(
            live_confirmation, source_url=str(page.url), target_url=destination,
        )
    return matches[0][4]


def _replay_minimum_age_days(agent) -> int:
    # Replay training is deliberately allowed to use the newest archived
    # event. Live monitoring still keeps the conservative default so a
    # scheduled event is not mistaken for an available replay.
    default_days = 0 if agent._replay_training_proxy_mode() else 2
    try:
        return max(
            0,
            int(os.getenv("WEBCAST_REPLAY_MINIMUM_AGE_DAYS", str(default_days))),
        )
    except ValueError:
        return default_days


async def _replay_candidate_rejection(
    agent,
    locator: Any,
    page_url: str,
) -> str | None:
    if agent.lifecycle != "replay":
        return None
    try:
        href = (await locator.get_attribute("href") or "").strip()
        label = " ".join(
            value.strip()
            for value in (
                await locator.inner_text(),
                await locator.get_attribute("aria-label"),
                await locator.get_attribute("title"),
            )
            if value and value.strip()
        )
        resolved_href = urljoin(page_url, href) if href else ""
        if resolved_href and NON_PLAYBACK_DOCUMENT_PATTERN.search(resolved_href):
            return "verified replay recipe points to a non-playback document"
        if (
            re.search(
                r"\b(?:pdf|document|prepared\s+remarks|transcript|slides?)\b|"
                r"link\s+opens\s+in\s+new\s+window",
                label,
                re.IGNORECASE,
            )
            and resolved_href
            and not is_media_candidate_url(resolved_href)
            and not is_webcast_player_url(resolved_href)
        ):
            return "verified replay recipe points to a labeled document"
        if resolved_href:
            parsed_href = urlparse(resolved_href)
            host = (parsed_href.hostname or "").lower()
            if (
                (host == "youtube.com" or host.endswith(".youtube.com") or host.endswith("youtu.be"))
                and not is_direct_player_url(resolved_href)
            ):
                return "verified replay recipe points to a YouTube channel or home page"
            if is_non_playback_surface_url(resolved_href):
                return "verified replay recipe points to an app store or software catalog"
            if is_non_playback_product_surface_url(resolved_href, label):
                return "verified replay recipe points to a product catalog"
            if is_non_playback_home_url(resolved_href, label):
                return "verified replay recipe points to a company homepage"
            if is_non_replay_navigation_link(resolved_href, label):
                return "verified replay recipe points to navigation or a tracking redirect"
            if label.casefold() in REPLAY_ARCHIVE_NAVIGATION_LABELS:
                return "verified replay recipe points to archive navigation"
            if (
                REPLAY_ARCHIVE_PRESENTATIONS_PATH_PATTERN.search(parsed_href.path)
                and not is_media_candidate_url(resolved_href)
                and not is_playback_control_label(label)
            ):
                return "verified replay recipe points to archive navigation"
            if (
                host.endswith("choruscall.com")
                and parsed_href.path.lower().rstrip("/").endswith("/mediaframe/webcast.html")
                and not is_webcast_player_url(resolved_href)
            ):
                return "verified replay recipe points to ChorusCall without a webcast identifier"
            if (
                NEWS_ARTICLE_PATH_PATTERN.search(parsed_href.path)
                and is_news_article_without_playback_label(label, parsed_href.path)
            ):
                return "verified replay recipe points to a news article without a playback label"
        elif label.casefold() in REPLAY_ARCHIVE_NAVIGATION_LABELS:
            # Some archived-event tabs are rendered as buttons or JS links
            # without an href. They are navigation controls, never replay
            # targets, and must not shadow a dated event-detail link.
            return "verified replay recipe points to archive navigation"
        # A previous exploratory pass can save an event-row utility button
        # whose DOM box is clickable but has no target or playback label.
        # Reusing it prevents the current page's real Webcast link from
        # being inspected. Keep direct-target icon controls valid.
        if (
            not href
            and not await locator.get_attribute("onclick")
            and not is_playback_control_label(label)
        ):
            return "verified replay recipe has no target or playback label"
        evidence = await locator.evaluate(
            """element => {
                let current = element;
                let fallback = '';
                for (let depth = 0; current && depth < 8; depth += 1, current = current.parentElement) {
                    const text = (current.innerText || current.textContent || '')
                        .replace(/\\s+/g, ' ').trim();
                    if (!fallback && text.length >= 10 && text.length <= 1800) fallback = text;
                    if (text.length >= 20 && text.length <= 1800 &&
                        /(?:earnings|conference call|webcast|financial results|q[1-4].{0,30}results)/i.test(text) &&
                        /(?:20\\d{2}|January|February|March|April|May|June|July|August|September|October|November|December)/i.test(text)) {
                        return text;
                    }
                }
                return fallback || [
                    element.innerText,
                    element.getAttribute('aria-label'),
                    element.getAttribute('title'),
                ].filter(Boolean).join(' ');
            }"""
        )
        rejection = replay_candidate_rejection_reason(
            evidence or "",
            resolved_href or None,
            minimum_age_days=agent._replay_minimum_age_days(),
        )
        if rejection:
            print(
                f"[{agent.ticker}] skipping verified replay candidate: {rejection}",
                flush=True,
            )
        return rejection
    except Exception:
        return None


async def _find_replay_event_detail_link(agent, page: Any) -> Any | None:
    """Find a dated event-detail link when the archive hides its webcast link."""
    if agent.lifecycle != "replay":
        return None
    snapshot = agent._learning_snapshot or await agent._capture_learning_snapshot(page)
    detail_pattern = re.compile(
        r"/(?:events?|event-details?)/(?:detail/)?|"
        r"/(?:ir[-/]calendar|calendar[-/]of[-/]events)/detail(?:/|$)",
        re.IGNORECASE,
    )
    eligible: list[tuple[date, WebcastCandidate]] = []
    for candidate in snapshot.candidates:
        if candidate.tag_name != "a" or not candidate.href_path:
            continue
        href = str(candidate.href_path)
        label = " ".join(
            value
            for value in (candidate.text, candidate.aria_label, candidate.title)
            if value
        )
        evidence = " ".join(
            value for value in (label, candidate.context_text, href) if value
        )
        if not detail_pattern.search(href) or not is_replay_training_candidate(
            candidate,
            minimum_age_days=agent._replay_minimum_age_days(),
        ):
            continue
        event_date = event_date_from_text(evidence) or date.min
        eligible.append((event_date, candidate))
    if not eligible:
        return None
    eligible.sort(key=lambda item: item[0], reverse=True)
    candidate = eligible[0][1]
    for frame in page.frames:
        try:
            locator = frame.locator(
                f"a[href*={json.dumps(candidate.href_path)}]"
            ).first
            if await locator.count() > 0 and await locator.is_visible():
                print(
                    f"[{agent.ticker}] opening replay event detail: "
                    f"{' '.join(candidate.text.split())[:120]}",
                    flush=True,
                )
                return locator
        except Exception:
            continue
    return None


async def find_webcast_button_with_archive_fallback(agent, page: Any) -> tuple[Any | None, Any]:
    """Try the supplied IR page, then one same-site recording archive when present."""
    # A human/workflow may already have moved from the archive into the
    # provider's registration page. Return control to the registration
    # dispatcher instead of treating its submit button as a webcast link.
    if await agent.has_registration_form(page):
        return None, page
    if agent.lifecycle == "live":
        from .navigation import find_live_target
        return await find_live_target(agent, page)
    if agent.lifecycle == "replay":
        await agent._prepare_replay_history(page)
    else:
        await agent._activate_replay_archive_view(page)
    button = await agent.find_webcast_button(page)
    if button:
        if await agent._replay_candidate_rejection(button, page.url):
            button = None
        else:
            return button, page

    detail_link = await agent._find_replay_event_detail_link(page)
    if detail_link:
        return detail_link, page

    snapshot = agent._learning_snapshot
    archive_url = (
        archive_navigation_url(page.url, snapshot.candidates)
        if snapshot
        else None
    )
    if not archive_url:
        archive_url = provider_archive_navigation_url(page.url)
    if not archive_url or archive_url == page.url:
        if agent._replay_training_proxy_mode():
            fallback_button, fallback_page = await agent._try_replay_training_surface_links(page)
            if fallback_button or fallback_page is not page:
                return fallback_button, fallback_page
        for _ in range(agent.human_retry_limit):
            if not await agent._human_handoff(
                page,
                stage="candidate",
                reason="자동 탐색에서 재생 후보를 찾지 못했습니다.",
            ):
                break
            page = agent._page_after_human_handoff(page)
            await agent._wait_for_dynamic_page(page)
            if await agent.has_registration_form(page):
                return None, page
            button = await agent.find_webcast_button(page)
            if button:
                if await agent._replay_candidate_rejection(button, page.url):
                    button = None
                else:
                    return button, page
        return None, page

    print(f"[{agent.ticker}] no playback control; opening archive fallback: {archive_url}", flush=True)
    try:
        agent._record_target_url(archive_url)
        # Archive pages often keep analytics/media requests open after their
        # interactive DOM is ready, so waiting for the full load event stalls
        # playback discovery unnecessarily.
        response = await page.goto(
            archive_url,
            wait_until="domcontentloaded",
            timeout=agent.page_ready_timeout_ms,
        )
        agent._page_http_status = response.status if response else None
        await asyncio.sleep(2)
        await agent.accept_cookie_banners(page)
        agent._page_barrier = await agent._detect_access_barrier(page)
        if agent._page_barrier:
            for _ in range(agent.human_retry_limit):
                if not agent._page_barrier:
                    break
                if not await agent._human_handoff(
                    page,
                    stage="access",
                    reason=f"아카이브 페이지 접근이 막혔습니다: {agent._page_barrier}",
                ):
                    break
                page = agent._page_after_human_handoff(page)
                agent._page_barrier = await agent._detect_access_barrier(page)
                if not agent._page_barrier:
                    button = await agent.find_webcast_button(page)
                    if button:
                        if await agent._replay_candidate_rejection(button, page.url):
                            button = None
                        else:
                            return button, page
            return None, page
    except Exception as exc:
        if await page.locator("body").count() == 0:
            print(f"[{agent.ticker}] archive fallback unavailable: {str(exc)[:160]}", flush=True)
            return None, page
        print(f"[{agent.ticker}] archive navigation timed out; inspecting rendered DOM", flush=True)

    button = await agent.find_webcast_button(page)
    if button:
        if await agent._replay_candidate_rejection(button, page.url):
            button = None
        else:
            return button, page

    # A historical archive can be a shell that exposes only a sibling
    # Videos/Webcast/Replay route. In proxy training mode, inspect those
    # bounded same-site links immediately instead of waiting for a human
    # handoff; the live path remains strict and does not use this branch.
    if agent.lifecycle == "replay":
        fallback_button, fallback_page = await agent._try_replay_training_surface_links(page)
        if fallback_button or fallback_page is not page:
            return fallback_button, fallback_page

    for _ in range(agent.human_retry_limit):
        if not await agent._human_handoff(
            page,
            stage="candidate",
            reason="아카이브에서도 재생 후보를 찾지 못했습니다.",
        ):
            break
        page = agent._page_after_human_handoff(page)
        await agent._wait_for_dynamic_page(page)
        if await agent.has_registration_form(page):
            return None, page
        button = await agent.find_webcast_button(page)
        if button:
            if await agent._replay_candidate_rejection(button, page.url):
                button = None
            else:
                return button, page
    if agent._replay_training_proxy_mode():
        fallback_button, fallback_page = await agent._try_replay_training_surface_links(page)
        if fallback_button or fallback_page is not page:
            return fallback_button, fallback_page
    return button, page


async def _expand_replay_event_rows(agent, page: Any) -> bool:
    """Expand hidden controls attached to past earnings-call rows."""
    if agent.lifecycle != "replay":
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
                if (text.length > 20 && text.length <= 1500 &&
                    /(?:earnings|conference call|webcast|listen|replay|watch|audio|video|presentation|webinar|financial results)/i.test(text) &&
                    /(?:20\\d{2}|\\d{1,2}\\/\\d{1,2}\\/20\\d{2})/i.test(text)) {
                    return text;
                }
            }
            return '';
        };
        const isFutureEvent = context => {
            const numeric = context.match(/\\b(0?[1-9]|1[0-2])\\/(0?[1-9]|[12]\\d|3[01])\\/(20\\d{2})\\b/);
            const named = context.match(/\\b(January|February|March|April|May|June|July|August|September|October|November|December)\\s+(\\d{1,2})(?:st|nd|rd|th)?,?\\s+(20\\d{2})\\b/i);
            const match = numeric || named;
            if (!match) return false;
            const months = {
                january: 0, february: 1, march: 2, april: 3, may: 4, june: 5,
                july: 6, august: 7, september: 8, october: 9, november: 10, december: 11,
            };
            const eventDate = numeric
                ? new Date(Number(match[3]), Number(match[1]) - 1, Number(match[2]))
                : new Date(Number(match[3]), months[String(match[1]).toLowerCase()], Number(match[2]));
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
                    f"[{agent.ticker}] expanded replay event control: {label or 'icon'}",
                    flush=True,
                )
                await asyncio.sleep(1)
                return True
            except Exception:
                continue
    return False


async def _page_has_earnings_context(agent, page: Any) -> bool:
    """Check whether the currently rendered archive page contains an earnings event."""
    text_parts: list[str] = []
    for frame in page.frames:
        try:
            text_parts.append((await frame.locator("body").inner_text(timeout=2000))[:8000])
        except Exception:
            continue
    return bool(EARNINGS_EVENT_CONTEXT_PATTERN.search(" ".join(text_parts)))


async def _page_has_replay_training_candidate(agent, page: Any) -> bool:
    """Return true only when the current page has a usable replay candidate.

    A future earnings row is not enough to stop replay training. We must
    keep looking through archived or similar webcast events until a link
    can actually be opened and tested.
    """
    if is_direct_player_url(str(page.url)):
        return True
    try:
        if await agent._has_visible_media_element(
            page,
            include_context_pages=False,
        ):
            return True
    except Exception:
        pass
    try:
        candidates = await agent._collect_candidates(page)
    except Exception:
        return False
    if choose_replay_training_candidate(
        candidates,
        minimum_age_days=agent._replay_minimum_age_days(),
    ) is not None:
        return True
    # A dated event/detail page is a valid downstream training surface even
    # when its actual provider link is rendered only after navigation.
    return choose_replay_training_surface_candidate(candidates) is not None


async def _try_replay_training_surface_links(
    agent,
    page: Any,
    *,
    max_links: int = 6,
) -> tuple[Any | None, Any]:
    """Probe recent event/detail links before handing off a missing candidate.

    A number of IR pages expose the event archive through links whose label
    is only a quarter/date or an icon. The normal candidate scorer quite
    reasonably avoids those ambiguous links. In replay training mode we
    can safely inspect a small, ranked set of same-domain/provider links
    and let the downstream page decide whether it has registration or a
    player. This keeps the real-time path strict while preventing an
    intermediate archive page from becoming a terminal "no candidate".
    """
    if agent.lifecycle != "replay":
        return None, page

    link_rows: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    current_url = str(page.url)
    current_host = domain_for_url(current_url)
    hint_pattern = re.compile(
        r"\b(?:earnings|results|quarter|conference|call|webcast|replay|"
        r"listen|watch|audio|video|presentation|webinar|event)\b|"
        r"/(?:events?|webcasts?|replays?|presentations?|media|conference|"
        r"earnings|calendar)(?:[-_/?.]|$)",
        re.IGNORECASE,
    )
    for frame in page.frames:
        try:
            links = frame.locator(
                "a[href], a[data-webcast-url], a[data-href], "
                "button[data-webcast-url], button[data-href], "
                "[role='button'][data-webcast-url], [role='button'][data-href]"
            )
            count = min(await links.count(), 500)
        except Exception:
            continue
        for index in range(count):
            link = links.nth(index)
            try:
                raw_href = ""
                for attribute in ("data-webcast-url", "data-href", "href"):
                    raw_href = (await link.get_attribute(attribute) or "").strip()
                    if raw_href and raw_href not in {"#", "javascript:void(0)", "javascript:;"}:
                        break
                if raw_href.lower().startswith("javascript:"):
                    embedded_url = re.search(r"https?://[^'\"\s)]+", raw_href)
                    raw_href = embedded_url.group(0) if embedded_url else ""
                href = urljoin(str(frame.url or current_url), raw_href)
                parsed = urlparse(href)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    continue
                if href in seen or href.rstrip("/") == current_url.rstrip("/"):
                    continue
                label = " ".join(
                    value.strip()
                    for value in (
                        await link.inner_text(),
                        await link.get_attribute("aria-label"),
                        await link.get_attribute("title"),
                    )
                    if value and value.strip()
                )
                try:
                    context = await link.evaluate(
                        "element => (element.parentElement?.innerText || '')"
                    )
                except Exception:
                    context = ""
                evidence = f"{label} {context} {href}"
                if not hint_pattern.search(evidence):
                    continue
                event_date = event_date_from_text(evidence)
                if event_date and event_date > date.today():
                    continue
                if is_non_playback_surface_url(href) or is_non_playback_product_surface_url(
                    href,
                    label,
                ) or is_non_playback_home_url(href, label):
                    continue
                if is_non_replay_navigation_link(href, label):
                    continue
                if NON_PLAYBACK_DOCUMENT_PATTERN.search(parsed.path):
                    continue
                if REPLAY_LOGIN_PATH_PATTERN.search(parsed.path):
                    continue
                host = domain_for_url(href)
                if host != current_host and not is_webcast_player_url(href):
                    continue
                score = 0
                if is_webcast_player_url(href):
                    score += 120
                if re.search(r"\b(?:webcast|replay|listen|watch|audio|video)\b", evidence, re.I):
                    score += 70
                if re.search(r"\b(?:earnings|results|quarter|conference call)\b", evidence, re.I):
                    score += 45
                if re.search(r"/(?:event|events|calendar|presentation|webcast|replay)", parsed.path, re.I):
                    score += 30
                if host == current_host:
                    score += 10
                seen.add(href)
                link_rows.append((score, href, label[:240]))
            except Exception:
                continue

    link_rows.sort(key=lambda item: item[0], reverse=True)
    for score, target_url, label in link_rows[: max(1, max_links)]:
        target_page = await page.context.new_page()
        agent._attach_media_watchers(target_page)
        try:
            print(
                f"[{agent.ticker}] replay surface fallback "
                f"score={score} label={label[:100]} url={target_url}",
                flush=True,
            )
            agent._record_target_url(target_url)
            await target_page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=agent.page_ready_timeout_ms,
            )
        except Exception as exc:
            if await target_page.locator("body").count() == 0:
                print(
                    f"[{agent.ticker}] replay surface fallback skipped: "
                    f"{str(exc)[:120]}",
                    flush=True,
                )
                await target_page.close()
                continue
        await agent._wait_for_dynamic_page(target_page)
        await agent.accept_cookie_banners(target_page)
        if await agent.has_registration_form(target_page, wait_seconds=3.0):
            return None, target_page
        if is_direct_player_url(str(target_page.url)) or await agent._has_visible_media_element(
            target_page,
            include_context_pages=False,
        ):
            return None, target_page
        button = await agent.find_webcast_button(target_page)
        if button:
            return button, target_page
        # Some IR event links open a second archive/detail shell whose
        # event rows are rendered only after navigation. Re-run the replay
        # archive preparation on that page before discarding the candidate.
        if domain_for_url(str(target_page.url)) == current_host:
            await agent._prepare_replay_history(target_page)
            if await agent.has_registration_form(target_page, wait_seconds=1.0):
                return None, target_page
            if is_direct_player_url(str(target_page.url)) or await agent._has_visible_media_element(
                target_page,
                include_context_pages=False,
            ):
                return None, target_page
            button = await agent.find_webcast_button(target_page)
            if button:
                return button, target_page
        try:
            await target_page.close()
        except Exception:
            pass
    return None, page


async def _recover_replay_archive_page(agent, page: Any) -> Any:
    """Return from a wrong provider tab to the original IR archive and keep scanning."""
    if agent.lifecycle != "replay":
        return page
    ir_domain = domain_for_url(agent.ir_url)
    for candidate in reversed(agent._usable_context_pages(page)):
        if domain_for_url(str(candidate.url)) != ir_domain:
            continue
        try:
            await candidate.bring_to_front()
        except Exception:
            pass
        print(
            f"[{agent.ticker}] returning to replay archive after non-target event: "
            f"{candidate.url}",
            flush=True,
        )
        await agent._prepare_replay_history(candidate)
        return candidate
    return page


async def _replay_pagination_controls(agent, page: Any) -> list[dict[str, Any]]:
    """Return visible archive pagination controls without guessing arbitrary links."""
    script = """() => {
        const compact = value => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
        const visible = element => {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' &&
                Number(style.opacity || 1) > 0 && rect.width > 4 && rect.height > 4;
        };
        const nthPath = element => {
            const parts = [];
            let current = element;
            for (let depth = 0; current && depth < 8; depth += 1, current = current.parentElement) {
                if (current.id) {
                    parts.unshift(`#${CSS.escape(current.id)}`);
                    break;
                }
                const tag = current.tagName.toLowerCase();
                const siblings = Array.from(current.parentElement?.children || [])
                    .filter(sibling => sibling.tagName === current.tagName);
                parts.unshift(`${tag}:nth-of-type(${Math.max(siblings.indexOf(current) + 1, 1)})`);
            }
            return parts.join(' > ');
        };
        return Array.from(document.querySelectorAll('a,button,[role="button"]'))
            .filter(visible)
            .map(element => {
                const text = compact(element.innerText);
                const aria = compact(element.getAttribute('aria-label'));
                const title = compact(element.getAttribute('title'));
                const label = compact([text, aria, title].filter(Boolean).join(' '));
                const metadata = `${element.className || ''} ${element.id || ''} ` +
                    `${element.parentElement?.className || ''}`.toLowerCase();
                const numberLabel = [text, aria, title].find(value =>
                    /^\\d{1,2}$/.test(value) ||
                    /^(?:go\\s+to\\s+)?page\\s+\\d{1,2}$/i.test(value)
                );
                const numberMatch = numberLabel && numberLabel.match(/\\d{1,2}/);
                const number = numberMatch ? Number(numberMatch[0]) : null;
                const navigation = number !== null ||
                    /^(?:next|older|more|previous|prev)$/i.test(label) ||
                    /(?:pagination|pager|page-number|page-link)/i.test(metadata);
                if (!navigation) return null;
                const active = element.getAttribute('aria-current') === 'page' ||
                    /(?:active|selected|current)/i.test(String(element.className || ''));
                return { selector: nthPath(element), label, number, active };
            })
            .filter(Boolean)
            .slice(0, 30);
    }"""
    controls: list[dict[str, Any]] = []
    for frame in page.frames:
        try:
            values = await asyncio.wait_for(frame.evaluate(script), timeout=5)
        except Exception:
            continue
        for value in values or []:
            if isinstance(value, dict):
                value["frame"] = frame
                controls.append(value)
    return controls


async def _replay_pagination_locators(agent, page: Any) -> list[dict[str, Any]]:
    """Read pagination controls through Playwright for SPA pages with unstable CSS paths."""
    controls: list[dict[str, Any]] = []
    for frame in page.frames:
        try:
            locator = frame.locator("a,button,[role='button']")
            count = min(await locator.count(), 200)
        except Exception:
            continue
        for index in range(count):
            control = locator.nth(index)
            try:
                if not await control.is_visible():
                    continue
                text = await control.inner_text()
                aria_label = await control.get_attribute("aria-label")
                title = await control.get_attribute("title")
                label = " ".join(
                    value.strip()
                    for value in (text, aria_label, title)
                    if value and value.strip()
                )
                label = re.sub(r"\s+", " ", label).strip()[:80]
                number = replay_page_number(text, aria_label, title)
                class_name = (await control.get_attribute("class") or "").lower()
                aria_current = await control.get_attribute("aria-current")
                active = aria_current == "page" or bool(
                    re.search(r"active|selected|current", class_name)
                )
                metadata = " ".join(
                    value
                    for value in (
                        class_name,
                        await control.get_attribute("id") or "",
                        await control.get_attribute("data-testid") or "",
                    )
                )
                navigation = (
                    number is not None
                    or label.lower() in {"next", "older", "more", "previous", "prev"}
                    or re.search(r"pagination|pager|page[-_ ]?(?:number|link)", metadata)
                )
                if navigation:
                    controls.append(
                        {
                            "locator": control,
                            "label": label,
                            "number": number,
                            "active": active,
                        }
                    )
            except Exception:
                continue
    return controls


async def _scan_replay_pagination(
    agent,
    page: Any,
    *,
    max_pages: int = 8,
    force: bool = False,
) -> bool:
    """Walk numbered archive pages until a replay-training surface appears."""
    if agent.lifecycle != "replay":
        return False

    last_page_number = 0
    visited_signatures: set[str] = set()
    for _ in range(max_pages):
        if not force and await agent._page_has_replay_training_candidate(page):
            print(f"[{agent.ticker}] replay training candidate found in archive", flush=True)
            return True

        try:
            body_text = " ".join(
                (await frame.locator("body").inner_text(timeout=1500))[:6000]
                for frame in page.frames
            )
        except Exception:
            body_text = ""
        signature = f"{page.url}|{hash(body_text)}"
        if signature in visited_signatures:
            return False
        visited_signatures.add(signature)

        controls = await agent._replay_pagination_locators(page)
        if not controls:
            controls = await agent._replay_pagination_controls(page)
        if last_page_number == 0:
            active_numbers = [
                int(control["number"])
                for control in controls
                if control.get("active") and isinstance(control.get("number"), int)
            ]
            all_numbers = [
                int(control["number"])
                for control in controls
                if isinstance(control.get("number"), int)
            ]
            if active_numbers:
                last_page_number = max(active_numbers)
            elif all_numbers and min(all_numbers) == 1:
                # Most archive pagers render page 1 without an active marker.
                last_page_number = 1
        numbered = [
            control
            for control in controls
            if isinstance(control.get("number"), int)
            and not control.get("active")
            and int(control["number"]) > last_page_number
        ]
        numbered.sort(key=lambda control: int(control["number"]))
        control = numbered[0] if numbered else next(
            (
                candidate
                for candidate in controls
                if not candidate.get("active")
                and str(candidate.get("label") or "").lower()
                in {"next", "older", "more"}
            ),
            None,
        )
        if not control:
            return False

        try:
            locator = control.get("locator")
            if locator is None:
                selector = str(control.get("selector") or "")
                frame = control.get("frame")
                if not selector or frame is None:
                    return False
                locator = frame.locator(selector).first
            await locator.click(force=True, timeout=8000)
            if isinstance(control.get("number"), int):
                last_page_number = int(control["number"])
            print(
                f"[{agent.ticker}] scanning historical replay page: {control.get('label')}",
                flush=True,
            )
            await asyncio.sleep(1.5)
        except Exception:
            return False
    return await agent._page_has_replay_training_candidate(page)


async def _prepare_replay_history(agent, page: Any) -> None:
    """Prefer historical archive evidence before live/future-page failure checks."""
    if agent.lifecycle != "replay":
        return
    print(f"[{agent.ticker}] preparing historical replay archive", flush=True)
    await agent._activate_replay_archive_view(page)
    # Replay training is explicitly allowed to use any past webcast-like
    # event. If the archive tab already exposes one, do not paginate into
    # a separate presentation-only archive and lose the playable links.
    if agent._replay_training_proxy_mode() and await agent._page_has_replay_training_candidate(page):
        return
    await agent._activate_replay_archive_year(page)
    current_non_earnings: str | None = None
    for _ in range(3):
        expanded = await agent._expand_replay_event_rows(page)
        current_non_earnings = await agent._detect_non_earnings_event(page)
        if await agent._page_has_replay_training_candidate(page):
            return
        if expanded:
            continue
        break
    await agent._scan_replay_pagination(
        page,
        force=bool(current_non_earnings),
    )


async def _activate_replay_archive_view(agent, page: Any) -> bool:
    """Open a client-rendered past-events tab before selecting replay links."""
    if agent.lifecycle != "replay":
        return False

    # Event tabs on IR templates are often inserted after the initial
    # document load. Give the client-rendered archive controls a brief
    # window before scanning them.
    await asyncio.sleep(3)
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
                    f"[{agent.ticker}] opening replay archive view: {label}",
                    flush=True,
                )
                await control.click(force=True, timeout=8000)
                await asyncio.sleep(2)
                await agent.accept_cookie_banners(page)
                return True
        except Exception:
            continue

    # Some IR templates render the tab through a custom button wrapper
    # that Playwright's text filter does not expose reliably. Use the
    # rendered label as a narrow fallback; this is limited to the exact
    # archive-tab labels and cannot select an arbitrary event.
    for frame in page.frames:
        try:
            opened = await frame.evaluate(
                """() => {
                    const compact = value => String(value || '').replace(/\\s+/g, ' ').trim();
                    const labels = /^(?:(?:past|previous|archived)\\s+(?:events?|webcasts?|calls?)|(?:webcasts?|events?)\\s+(?:&|and)\\s+presentations|investor\\s+calls?|historical\\s+webcasts?|webcast\\s+archives?)$/i;
                    const controls = Array.from(document.querySelectorAll(
                        'a, button, input[type="button"], input[type="submit"], ' +
                        '[role="tab"], [role="button"]'
                    ));
                    const control = controls.find(element => labels.test(compact([
                        element.innerText,
                        element.value,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                    ].filter(Boolean).join(' '))));
                    if (!control) return false;
                    control.scrollIntoView({ block: 'center', inline: 'nearest' });
                    control.click();
                    return true;
                }"""
            )
            if opened:
                print(
                    f"[{agent.ticker}] opening replay archive view via DOM label fallback",
                    flush=True,
                )
                await asyncio.sleep(2)
                await agent.accept_cookie_banners(page)
                return True
        except Exception:
            continue
    return False


async def _activate_replay_archive_year(agent, page: Any) -> bool:
    """Open the newest year listed specifically inside an archived-events section."""
    if agent.lifecycle != "replay" or id(page) in agent._replay_archive_year_page_ids:
        return False

    candidates: list[tuple[int, Any]] = []
    current_year = date.today().year
    for frame in page.frames:
        try:
            controls = frame.locator(
                "a, button, [role='button'], [role='tab']"
            ).filter(has_text=re.compile(r"^\s*20\d{2}\s*$"))
            count = min(await controls.count(), 40)
        except Exception:
            continue
        for index in range(count):
            control = controls.nth(index)
            try:
                label = " ".join((await control.inner_text()).split())
                if not re.fullmatch(r"20\d{2}", label):
                    continue
                year = int(label)
                if year > current_year:
                    continue
                visible = await control.is_visible()
                if not visible:
                    if os.getenv("WEBCAST_ARCHIVE_DIAGNOSTICS", "false").lower() == "true":
                        print(
                            f"[{agent.ticker}] archive year candidate "
                            f"year={year} visible=false",
                            flush=True,
                        )
                    continue
                in_archive = await control.evaluate(
                    """element => {
                        let current = element;
                        for (let depth = 0; current && depth < 8; depth += 1, current = current.parentElement) {
                            const text = String(current.innerText || current.textContent || '')
                                .replace(/\\s+/g, ' ').trim();
                            if (/(?:archived|past|previous)\\s+(?:events?|webcasts?|calls?)/i.test(text)) return true;
                        }
                        const archiveLabels = Array.from(document.querySelectorAll(
                            'h1, h2, h3, h4, h5, h6, [role="heading"], div, span, p, strong'
                        ));
                        return archiveLabels.some(label => {
                            const text = String(label.innerText || label.textContent || '')
                                .replace(/\\s+/g, ' ').trim();
                            if (!/^(?:archived|past|previous)\\s+(?:events?|webcasts?|calls?)$/i.test(text)) {
                                return false;
                            }
                            return Boolean(
                                label.compareDocumentPosition(element) &
                                Node.DOCUMENT_POSITION_FOLLOWING
                            );
                        });
                    }"""
                )
                if os.getenv("WEBCAST_ARCHIVE_DIAGNOSTICS", "false").lower() == "true":
                    print(
                        f"[{agent.ticker}] archive year candidate "
                        f"year={year} visible=true in_archive={bool(in_archive)}",
                        flush=True,
                    )
                if in_archive:
                    candidates.append((year, control))
            except Exception:
                continue

    for year, control in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            await control.scroll_into_view_if_needed(timeout=5000)
            await control.click(force=True, timeout=8000)
            agent._replay_archive_year_page_ids.add(id(page))
            print(
                f"[{agent.ticker}] opening archived event year: {year}",
                flush=True,
            )
            await asyncio.sleep(1.5)
            await agent.accept_cookie_banners(page)
            return True
        except Exception:
            continue
    return False
