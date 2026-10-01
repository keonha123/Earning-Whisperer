"""Explicit provider-common actions applied only inside a verified current event.

Evidence schema: scope='provider_common', domain, stage, preconditions=[{kind:
'visible', target:{label:'Email'}}], steps=[{action:'fill', target:{label:'Email'},
profile_field:'email'}], postconditions=[{kind:'registration_complete', target:
{role:'button',name:'Play'}}]. Playback requires a media_progress postcondition.
Only semantic targets are accepted; URLs, old selectors and saved input values
cannot become actions. Existing replay recipes are never promoted implicitly.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse


PROFILE_FIELDS = frozenset({
    "email", "first_name", "last_name", "full_name", "company", "phone_number",
    "country", "city", "state", "job_title", "occupation", "industry_affiliation",
    "attendee_type", "other_option",
})
ROLES = frozenset({"button", "textbox", "combobox", "listbox", "checkbox"})
EVENT_LITERAL = re.compile(r"https?://|@|\b20\d{2}\b|\bq[1-4]\b|[?&](?:ei|eventid|token)=", re.I)


def _valid_target(target: object) -> bool:
    if not isinstance(target, dict):
        return False
    if set(target) == {"label"}:
        values = [target["label"]]
    elif set(target) == {"role", "name"} and isinstance(target["role"], str) and target["role"] in ROLES:
        values = [target["name"]]
    elif set(target) == {"media"} and isinstance(target["media"], str) and target["media"] in {"audio", "video"}:
        return True
    else:
        return False
    return all(isinstance(value, str) and 0 < len(value) <= 160 and not EVENT_LITERAL.search(value) for value in values)


def valid_provider_recipe(recipe, *, stage: str, hostname: str) -> bool:
    evidence = getattr(recipe, "evidence", None)
    if not isinstance(evidence, dict) or stage not in {"registration", "playback"}:
        return False
    if (evidence.get("scope") != "provider_common" or evidence.get("domain") != hostname
            or recipe.domain != hostname or recipe.stage != stage
            or evidence.get("stage", evidence.get("workflow_stage")) != stage
            or getattr(recipe, "target_href_path", None)):
        return False
    # Old event selectors are not a fallback for these reviewed semantic steps.
    if any(EVENT_LITERAL.search(str(value)) or "href" in str(value).lower()
           for value in getattr(recipe, "selectors", ())):
        return False
    preconditions, postconditions, steps = (
        evidence.get("preconditions"), evidence.get("postconditions"), evidence.get("steps"),
    )
    if not all(isinstance(items, list) and 0 < len(items) <= 20 for items in (preconditions, postconditions, steps)):
        return False
    for condition in preconditions + postconditions:
        if (not isinstance(condition, dict) or set(condition) != {"kind", "target"}
                or not isinstance(condition["kind"], str)
                or condition["kind"] not in {"visible", "hidden", "registration_complete", "media_progress"}
                or not _valid_target(condition["target"])):
            return False
    if any(condition["kind"] != "visible" for condition in preconditions):
        return False
    required = "registration_complete" if stage == "registration" else "media_progress"
    if not any(condition["kind"] == required for condition in postconditions):
        return False
    for step in steps:
        if not isinstance(step, dict) or not _valid_target(step.get("target")):
            return False
        action = step.get("action")
        if not isinstance(action, str):
            return False
        allowed_keys = {"action", "target", "profile_field"} if action in {"fill", "select"} else {"action", "target"}
        if set(step) != allowed_keys or action not in {"click", "fill", "select", "unmute"}:
            return False
        if action in {"fill", "select"} and (stage != "registration" or not isinstance(step["profile_field"], str) or step["profile_field"] not in PROFILE_FIELDS):
            return False
        if action == "unmute" and (stage != "playback" or "media" not in step["target"]):
            return False
        if action == "click" and step["target"].get("role") != "button":
            return False
    if stage == "registration":
        click_indexes = [index for index, step in enumerate(steps) if step["action"] == "click"]
        if click_indexes != [len(steps) - 1]:
            return False  # A reviewed registration performs exactly one final submit.
    return True


async def _matching_targets(page, target: dict, hostname: str):
    matches = []
    for frame in page.frames:
        ancestor = frame
        for _ in range(8):
            if ancestor is None or str(ancestor.url) not in {"about:blank", "about:srcdoc"}:
                break
            ancestor = ancestor.parent_frame
        if ancestor is None or (urlparse(str(ancestor.url)).hostname or "").lower() != hostname:
            continue
        if "label" in target:
            locator = frame.get_by_label(target["label"], exact=True)
        elif "media" in target:
            locator = frame.locator(target["media"])
        else:
            locator = frame.get_by_role(target["role"], name=target["name"], exact=True)
        for index in range(min(await locator.count(), 3)):
            element = locator.nth(index)
            if await element.is_visible():
                matches.append(element)
    return matches


async def _unique_target(page, target: dict, hostname: str):
    matches = await _matching_targets(page, target, hostname)
    return matches[0] if len(matches) == 1 else None


async def _condition(agent, page, condition: dict, hostname: str) -> bool:
    matches = await _matching_targets(page, condition["target"], hostname)
    target = matches[0] if len(matches) == 1 else None
    kind = condition["kind"]
    if kind == "hidden":
        return not matches
    if target is None:
        return False
    if kind == "registration_complete":
        return not await agent.has_registration_form(page, wait_seconds=0)
    if kind == "media_progress":
        first = await target.evaluate("el => el instanceof HTMLMediaElement ? {time:el.currentTime,paused:el.paused,ended:el.ended,muted:el.muted,volume:el.volume} : null")
        if not first or first["paused"] or first["ended"] or first["muted"] or first["volume"] <= 0:
            return False
        await asyncio.sleep(0.25)
        return bool(await target.evaluate("(el, start) => !el.paused && !el.ended && !el.muted && el.volume > 0 && el.currentTime > start + 0.05", first["time"]))
    return kind == "visible"


async def apply_provider_steps(agent, page: Any, recipe, *, stage: str) -> tuple[Any, bool]:
    """Return true only after this event's stage checkpoint is observed."""
    hostname = (urlparse(str(page.url)).hostname or "").lower()
    if (getattr(agent, "discovery_only", False) or getattr(agent, "lifecycle", "") != "live"
            or not valid_provider_recipe(recipe, stage=stage, hostname=hostname)
            or not await agent._validate_live_target_page(page)):
        return page, False
    evidence = recipe.evidence
    prepared_fields = [step["profile_field"] for step in evidence["steps"] if "profile_field" in step]
    if stage == "registration":
        from .registration import _registration_approval_error
        if (getattr(agent, "registration_preview_only", False)
                or _registration_approval_error(agent, str(page.url), prepared_fields, False)):
            return page, False
        if getattr(agent, "_provider_registration_pending", False):
            return page, False
    attempts = getattr(agent, "_provider_step_attempts", set())
    key = (getattr(recipe, "recipe_id", None) or repr(evidence), stage, str(page.url))
    if key in attempts:
        return page, False
    transition = None
    initial_page = page
    pages_before = tuple(page.context.pages)
    try:
        if not all([await _condition(agent, page, item, hostname) for item in evidence["preconditions"]]):
            return page, False
        # Validate all current profile references before partially filling a form.
        if any(not str(getattr(agent.profile, field, "") or "").strip() for field in prepared_fields):
            return page, False
        attempts.add(key)
        agent._provider_step_attempts = attempts
        for step in evidence["steps"]:
            if ((urlparse(str(page.url)).hostname or "").lower() != hostname
                    or not await agent._validate_live_target_page(page)):
                return page, False
            target = await _unique_target(page, step["target"], hostname)
            if target is None:
                return page, False
            action = step["action"]
            if action == "fill":
                await target.fill(str(getattr(agent.profile, step["profile_field"])), timeout=3000)
            elif action == "select":
                await target.select_option(label=str(getattr(agent.profile, step["profile_field"])), timeout=3000)
            elif action == "unmute":
                await target.evaluate("el => { if (el instanceof HTMLMediaElement) { el.muted = false; el.volume = 1; } }")
            else:
                if await target.evaluate("el => Boolean(el.closest('a[href]'))"):
                    return page, False
                if stage == "registration":
                    from .registration import _click_registration_control_once
                    from .navigation import begin_registration_transition
                    transition = await begin_registration_transition(agent, page)
                    # A dispatched JS or native submit may still be processing.
                    # Generic registration must not resubmit it on a timeout.
                    if not await _click_registration_control_once(page, target):
                        return page, False
                    agent._provider_registration_pending = True
                else:
                    await target.click(timeout=3000)
        deadline = asyncio.get_running_loop().time() + min(15, max(1, float(getattr(agent, "provider_steps_wait_seconds", 5))))
        while asyncio.get_running_loop().time() < deadline:
            candidates = [page]
            if stage == "registration":
                for candidate in page.context.pages:
                    if candidate not in pages_before and await candidate.opener() is initial_page:
                        candidates.append(candidate)
            for candidate in candidates:
                if ((urlparse(str(candidate.url)).hostname or "").lower() != hostname
                        or not all([await _condition(agent, candidate, condition, hostname) for condition in evidence["postconditions"]])):
                    continue
                if stage == "registration":
                    from .navigation import finish_registration_transition
                    await finish_registration_transition(agent, transition, candidate, True)
                if await agent._validate_live_target_page(candidate):
                    if stage == "registration":
                        agent._provider_registration_pending = False
                    return candidate, True
            await asyncio.sleep(0.2)
    except Exception:
        # Existing generic provider handling owns fallback; never log profile data.
        return page, False
    finally:
        if transition is not None:
            from .navigation import finish_registration_transition
            await finish_registration_transition(agent, transition, page, False)
    return page, False
