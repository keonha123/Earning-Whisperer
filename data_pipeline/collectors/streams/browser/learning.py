"""Snapshots and learned recipe selection/replay."""

from __future__ import annotations

import asyncio
import json
import hashlib
from collections import Counter
import uuid
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from data_pipeline.live_telemetry import emit_live_event
from .rules import (
    HumanPageAssessment,
    LearningSnapshot,
    WebcastCandidate,
    WebcastRecipe,
    artifact_paths,
    candidate_identity_mismatch,
    choose_heuristic_candidate,
    choose_replay_training_candidate,
    choose_replay_training_surface_candidate,
    domain_for_url,
    is_non_playback_home_url,
    is_non_playback_product_surface_url,
    is_non_replay_navigation_link,
    is_replay_training_candidate,
    is_webcast_player_url,
    make_generalized_patterns,
)
from ..webcast_learning import candidate_event_evidence, live_candidate_event_type_mismatch


# Both initial ranking and the pinned click target must read the same local
# card. Do not climb past an event item merely because its title lacks the word
# "earnings"; doing so can borrow a neighbouring analyst call's date/title.
_EVENT_LOCAL_CONTEXT_JS = r"""
    const eventBoundary = node => node.matches('article, tr, [data-event-id], [itemtype*="schema.org/Event"]') ||
        /(?:^|\s)[^\s]*(?:event|webcast)[-_](?:item|card)(?:\s|$)/i.test(node.className || '');
    const eventDetailBoundary = node => node.matches(
        '.tribe-events-single, [data-event-detail], .event-detail, .event-details, .event-detail-page'
    );
    const eventStructuredContext = element => {
        // Only enrich a candidate from its own card or explicit detail page.
        // Never promote arbitrary page-wide dates, scripts or adjacent cards.
        let scope = null;
        for (let parent = element.parentElement, depth = 0;
             parent && depth < 12; parent = parent.parentElement, depth++) {
            if (eventBoundary(parent) || eventDetailBoundary(parent)) { scope = parent; break; }
            if (['BODY', 'MAIN'].includes(parent.tagName)) break;
        }
        if (!scope) return '';
        const owned = node => {
            for (let parent = node.parentElement; parent && parent !== scope; parent = parent.parentElement) {
                if (eventBoundary(parent) || eventDetailBoundary(parent)) return false;
            }
            return scope.contains(node);
        };
        let heading = '';
        for (const selector of ['h1', '[itemprop="name"]', 'h2,h3,h4,[data-event-title]']) {
            const names = [...scope.querySelectorAll(selector)].filter(owned)
                .map(node => (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim())
                .filter(value => value.length > 0 && value.length <= 300 &&
                    /earnings|financial (?:results|(?:conference )?call)|conference call|webcast|webinar/i.test(value));
            const unique = [...new Set(names)];
            if (unique.length > 1) return '';
            if (unique.length === 1) { heading = unique[0]; break; }
        }
        if (!heading) return '';
        const dates = new Set();
        for (const node of scope.querySelectorAll(
            'time[datetime]:not([itemprop="endDate"]), abbr[title], .dtstart[title], ' +
            '[itemprop="startDate"], [data-event-date], [data-start-date]'
        )) {
            if (!owned(node)) continue;
            if (node.closest('[itemprop="datePublished"], [itemprop="dateModified"], [itemprop="endDate"]')) continue;
            const preceding = document.createRange();
            preceding.setStart(node.parentElement, 0);
            preceding.setEndBefore(node);
            const dateLabel = preceding.toString().slice(-100).replace(/\s+/g, ' ').trim();
            if (/\b(?:(?:published|updated|last modified)(?:\s+(?:on|at))?|(?:quarter|period|fiscal year) ended)\s*[:\-]?$/i.test(dateLabel)) continue;
            const raw = node.getAttribute('datetime') || node.getAttribute('content') ||
                node.getAttribute('data-event-date') || node.getAttribute('data-start-date') ||
                node.getAttribute('title') || '';
            const match = raw.match(/^(20\d{2}-\d{2}-\d{2})(?:$|T|\s)/);
            if (match) dates.add(match[1]);
        }
        // Multiple explicit event days are ambiguous; the classifier must not
        // receive a convenient date borrowed from a different event.
        return dates.size === 1 ? `${heading} event-date=${[...dates][0]}` : '';
    };
    const eventLocalContext = element => {
        const structured = eventStructuredContext(element);
        // Accordion bodies may be siblings of the dated heading. Inherit only
        // the one control that explicitly owns this panel, never the whole list.
        let controlledHeading = '';
        for (let node=element.parentElement, depth=0; node && depth<8; node=node.parentElement,depth++) {
            if (['BODY','MAIN'].includes(node.tagName)) break;
            if (!node.id) continue;
            const controls=[...document.querySelectorAll('[aria-controls],[data-bs-target],[data-target]')]
                .filter(control => control.getAttribute('aria-controls') === node.id ||
                    control.getAttribute('data-bs-target') === '#' + node.id ||
                    control.getAttribute('data-target') === '#' + node.id);
            if (controls.length === 1) {
                const text=(controls[0].innerText || controls[0].textContent || '').replace(/\s+/g,' ').trim();
                if (text.length<=500 && /earnings|financial (?:results|call)|conference call|webcast/i.test(text)) {
                    controlledHeading=text; break;
                }
            }
            if (eventBoundary(node) || eventDetailBoundary(node)) break;
        }
        const withStructured = text => [structured, controlledHeading, text].filter(Boolean).join(' ');
        let fallback = '';
        for (let parent = element.parentElement, depth = 0;
             parent && depth < 8; parent = parent.parentElement, depth++) {
            if (['BODY', 'MAIN'].includes(parent.tagName)) break;
            const text = (parent.innerText || parent.textContent || '').replace(/\s+/g, ' ').trim();
            if (text.length > 20 && text.length <= 1500 &&
                /earnings|financial (?:results|(?:conference )?call)|conference call|webcast|listen|replay|watch|audio|video|presentation|webinar/i.test(text)) {
                if (!fallback) fallback = text;
                const hasDate = /(?:\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}[/-](?:20)?\d{2}\b|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2})/i.test(text);
                if (hasDate) return withStructured(text);
            }
            if (eventBoundary(parent) || eventDetailBoundary(parent)) return withStructured(fallback);
        }
        return withStructured(fallback);
    };
"""


