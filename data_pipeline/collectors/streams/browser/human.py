"""Human handoff recording and verified workflow checkpoints."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse
from .rules import (
    EARNINGS_EVENT_CONTEXT_PATTERN,
    HUMAN_ACTION_CAPTURE_SCRIPT,
    HumanPageAssessment,
    WebcastRecipe,
    domain_for_url,
    is_direct_player_url,
    is_nonessential_popup_url,
    is_webcast_player_url,
    non_earnings_event_reason,
)


async def _wait_for_manual_ready(agent, page: Any) -> str | None:
    """Let a human complete consent/login/anti-bot checks in a visible browser first."""
    if not agent.manual_ready_path:
        return None

    print(
        f"[{agent.ticker}] MANUAL_BROWSER_READY path={agent.manual_ready_path} url={page.url}",
        flush=True,
    )
    deadline = asyncio.get_running_loop().time() + max(1, agent.manual_ready_timeout_seconds)
    while asyncio.get_running_loop().time() < deadline:
        if agent.manual_ready_path.exists():
            await agent.accept_cookie_banners(page)
            agent._page_barrier = await agent._detect_access_barrier(page)
            return None
        await asyncio.sleep(0.5)
    return f"manual browser confirmation timed out after {agent.manual_ready_timeout_seconds:g}s"


async def _install_human_action_capture(agent, context: Any) -> None:
    """Install navigation-safe action capture before any page is opened."""
    try:
        await context.expose_binding(
            "__ewRecordHumanAction",
            agent._receive_human_action,
        )
    except Exception as exc:
        print(
            f"[{agent.ticker}] human action binding unavailable; "
            f"using page queue fallback: {str(exc)[:120]}",
            flush=True,
        )
    await context.add_init_script(HUMAN_ACTION_CAPTURE_SCRIPT)


def _receive_human_action(agent, source: Any, value: Any) -> None:
    """Receive one redacted action before a click navigation destroys its page."""
    if not agent._human_capture_active or not isinstance(value, dict):
        return
    action = dict(value)
    action.pop("value", None)
    action.pop("input_value", None)
    page = source.get("page") if isinstance(source, dict) else None
    frame = source.get("frame") if isinstance(source, dict) else None
    action["page_url"] = str(
        action.pop("captured_page_url", "")
        or getattr(page, "url", "")
    )
    action["frame_url"] = str(getattr(frame, "url", "") or action["page_url"])
    action["handoff"] = agent._human_handoff_count
    captured_at = float(action.get("captured_at") or time.time() * 1000)
    if page is not None and captured_at >= agent._last_human_action_at:
        agent._last_human_action_page = page
        agent._last_human_action_at = captured_at
    agent._human_action_buffer.append(action)


def _human_action_fingerprint(action: dict[str, Any]) -> str:
    return "|".join(
        str(action.get(key) or "")
        for key in (
            "handoff",
            "captured_at",
            "type",
            "selector_hint",
            "page_url",
            "frame_url",
        )
    )


def _persist_human_actions(agent, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not actions or not agent.human_action_log_path:
        return []

    persisted: list[dict[str, Any]] = []
    for action in actions:
        action.pop("value", None)
        action.pop("input_value", None)
        fingerprint = agent._human_action_fingerprint(action)
        if fingerprint in agent._human_action_seen:
            continue
        agent._human_action_seen.add(fingerprint)
        persisted.append(action)
        handoff = int(action.get("handoff") or agent._human_handoff_count)
        agent._human_actions_by_handoff.setdefault(handoff, []).append(action)

    if not persisted:
        return []
    agent.human_action_log_path.parent.mkdir(parents=True, exist_ok=True)
    with agent.human_action_log_path.open("a", encoding="utf-8") as handle:
        for action in persisted:
            handle.write(json.dumps(action, ensure_ascii=True) + "\n")
    return persisted


async def _drain_human_actions(agent, page: Any) -> list[dict[str, Any]]:
    """Persist redacted actions collected from every open page."""
    if not agent.human_loop_enabled or not agent.human_action_log_path:
        return []

    actions = list(agent._human_action_buffer)
    agent._human_action_buffer.clear()
    pages = agent._playback_pages(page)
    for candidate_page in pages:
        for frame in list(getattr(candidate_page, "frames", [])):
            try:
                frame_actions = await frame.evaluate(
                    """() => {
                        const values = Array.isArray(window.__ewHumanActions)
                            ? window.__ewHumanActions.splice(0)
                            : [];
                        return values;
                    }"""
                )
            except Exception:
                continue
            if not isinstance(frame_actions, list):
                continue
            for action in frame_actions:
                if not isinstance(action, dict):
                    continue
                action.pop("value", None)
                action.pop("input_value", None)
                action["page_url"] = str(
                    action.pop("captured_page_url", "")
                    or getattr(candidate_page, "url", "")
                )
                action["frame_url"] = str(getattr(frame, "url", ""))
                action["handoff"] = agent._human_handoff_count
                captured_at = float(action.get("captured_at") or 0)
                if captured_at >= agent._last_human_action_at:
                    agent._last_human_action_page = candidate_page
                    agent._last_human_action_at = captured_at
                actions.append(action)
    return agent._persist_human_actions(actions)


async def _clear_human_action_queue(agent, page: Any) -> None:
    """Discard automation clicks collected before the human baton is handed over."""
    if not agent.human_loop_enabled:
        return
    agent._human_action_buffer.clear()
    agent._human_action_seen.clear()
    for candidate_page in agent._playback_pages(page):
        for frame in list(getattr(candidate_page, "frames", [])):
            try:
                await frame.evaluate(
                    """() => {
                        if (Array.isArray(window.__ewHumanActions)) {
                            window.__ewHumanActions.splice(0);
                        }
                    }"""
                )
            except Exception:
                continue


def _human_workflow_stage(stage: str) -> str:
    if stage in {"candidate", "event_selection"}:
        return "event_selection"
    return stage


def _is_human_playback_click(action: dict[str, Any]) -> bool:
    """Recognize an unlabeled player click from legacy and new action logs."""
    if str(action.get("type") or "").lower() != "click":
        return False
    labels = " ".join(
        str(action.get(key) or "").strip()
        for key in ("text", "aria_label", "title", "href")
    ).strip()
    page_url = str(action.get("page_url") or action.get("frame_url") or "")
    if not is_webcast_player_url(page_url):
        return False
    if bool(action.get("icon_control")):
        return True
    # Older human-loop logs only retained `button` for an icon-only control.
    return not labels and str(action.get("selector_hint") or "").lower() in {
        "button",
        "div",
        "span",
    }


def _human_workflow_return_stage(
    agent,
    requested_stage: str,
    assessment: HumanPageAssessment,
    actions: list[dict[str, Any]],
) -> str:
    """Promote a successful player click separately from event navigation."""
    normalized_stage = agent._human_workflow_stage(requested_stage)
    if normalized_stage != "event_selection":
        return normalized_stage
    if assessment.state in {"player", "playback"} and any(
        agent._is_human_playback_click(action) for action in actions
    ):
        return "playback"
    return normalized_stage


def _human_workflow_steps(agent, handoff: int) -> list[dict[str, Any]]:
    """Return replayable actions in the order the operator performed them."""
    steps: list[dict[str, Any]] = []
    for action in agent._human_actions_by_handoff.get(handoff, []):
        if action.get("type") != "click":
            continue
        selector = str(action.get("selector_hint") or "").strip()
        text_value = str(action.get("text") or "").strip()
        aria_label = str(action.get("aria_label") or "").strip()
        title = str(action.get("title") or "").strip()
        href = str(action.get("href") or "").strip()
        if not any((selector, text_value, aria_label, title, href)):
            continue
        steps.append(
            {
                "type": "click",
                "selector": selector,
                "text": text_value[:240],
                "aria_label": aria_label[:240],
                "title": title[:240],
                "href": href[:1000],
                "context_text": str(action.get("context_text") or "")[:500],
                "page_url": str(action.get("page_url") or "")[:1000],
                "frame_url": str(action.get("frame_url") or "")[:1000],
                "element_path": str(action.get("element_path") or "")[:1600],
                "player_context": str(action.get("player_context") or "")[:300],
                "icon_control": bool(action.get("icon_control")),
                "rect": action.get("rect") if isinstance(action.get("rect"), dict) else None,
                "captured_at": action.get("captured_at"),
            }
        )
    return steps


async def _classify_human_page(agent, page: Any) -> HumanPageAssessment:
    """Re-enter automation from the page where the operator actually worked."""
    await agent._wait_for_dynamic_page(page)
    await agent.accept_cookie_banners(page)

    access_barrier = await agent._detect_access_barrier(page)
    if access_barrier:
        return HumanPageAssessment("access_blocked", access_barrier)

    non_earnings = await agent._detect_non_earnings_event(page)
    training_proxy_reason = (
        f"non-earnings replay training proxy: {non_earnings}"
        if non_earnings and agent.lifecycle == "replay"
        else None
    )
    if non_earnings and not training_proxy_reason:
        return HumanPageAssessment("non_earnings", non_earnings)

    registration_barrier = await agent._detect_registration_barrier(page)
    if registration_barrier:
        return HumanPageAssessment(
            "registration_blocked",
            training_proxy_reason or registration_barrier,
        )
    if await agent.has_registration_form(page):
        return HumanPageAssessment("registration", training_proxy_reason)

    active_reason = await agent.detect_active_playback(
        page,
        include_context_pages=False,
    )
    if active_reason:
        return HumanPageAssessment(
            "playback",
            training_proxy_reason or active_reason,
        )
    if is_direct_player_url(str(page.url)) or await agent._has_visible_media_element(
        page,
        include_context_pages=False,
    ):
        return HumanPageAssessment("player", training_proxy_reason)
    if non_earnings:
        return HumanPageAssessment("non_earnings", non_earnings)
    if await agent._page_has_earnings_context(page):
        return HumanPageAssessment("earnings_event")
    return HumanPageAssessment("unknown")


def _workflow_checkpoint_succeeded(
    stage: str,
    assessment: HumanPageAssessment,
    steps: list[dict[str, Any]],
) -> bool:
    stage = _human_workflow_stage(stage)
    labels = " ".join(
        str(step.get(key) or "")
        for step in steps
        for key in ("text", "aria_label", "title", "context_text")
    )
    explicit_non_earnings = non_earnings_event_reason(labels)
    explicit_earnings = bool(EARNINGS_EVENT_CONTEXT_PATTERN.search(labels))

    if stage == "event_selection":
        if assessment.state == "non_earnings":
            return False
        if str(assessment.reason or "").startswith(
            "non-earnings replay training proxy:"
        ):
            return False
        if explicit_non_earnings and not explicit_earnings:
            return False
        return assessment.state in {
            "registration",
            "registration_blocked",
            "player",
            "playback",
            "earnings_event",
        }
    if stage == "registration":
        return assessment.state in {"player", "playback", "earnings_event"}
    if stage == "playback":
        # A human click on an icon-only player control is useful even when
        # the browser-side media probe cannot confirm audio yet. The
        # saved workflow will replay the click, while the normal OS audio
        # check remains the final success gate.
        return assessment.state in {"player", "playback"}
    if stage == "access":
        return assessment.state != "access_blocked"
    return assessment.state not in {"unknown", "access_blocked", "non_earnings"}


async def _checkpoint_human_workflow(
    agent,
    *,
    stage: str,
    source_url: str,
    page: Any,
) -> HumanPageAssessment:
    """Promote each solved segment without waiting for final audio success."""
    actions = list(agent._human_actions_by_handoff.get(agent._human_handoff_count, []))
    steps = agent._human_workflow_steps(agent._human_handoff_count)
    assessment = await agent._classify_human_page(page)
    normalized_stage = agent._human_workflow_return_stage(
        stage,
        assessment,
        actions,
    )
    pending = {
        "stage": normalized_stage,
        "source_url": source_url,
        "destination_url": str(page.url),
        "steps": steps,
        "assessment": assessment.state,
        "reason": assessment.reason,
    }
    agent._pending_human_workflows[normalized_stage] = pending
    print(
        f"[{agent.ticker}] HUMAN_RESUME_CLASSIFIED stage={normalized_stage} "
        f"state={assessment.state} url={pending['destination_url']}",
        flush=True,
    )
    if steps and agent._workflow_checkpoint_succeeded(
        normalized_stage,
        assessment,
        steps,
    ):
        agent._save_human_workflow(pending)
    else:
        print(
            f"[{agent.ticker}] HUMAN_WORKFLOW_PENDING stage={normalized_stage} "
            f"steps={len(steps)} state={assessment.state}",
            flush=True,
        )
    return assessment


def _promote_pending_human_workflows(
    agent,
    assessment: HumanPageAssessment,
) -> None:
    for stage, pending in list(agent._pending_human_workflows.items()):
        steps = list(pending.get("steps") or [])
        if not steps or not agent._workflow_checkpoint_succeeded(
            stage,
            assessment,
            steps,
        ):
            continue
        pending["assessment"] = assessment.state
        pending["reason"] = assessment.reason
        agent._save_human_workflow(pending)


def _save_human_workflow(agent, pending: dict[str, Any]) -> int | None:
    steps = list(pending.get("steps") or [])
    if not steps:
        return None
    source_url = str(
        next(
            (
                step.get("page_url")
                for step in steps
                if domain_for_url(str(step.get("page_url") or ""))
            ),
            None,
        )
        or pending.get("source_url")
        or agent.ir_url
    )
    selectors = tuple(
        f"{index}:{step.get('selector') or step.get('text') or step.get('href')}"
        for index, step in enumerate(steps)
    )
    last_step = steps[-1]
    last_href = str(last_step.get("href") or "")
    recipe = WebcastRecipe(
        domain=domain_for_url(source_url),
        selectors=selectors,
        frame_hostname=None,
        target_text=str(
            last_step.get("text")
            or last_step.get("aria_label")
            or last_step.get("title")
            or ""
        )[:500],
        target_href_path=urlparse(last_href).path or None if last_href else None,
        strategy="human_workflow",
        lifecycle=agent.lifecycle,
        confidence=0.90,
        evidence={
            "workflow_stage": str(pending.get("stage") or ""),
            "steps": steps,
            "source_url": source_url,
            "destination_url": str(pending.get("destination_url") or ""),
            "checkpoint_state": str(pending.get("assessment") or ""),
            "checkpoint_reason": pending.get("reason"),
            "learned_at": time.time(),
        },
        stage=str(pending.get("stage") or "event_selection"),
    )
    recipe.recipe_id = agent._save_recipe(recipe)
    if not recipe.recipe_id:
        return None
    try:
        try:
            from .... import database
        except ImportError:
            from data_pipeline import database

        database.record_webcast_recipe_outcome(recipe.recipe_id, success=True)
    except Exception as exc:
        print(
            f"[{agent.ticker}] human workflow checkpoint save skipped: {str(exc)[:120]}",
            flush=True,
        )
        return None
    agent._pending_human_workflows.pop(recipe.stage, None)
    print(
        f"[{agent.ticker}] HUMAN_WORKFLOW_LEARNED stage={recipe.stage} "
        f"steps={len(steps)} recipe_id={recipe.recipe_id}",
        flush=True,
    )
    return recipe.recipe_id


def _latest_context_page(page: Any) -> Any:
    try:
        for candidate in reversed(page.context.pages):
            try:
                if not candidate.is_closed() and candidate.url not in {"", "about:blank"}:
                    return candidate
            except Exception:
                continue
    except Exception:
        pass
    return page


def _usable_context_pages(page: Any) -> list[Any]:
    pages: list[Any] = []
    try:
        candidates = list(page.context.pages)
    except Exception:
        candidates = [page]
    for candidate in candidates:
        try:
            if candidate.is_closed() or candidate.url in {"", "about:blank"}:
                continue
        except Exception:
            continue
        pages.append(candidate)
    return pages


def _human_return_target_page(
    agent,
    page: Any,
    pages_before_handoff: set[int],
) -> Any:
    """Select a new tab, otherwise the tab that received the last human action."""
    pages = agent._usable_context_pages(page)
    new_pages = [
        candidate
        for candidate in pages
        if id(candidate) not in pages_before_handoff
        and not is_nonessential_popup_url(str(candidate.url))
    ]
    if new_pages:
        return new_pages[-1]

    action_page = agent._last_human_action_page
    if action_page is not None:
        try:
            if not action_page.is_closed() and action_page in pages:
                return action_page
        except Exception:
            pass
    return agent._latest_context_page(page)


def _page_after_human_handoff(agent, fallback: Any) -> Any:
    page = agent._human_return_page
    agent._human_return_page = None
    if page is not None:
        try:
            if not page.is_closed():
                return page
        except Exception:
            pass
    return agent._latest_context_page(fallback)


def _write_human_handoff(agent, payload: dict[str, Any]) -> None:
    if not agent.human_handoff_path:
        return
    agent.human_handoff_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = agent.human_handoff_path.with_suffix(
        f"{agent.human_handoff_path.suffix}.tmp"
    )
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(agent.human_handoff_path)


async def _human_handoff(agent, page: Any, *, stage: str, reason: str) -> bool:
    """Pause automation while a user resolves the current web obstacle."""
    if not agent.human_loop_enabled or not agent.human_resume_path:
        return False

    agent._human_handoff_count += 1
    await agent._clear_human_action_queue(page)
    agent._human_actions_by_handoff[agent._human_handoff_count] = []
    agent._last_human_action_page = None
    agent._last_human_action_at = 0.0
    agent._human_return_page = None
    pages_before_handoff = {
        id(candidate) for candidate in agent._usable_context_pages(page)
    }
    source_url = str(page.url)
    agent._human_capture_active = True
    payload = {
        "status": "waiting_for_human",
        "ticker": agent.ticker,
        "stage": stage,
        "reason": reason[:500],
        "url": str(page.url),
        "handoff": agent._human_handoff_count,
        "created_at": time.time(),
    }
    agent._write_human_handoff(payload)
    print(
        f"[{agent.ticker}] HUMAN_HANDOFF stage={stage} "
        f"handoff={agent._human_handoff_count} reason={reason[:180]} url={page.url}",
        flush=True,
    )

    deadline = asyncio.get_running_loop().time() + agent.human_handoff_timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        await agent._drain_human_actions(page)
        if agent.human_resume_path.exists():
            try:
                agent.human_resume_path.unlink(missing_ok=True)
            except OSError:
                pass
            await agent._drain_human_actions(page)
            agent._human_capture_active = False
            latest_page = agent._human_return_target_page(
                page,
                pages_before_handoff,
            )
            agent._human_return_page = latest_page
            assessment = await agent._checkpoint_human_workflow(
                stage=stage,
                source_url=source_url,
                page=latest_page,
            )
            # Preserve a session the user has legitimately completed so a
            # later automated replay can continue from the same state.
            await agent._save_storage_state(latest_page.context)
            payload["status"] = "human_returned"
            payload["returned_at"] = time.time()
            payload["returned_url"] = str(latest_page.url)
            payload["page_state"] = assessment.state
            agent._write_human_handoff(payload)
            print(
                f"[{agent.ticker}] HUMAN_BATON_RETURNED stage={stage} "
                f"handoff={agent._human_handoff_count} "
                f"state={assessment.state} url={latest_page.url}",
                flush=True,
            )
            agent._page_barrier = await agent._detect_access_barrier(latest_page)
            return True
        await asyncio.sleep(0.5)

    payload["status"] = "timed_out"
    payload["timed_out_at"] = time.time()
    agent._human_capture_active = False
    agent._write_human_handoff(payload)
    print(
        f"[{agent.ticker}] HUMAN_HANDOFF_TIMEOUT stage={stage} "
        f"timeout={agent.human_handoff_timeout_seconds:g}s",
        flush=True,
    )
    return False