async def _capture_learning_snapshot(agent, page: Any) -> LearningSnapshot:
    screenshot_path, candidates_path = artifact_paths(agent.ticker, page.url)
    # Multiple rescans may happen in one second; never overwrite their evidence.
    suffix = uuid.uuid4().hex[:8]
    screenshot_path = screenshot_path.with_name(screenshot_path.stem + "-" + suffix + ".jpg")
    candidates_path = candidates_path.with_name(candidates_path.stem + "-" + suffix + ".json")
    if getattr(agent, "discovery_only", False):
        candidates = await agent._collect_candidates(page)
        _persist_candidate_inventory(agent, page, candidates, candidates_path)
        return LearningSnapshot(
            screenshot_path=screenshot_path, candidates_path=candidates_path,
            candidates=tuple(candidates),
        )
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_timeout = max(
        5.0,
        float(os.getenv("WEBCAST_SCREENSHOT_TIMEOUT_SECONDS", "10")),
    )
    print(f"[{agent.ticker}] capturing learning snapshot", flush=True)
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
            f"[{agent.ticker}] learning snapshot unavailable; continuing with DOM: "
            f"{str(exc)[:120] or 'timeout'}",
            flush=True,
        )
    candidates = await agent._collect_candidates(page)
    print(f"[{agent.ticker}] collected {len(candidates)} visible candidates", flush=True)
    _persist_candidate_inventory(agent, page, candidates, candidates_path)
    return LearningSnapshot(
        screenshot_path=screenshot_path,
        candidates_path=candidates_path,
        candidates=tuple(candidates),
    )


def _candidate_rejection_reason(agent, candidate: WebcastCandidate, page_url: str) -> str | None:
    from .navigation import is_event_navigation
    if agent.lifecycle == "live" and is_event_navigation(
        candidate.href or candidate.href_path or "", candidate.text,
        candidate.aria_label, candidate.title,
    ):
        return "event_list_navigation"
    if (agent.lifecycle == 'live' and candidate.tag_name == 'a'
            and candidate.href and candidate.href == page_url
            and not re.search(r'\b(?:webcast|play|watch|listen|join|register)\b',
                              ' '.join((candidate.text, candidate.aria_label, candidate.title)), re.I)):
        return 'non_actionable_self_link'
    # Full destinations retain provider host and query-based event identifiers.
    if agent._is_live_excluded_url(candidate.href or candidate.href_path, page_url):
        return "excluded_event"
    mismatch = agent._live_candidate_identity_mismatch(candidate)
    if mismatch:
        return "identity_mismatch: " + str(mismatch)[:180]
    if agent._live_target_confirmation_required() and not agent._live_candidate_identity_confirmation(candidate):
        return "event_identity_unconfirmed"
    label = " ".join(value for value in (candidate.text, candidate.aria_label, candidate.title) if value)
    href = candidate.href or candidate.href_path or ""
    if is_non_playback_product_surface_url(href, label):
        return "product_navigation"
    if is_non_playback_home_url(href, label):
        return "homepage_navigation"
    if is_non_replay_navigation_link(href, label) or any(
        is_non_replay_navigation_link(url, label)
        for url in re.findall(r"https?://[^\"'\s>]+", " ".join(candidate.selectors))
    ):
        return "non_playback_navigation"
    return None


def _persist_candidate_inventory(agent, page: Any, candidates: list[WebcastCandidate], path: Path) -> None:
    """Keep read-only discovery evidence, excluding form values and URL secrets."""
    from .diagnostics import _safe_url, _scrub
    try:
        rows = []
        reasons = Counter()
        eligible_count = 0
        for candidate in candidates:
            reason = _candidate_rejection_reason(agent, candidate, str(page.url))
            if reason:
                reasons[reason.split(":", 1)[0]] += 1
            eligible_count += reason is None
            if len(rows) >= 600:
                continue
            href = str(candidate.href or candidate.href_path or "")
            rows.append({
                "candidate_id": candidate.candidate_id,
                "destination": _safe_url(urljoin(str(page.url), href)) if href else "",
                "destination_hash": hashlib.sha256(href.encode()).hexdigest()[:20],
                "text": candidate.text[:240], "context": candidate.context_text[:700],
                "metadata": candidate.metadata_text[:400], "rejection_reason": reason,
                "eligible": reason is None,
            })
        profile = getattr(agent, "profile", None)
        secrets = [str(getattr(profile, name, "")) for name in (
            "email", "password", "first_name", "last_name", "company", "phone_number",
            "q4_email", "q4_password", "q4_first_name", "q4_last_name",
        ) if len(str(getattr(profile, name, ""))) >= 3]
        # Context text can contain links; remove all URL query/fragment values.
        for row in rows:
            for key in ("text", "context", "metadata"):
                row[key] = re.sub(r"https?://[^\s<>\"']+", lambda m: _safe_url(m.group()), row[key])
        payload = _scrub({
            "page_url": _safe_url(str(page.url)), "candidate_count": len(candidates),
            "eligible_count": eligible_count, "omitted_count": len(candidates) - len(rows),
            "rejection_counts": dict(reasons), "candidates": rows,
            "call_id": os.getenv("WEBCAST_CALL_DB_ID", ""),
            "schedule_revision": os.getenv("WEBCAST_SCHEDULE_REVISION", ""),
            "attempt_id": os.getenv("WEBCAST_ATTEMPT_ID", ""),
        }, secrets)
        agent._last_candidate_inventory = {key: payload[key] for key in (
            "candidate_count", "eligible_count", "rejection_counts",
        )}
        payload["eligibility_scope"] = "identity_and_surface_filters_before_ranking_and_locator_validation"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
            json.dump(payload, output, ensure_ascii=False)
        emit_live_event("discovery", "candidate_inventory", status=(
            "no_candidates" if not rows else "no_eligible_candidates" if not payload["eligible_count"] else "candidates_found"
        ), ticker=agent.ticker, page_url=str(page.url), artifact_path=str(path),
            **agent._last_candidate_inventory)
    except Exception as exc:
        # Evidence output must never turn a playable event into a failed probe.
        emit_live_event("discovery", "evidence_unavailable", status="warning",
                        error_type=type(exc).__name__, ticker=agent.ticker)


async def _capture_failure_snapshot(agent, page: Any) -> None:
    """Persist a redacted terminal browser state for later rule improvement."""
    from .diagnostics import capture_diagnostics
    await capture_diagnostics(agent, getattr(page, "context", page), "browser_failure")
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
        agent._learning_snapshot = await agent._capture_learning_snapshot(page)
        print(
            f"[{agent.ticker}] captured redacted failure snapshot: "
            f"{agent._artifact_path()}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[{agent.ticker}] failure snapshot skipped: {str(exc)[:120]}",
            flush=True,
        )
    if agent.failure_hold_seconds > 0:
        print(
            f"[{agent.ticker}] holding failure screen for "
            f"{agent.failure_hold_seconds:g}s",
            flush=True,
        )
        await asyncio.sleep(agent.failure_hold_seconds)


async def _collect_candidates(
    agent,
    page: Any,
    *,
    include_hidden: bool = False,
) -> list[WebcastCandidate]:
    script = """() => {
        /* event local context */
        const compact = value => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 500);
        const contextText = eventLocalContext;
        const metadataText = element => {
            const values = [];
            const attributes = [
                'datetime', 'data-date', 'data-event-date', 'data-start',
                'data-start-time', 'data-live', 'data-status', 'data-state',
                'data-updated', 'data-published', 'data-last-modified',
                'aria-live', 'role'
            ];
            let current = element;
            for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
                for (const name of attributes) {
                    const value = current.getAttribute(name);
                    if (value) {
                        values.push(`${name}=${compact(value)}`);
                    }
                }
                const labels = `${current.id || ''} ${current.getAttribute('class') || ''}`;
                if (/(?:live|upcoming|scheduled|webcast|earnings|event)/i.test(labels)) {
                    values.push(`container=${compact(labels)}`);
                }
                if (eventBoundary(current)) break;
            }
            return compact([...new Set(values)].join(' ')).slice(0, 1000);
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
            const href = element.getAttribute('href');
            if (element.tagName.toLowerCase() === 'a' && href) {
                values.push(`a[href=${JSON.stringify(href)}]`);
            }
            values.push(nthPath(element));
            return [...new Set(values)].filter(Boolean);
        };

        return Array.from(document.querySelectorAll(
            'a, button, [role="button"], [role="link"], [role="tab"], [onclick], video, audio'
        ))
            .filter(visible)
            // Large IR pages often put the current event below long navigation,
            // year selectors, and disclosure links. Keep enough candidates for
            // the context/quarter scorer to see those controls.
            .slice(0, 600)
            .map((element, index) => {
                const rect = element.getBoundingClientRect();
                const rawHref = element.getAttribute('href') || '';
                let hrefPath = null;
                let resolvedHref = null;
                try {
                    const parsedHref = rawHref ? new URL(rawHref, document.baseURI) : null;
                    hrefPath = parsedHref ? parsedHref.pathname : null;
                    resolvedHref = parsedHref ? parsedHref.href : null;
                } catch (_) {}
                return {
                    dom_index: index,
                    selectors: selectors(element),
                    text: compact(element.innerText || element.textContent),
                    aria_label: compact(element.getAttribute('aria-label')),
                    title: compact(element.getAttribute('title')),
                    href_path: hrefPath,
                    href: resolvedHref,
                    tag_name: element.tagName.toLowerCase(),
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    in_navigation: inNavigation(element),
                    context_text: contextText(element),
                    metadata_text: metadataText(element),
                };
            });
    }""".replace("/* event local context */", _EVENT_LOCAL_CONTEXT_JS)
    if include_hidden:
        # Lazy IR templates frequently keep the historical event anchors
        # hidden until a tab/accordion is opened. They are still valid
        # href targets for the bounded replay fallback.
        script = script.replace(
            ".filter(visible)",
            ".filter(element => visible(element) || "
            "element.tagName.toLowerCase() === 'a')",
        )
    candidates: list[WebcastCandidate] = []
    for frame_index, frame in enumerate(page.frames):
        try:
            rows = await asyncio.wait_for(frame.evaluate(script), timeout=5)
        except Exception as exc:
            emit_live_event("discovery", "frame_scan_failed", status="partial_dom_unavailable",
                            ticker=agent.ticker, frame_index=frame_index,
                            error_type=type(exc).__name__)
            continue
        frame_hostname = None if frame == page.main_frame else domain_for_url(frame.url)
        for row in rows:
            row["candidate_id"] = f"frame-{frame_index}-element-{row.pop('dom_index')}"
            row["frame_hostname"] = frame_hostname or None
            candidates.append(WebcastCandidate.from_dict(row))
    return candidates


async def _choose_learning_candidate(
    agent,
    page: Any,
    snapshot: LearningSnapshot,
) -> tuple[WebcastCandidate | None, str, float, str | None]:
    candidates = []
    identity_confirmation_required = agent._live_target_confirmation_required()
    for candidate in snapshot.candidates:
        rejection = _candidate_rejection_reason(agent, candidate, str(page.url))
        if rejection:
            print(f"[{agent.ticker}] skipping learning candidate "
                  f"id={candidate.candidate_id} reason={rejection}", flush=True)
            continue
        candidates.append(candidate)
    replay_proxy_mode = agent._replay_training_proxy_mode()
    selection = None
    if not getattr(agent, "discovery_only", False) and not getattr(agent, "_selection_retry", False):
        selection = await agent._vision_selector.select(
            snapshot.screenshot_path, candidates, ticker=agent.ticker,
        )
    minimum_confidence = float(os.getenv("WEBCAST_VISION_MIN_CONFIDENCE", "0.55"))
    if selection and selection.confidence >= minimum_confidence:
        selected = next(
            (candidate for candidate in candidates if candidate.candidate_id == selection.candidate_id),
            None,
        )
        if selected and (
            not replay_proxy_mode
            or is_replay_training_candidate(
                selected,
                minimum_age_days=agent._replay_minimum_age_days(),
            )
        ):
            return selected, "vision", selection.confidence, selection.reason
        if selected and replay_proxy_mode:
            print(
                f"[{agent.ticker}] replay proxy rejected non-playable "
                f"vision candidate={selected.candidate_id}",
                flush=True,
            )
        if selection.x > 0 and selection.y > 0:
            pointed = await agent._candidate_at_page_point(page, selection.x, selection.y)
            pointed_confirmation = (
                agent._live_candidate_identity_confirmation(pointed)
                if pointed and identity_confirmation_required
                else None
            )
            if pointed and (
                not _candidate_rejection_reason(agent, pointed, str(page.url))
                and (not identity_confirmation_required or pointed_confirmation)
                and (
                    not replay_proxy_mode
                    or is_replay_training_candidate(
                        pointed,
                        minimum_age_days=agent._replay_minimum_age_days(),
                    )
                )
            ):
                return pointed, "vision-point", selection.confidence, selection.reason

    generalized_patterns = ()
    if agent.generalized_learning_enabled and not getattr(agent, "discovery_only", False):
        try:
            try:
                from .... import database
            except ImportError:
                from data_pipeline import database

            generalized_patterns = make_generalized_patterns(
                database.get_generalized_webcast_patterns(
                    agent._compatible_recipe_lifecycles()
                )
            )
            if generalized_patterns:
                print(
                    f"[{agent.ticker}] applying generalized webcast evidence "
                    f"patterns={len(generalized_patterns)}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[{agent.ticker}] generalized evidence lookup skipped: {str(exc)[:120]}",
                flush=True,
            )

    heuristic = choose_heuristic_candidate(
        candidates,
        generalized_patterns,
        lifecycle=agent.lifecycle,
        target_year=agent.target_year,
        target_quarter=agent.target_quarter,
        target_date=agent.target_date,
        target_time_utc=agent.target_time_utc,
        replay_minimum_age_days=agent._replay_minimum_age_days(),
    )
    if heuristic and (
        not replay_proxy_mode
        or is_replay_training_candidate(
            heuristic,
            minimum_age_days=agent._replay_minimum_age_days(),
        )
    ):
        return heuristic, "dom-heuristic", 0.50, None
    if heuristic and replay_proxy_mode:
        print(
            f"[{agent.ticker}] replay proxy rejected non-playable "
            f"heuristic candidate={heuristic.candidate_id}",
            flush=True,
        )
    if replay_proxy_mode:
        proxy_candidate = choose_replay_training_candidate(
            candidates,
            minimum_age_days=agent._replay_minimum_age_days(),
        )
        if proxy_candidate:
            return proxy_candidate, "replay-training-proxy", 0.45, None

        # The strict proxy selector above requires a player-like label on
        # the current page. Many IR sites expose only a dated event/detail
        # link here and render the actual webcast on the next page. Keep
        # the downstream training loop moving with that intermediate link.
        surface_candidate = choose_replay_training_surface_candidate(candidates)
        if surface_candidate:
            return surface_candidate, "replay-training-surface-fallback", 0.40, None

        hidden_candidates = await agent._collect_candidates(
            page,
            include_hidden=True,
        )
        if hidden_candidates:
            hidden_candidate = choose_replay_training_candidate(
                hidden_candidates,
                minimum_age_days=agent._replay_minimum_age_days(),
            ) or choose_replay_training_surface_candidate(hidden_candidates)
            if hidden_candidate:
                print(
                    f"[{agent.ticker}] using hidden or delayed replay candidate "
                    f"{hidden_candidate.candidate_id}",
                    flush=True,
                )
                return hidden_candidate, "replay-training-hidden-fallback", 0.35, None
    return None, "none", 0.0, None


def _live_candidate_date_mismatch(
    agent,
    candidate: WebcastCandidate,
) -> bool:
    """Backward-compatible predicate retained for existing callers."""
    return bool(agent._live_candidate_identity_mismatch(candidate))


def _live_candidate_identity_mismatch(
    agent,
    candidate: WebcastCandidate,
) -> str | None:
    if agent.lifecycle != "live":
        return None
    event_type = live_candidate_event_type_mismatch(candidate)
    if event_type:
        return event_type
    return candidate_identity_mismatch(
        candidate,
        target_ticker=agent.ticker,
        # Stored call periods are calendar values; issuer pages commonly use
        # a different fiscal year/quarter for the same exact event date.
        target_year=None,
        target_quarter=None,
        target_date=agent.target_date,
        target_time_utc=agent.target_time_utc,
    )


async def _candidate_at_page_point(
    agent,
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
                metadata_text: [
                    'datetime', 'data-date', 'data-event-date', 'data-start',
                    'data-start-time', 'data-live', 'data-status', 'data-state',
                    'data-updated', 'data-published', 'aria-live'
                ].map(name => {
                    const value = target.getAttribute(name);
                    return value
                        ? `${name}=${compact(value)}`
                        : '';
                }).filter(Boolean).join(' '),
            };
        }""",
        {"x": x, "y": y},
    )
    if not row:
        return None
    row["candidate_id"] = f"vision-point-{int(x)}-{int(y)}"
    row["frame_hostname"] = None
    return WebcastCandidate.from_dict(row)


async def _live_element_candidate(element: Any) -> WebcastCandidate:
    """Prove the live identity from the element we will actually click."""
    row = await element.evaluate(
        r"""element => {
            /* event local context */
            const compact = value => (value || '').replace(/\s+/g, ' ').trim();
            const href = element.getAttribute('href') || '';
            const context = eventLocalContext(element);
            const metadata = [];
            for (let current = element, depth = 0;
                 current && depth < 6; current = current.parentElement, depth++) {
                if (['BODY', 'MAIN'].includes(current.tagName)) break;
                for (const name of ['datetime', 'data-date', 'data-event-date', 'data-start', 'data-start-time']) {
                    const value = current.getAttribute(name);
                    if (value) metadata.push(`${name}=${value}`);
                }
                if (metadata.length || eventBoundary(current)) break;
            }
            let path = null;
            try { path = href ? new URL(href, document.baseURI).pathname : null; } catch (_) {}
            return {
                candidate_id: 'current-click-target',
                selectors: href ? [`a[href=${JSON.stringify(href)}]`] : [],
                text: compact(element.innerText || element.textContent),
                aria_label: element.getAttribute('aria-label') || '',
                title: element.getAttribute('title') || '',
                href_path: path, href: href ? new URL(href, document.baseURI).href : null,
                tag_name: element.tagName.toLowerCase(),
                context_text: context, metadata_text: metadata.join(' '),
            };
        }""".replace("/* event local context */", _EVENT_LOCAL_CONTEXT_JS)
    )
    return WebcastCandidate.from_dict(row)


async def _live_element_confirmation(agent, element: Any) -> str | None:
    candidate = await _live_element_candidate(element)
    if not agent._live_candidate_identity_confirmation(candidate):
        return None
    # Persist what was actually selected, not only a generic "date matched"
    # verdict. Downstream schedule guards need the title/date to revalidate it.
    return candidate_event_evidence(candidate)


def _recipe_exact_href(recipe: WebcastRecipe) -> str | None:
    """Recover the complete href already preserved by the candidate selector."""
    for selector in recipe.selectors:
        match = re.fullmatch(r'a\[href=("(?:[^"\\]|\\.)*")\]', selector)
        if match:
            return json.loads(match.group(1))
    return None


async def _find_recipe_button(agent, page: Any, recipe: WebcastRecipe) -> Any | None:
    allow_hidden_replay_target = recipe.strategy in {
        "replay-training-surface-fallback",
        "replay-training-hidden-fallback",
    }
    frames = [page.main_frame]
    if recipe.frame_hostname:
        frames = [
            frame for frame in page.frames
            if domain_for_url(frame.url) == recipe.frame_hostname
        ]
    exact_href = _recipe_exact_href(recipe)
    identity_required = agent._live_target_confirmation_required()

    async def unique_target(locator: Any, *, require_path: bool = False) -> Any | None:
        matches = []
        # Pin DOM nodes now. A positional Locator could resolve to another
        # event after a dynamic list reorder between selection and click.
        for element in await locator.element_handles():
            if not allow_hidden_replay_target and not await element.is_visible():
                continue
            href = (await element.get_attribute("href") or "").strip()
            base = await element.evaluate("element => element.ownerDocument.baseURI")
            if exact_href and urljoin(base, href) != urljoin(base, exact_href):
                continue
            if require_path and urlparse(urljoin(base, href)).path != recipe.target_href_path:
                continue
            confirmation = None
            if agent.lifecycle == "live":
                current = await _live_element_candidate(element)
                from .navigation import is_event_navigation
                if is_event_navigation(current.href or current.href_path or "",
                                       current.text, current.aria_label, current.title):
                    continue
                if agent._live_candidate_identity_mismatch(current):
                    continue
                if _candidate_rejection_reason(agent, current, str(page.url)) == 'non_actionable_self_link':
                    continue
            if identity_required:
                confirmation = await _live_element_confirmation(agent, element)
                if not confirmation:
                    continue
            matches.append((element, confirmation))
        if len(matches) != 1:
            return None
        element, confirmation = matches[0]
        if (not confirmation and agent.lifecycle == "live"
                and hasattr(agent, "_validate_live_target_page")
                and await agent._validate_live_target_page(page)):
            confirmation = agent.live_target_identity_evidence or "linked from confirmed event"
        if confirmation:
            href = (await element.get_attribute("href") or "").strip()
            base = await element.evaluate("element => element.ownerDocument.baseURI")
            agent._mark_live_target_identity_confirmed(
                confirmation, source_url=str(page.url),
                target_url=urljoin(base, href) if href else str(page.url),
            )
        return element

    for frame in frames:
        selectors = list(recipe.selectors)
        if exact_href:
            selectors.insert(0, f"a[href={json.dumps(exact_href)}]")
        for selector in dict.fromkeys(selectors):
            try:
                candidate = await unique_target(frame.locator(selector))
                if candidate is not None:
                    return candidate
            except Exception:
                continue
        # Old recipes may lack an exact href. A path/text fallback must still
        # resolve uniquely, and live event evidence is reread from that node.
        if recipe.target_href_path:
            try:
                candidate = await unique_target(
                    frame.locator(f"a[href*={json.dumps(recipe.target_href_path)}]"),
                    require_path=True,
                )
                if candidate is not None:
                    return candidate
            except Exception:
                pass
        if recipe.target_text:
            try:
                candidate = await unique_target(
                    frame.locator("a, button, [role='button']").filter(
                        has_text=re.compile(re.escape(recipe.target_text[:120]), re.IGNORECASE)
                    )
                )
                if candidate is not None:
                    return candidate
            except Exception:
                pass
    return None


def _load_verified_human_workflows(
    agent,
    page_url: str,
    *,
    stage: str,
) -> list[WebcastRecipe]:
    domain = domain_for_url(page_url)
    if not domain:
        return []
    try:
        try:
            from .... import database
        except ImportError:
            from data_pipeline import database

        recipes = [
            WebcastRecipe.from_record(row)
            for row in database.get_verified_human_workflows(
                domain,
                lifecycles=agent._compatible_recipe_lifecycles(),
            )
        ]
        return [
            recipe
            for recipe in recipes
            if recipe.stage == agent._human_workflow_stage(stage)
        ]
    except Exception as exc:
        print(
            f"[{agent.ticker}] human workflow lookup skipped: {str(exc)[:160]}",
            flush=True,
        )
        return []


async def _find_human_workflow_step(
    agent,
    page: Any,
    step: dict[str, Any],
) -> Any | None:
    frame_hostname = domain_for_url(str(step.get("frame_url") or ""))
    frames = [
        frame
        for frame in page.frames
        if not frame_hostname or domain_for_url(str(frame.url)) == frame_hostname
    ]
    if not frames:
        frames = list(page.frames)

    href = str(step.get("href") or "").strip()
    href_path = urlparse(href).path if href else ""
    selector = str(step.get("selector") or "").strip()
    element_path = str(step.get("element_path") or "").strip()
    generic_selectors = {"a", "button", "div", "span", "input", "label"}
    labels = [
        str(step.get(key) or "").strip()
        for key in ("text", "aria_label", "title")
        if str(step.get(key) or "").strip()
    ]

    for frame in frames:
        if element_path:
            try:
                locator = frame.locator(element_path).first
                if await locator.count() > 0 and await locator.is_visible():
                    return locator
            except Exception:
                pass
        if href_path:
            try:
                locator = frame.locator(
                    f"a[href*={json.dumps(href_path)}]"
                ).first
                if await locator.count() > 0 and await locator.is_visible():
                    return locator
            except Exception:
                pass
        if selector and selector not in generic_selectors:
            try:
                locator = frame.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible():
                    return locator
            except Exception:
                pass
        for label in labels:
            try:
                candidates = frame.locator(
                    "a,button,[role='button'],[role='link'],summary"
                ).filter(has_text=re.compile(re.escape(label), re.IGNORECASE))
                for index in range(min(await candidates.count(), 30)):
                    candidate = candidates.nth(index)
                    if not await candidate.is_visible():
                        continue
                    visible_label = " ".join(
                        (
                            await candidate.inner_text()
                            or await candidate.get_attribute("aria-label")
                            or await candidate.get_attribute("title")
                            or ""
                        ).split()
                    )
                    if visible_label.casefold() == " ".join(label.split()).casefold():
                        return candidate
                first = candidates.first
                if await first.count() > 0 and await first.is_visible():
                    return first
            except Exception:
                continue

        if bool(step.get("icon_control")) or (
            not labels
            and not href_path
            and selector.lower() in generic_selectors
            and is_webcast_player_url(str(page.url))
        ):
            controls = frame.locator(
                "button, a, div[role='button'], "
                "[aria-label*='play' i], [aria-label*='listen' i], "
                "[aria-label*='start' i], [aria-label*='unmute' i], "
                "[title*='play' i], [title*='listen' i], "
                "[title*='start' i], [title*='unmute' i]"
            )
            try:
                count = await controls.count()
            except Exception:
                count = 0
            for index in range(count):
                candidate = controls.nth(index)
                try:
                    if not await candidate.is_visible():
                        continue
                    matches_player_context = await candidate.evaluate(
                        """element => {
                            if (!element.querySelector('svg, use, path')) return false;
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
                            return rect.top >= window.innerHeight * 0.45
                                || /player|video|media|control|playback|progress|timeline|seek|webcast/i.test(context);
                        }"""
                    )
                except Exception:
                    continue
                if matches_player_context:
                    return candidate
    return None


async def _apply_human_workflow(
    agent,
    page: Any,
    *,
    stage: str,
) -> tuple[Any, bool]:
    """Replay a stage-verified, ordered human path in the current context."""
    if (
        agent.lifecycle == "live" and stage in {"registration", "playback"}
        and await agent._validate_live_target_page(page)
    ):
        from .provider_steps import apply_provider_steps
        for recipe in _load_verified_provider_steps(agent, page.url, stage=stage):
            page, applied = await apply_provider_steps(agent, page, recipe, stage=stage)
            if applied:
                return page, True
    recipes = agent._load_verified_human_workflows(page.url, stage=stage)
    if not recipes:
        return page, False

    for recipe in recipes:
        steps = recipe.evidence.get("steps")
        if not isinstance(steps, list) or not steps:
            continue
        current_page = page
        completed = True
        print(
            f"[{agent.ticker}] replaying human workflow "
            f"stage={recipe.stage} steps={len(steps)} recipe_id={recipe.recipe_id}",
            flush=True,
        )
        for index, raw_step in enumerate(steps):
            if not isinstance(raw_step, dict):
                completed = False
                break
            step = dict(raw_step)
            locator = await agent._find_human_workflow_step(current_page, step)
            if locator is None:
                href = str(step.get("href") or "").strip()
                if (
                    index == len(steps) - 1
                    and urlparse(href).scheme in {"http", "https"}
                ):
                    try:
                        target_page = await current_page.context.new_page()
                        agent._attach_media_watchers(target_page)
                        await target_page.goto(
                            href,
                            wait_until="domcontentloaded",
                            timeout=agent.page_ready_timeout_ms,
                        )
                        current_page = target_page
                        continue
                    except Exception:
                        pass
                completed = False
                break

            pages_before_click = tuple(current_page.context.pages)
            source_url = str(current_page.url)
            try:
                await locator.click(force=True, timeout=8000)
                current_page = await agent._wait_for_clicked_target(
                    current_page.context,
                    source_page=current_page,
                    source_url=source_url,
                    pages_before_click=pages_before_click,
                )
                current_page = agent._latest_context_page(current_page)
                await agent._wait_for_dynamic_page(current_page)
            except Exception:
                completed = False
                break

        assessment = (
            await agent._classify_human_page(current_page)
            if completed
            else HumanPageAssessment("unknown", "workflow step could not be replayed")
        )
        if completed and agent._workflow_checkpoint_succeeded(
            recipe.stage,
            assessment,
            [dict(step) for step in steps if isinstance(step, dict)],
        ):
            try:
                try:
                    from .... import database
                except ImportError:
                    from data_pipeline import database

                if recipe.recipe_id:
                    database.record_webcast_recipe_outcome(
                        recipe.recipe_id,
                        success=True,
                    )
            except Exception:
                pass
            print(
                f"[{agent.ticker}] HUMAN_WORKFLOW_REPLAYED stage={recipe.stage} "
                f"state={assessment.state} url={current_page.url}",
                flush=True,
            )
            return current_page, True

        try:
            try:
                from .... import database
            except ImportError:
                from data_pipeline import database

            if recipe.recipe_id:
                database.record_webcast_recipe_outcome(
                    recipe.recipe_id,
                    success=False,
                    error=assessment.reason or "human workflow replay did not reach its checkpoint",
                )
        except Exception:
            pass
    return page, False


def _load_verified_provider_steps(agent, page_url: str, *, stage: str) -> list[WebcastRecipe]:
    """Only explicitly reviewed provider-common actions cross lifecycle bounds."""
    if getattr(agent, "discovery_only", False):
        return []
    domain = domain_for_url(page_url)
    try:
        try:
            from .... import database
        except ImportError:
            from data_pipeline import database
        rows = database.get_verified_webcast_recipes(
            domain, lifecycles=("live", "replay", "unknown"),
        ) + database.get_verified_human_workflows(
            domain, lifecycles=("live", "replay", "unknown"),
        )
        recipes = [WebcastRecipe.from_record(row) for row in rows]
        return [
            recipe for recipe in recipes
            if recipe.evidence.get("scope") == "provider_common"
            and recipe.stage == stage and recipe.domain == domain
            and recipe.evidence.get("domain", domain) == domain
        ]
    except Exception as exc:
        print(f"[{agent.ticker}] provider-common lookup skipped: {str(exc)[:100]}")
        return []


def _load_verified_recipes(agent, page_url: str) -> list[WebcastRecipe]:
    if getattr(agent, "discovery_only", False):
        return []
    domain = domain_for_url(page_url)
    if not domain:
        return []
    try:
        try:
            from .... import database
        except ImportError:
            from data_pipeline import database

        return [
            WebcastRecipe.from_record(row)
            for row in database.get_verified_webcast_recipes(
                domain,
                lifecycles=agent._compatible_recipe_lifecycles(),
            )
        ]
    except Exception as exc:
        print(f"[{agent.ticker}] recipe lookup skipped: {str(exc)[:160]}")
        return []


def _compatible_recipe_lifecycles(agent) -> tuple[str, ...]:
    if agent.lifecycle == "live":
        # A replay recipe often contains an event-specific attendee path. Reusing it
        # for a live watch can open an old recording and create a false audio hit.
        return ("live", "unknown")
    if agent.lifecycle == "pre_live":
        return ("pre_live", "unknown")
    if agent.lifecycle == "replay":
        return ("replay", "unknown")
    return ("unknown",)


def _save_recipe(agent, recipe: WebcastRecipe) -> int | None:
    if getattr(agent, "discovery_only", False):
        return None
    try:
        try:
            from .... import database
        except ImportError:
            from data_pipeline import database

        return database.save_webcast_recipe(recipe.database_value())
    except Exception as exc:
        print(f"[{agent.ticker}] recipe save skipped: {str(exc)[:160]}")
        return None


def _recipe_context_path(agent) -> Path:
    return Path(os.getenv("WEBCAST_RECIPE_CONTEXT_PATH", "/tmp/ew-webcast-recipe.json"))


def _clear_recipe_context(agent) -> None:
    agent._recipe_context_path().unlink(missing_ok=True)


def _write_recipe_context(agent) -> None:
    if not agent._active_recipe or not agent._active_recipe.recipe_id:
        return
    path = agent._recipe_context_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "recipe_id": agent._active_recipe.recipe_id,
                "recipe_strategy": agent._active_recipe.strategy,
                "recipe_lifecycle": agent._active_recipe.lifecycle,
                "ticker": agent.ticker,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )


def _recipe_id(agent) -> int | None:
    return agent._active_recipe.recipe_id if agent._active_recipe else None


def _recipe_strategy(agent) -> str | None:
    return agent._active_recipe.strategy if agent._active_recipe else None


def _artifact_path(agent) -> str | None:
    return str(agent._learning_snapshot.screenshot_path) if agent._learning_snapshot else None


async def _is_navigation_element(agent, element: Any) -> bool:
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
