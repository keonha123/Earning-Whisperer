"""Provider registration forms, consent and submission."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any
from data_pipeline.live_telemetry import emit_live_event
from .form_controls import is_structured_choice, select_custom_option
from .form_validation import collect_registration_validation, registration_transition_state
from .rules import (
    ALREADY_REGISTERED_PATTERN,
    HumanPageAssessment,
    Q4_EVENT_GATE_PATTERN,
    REGISTRATION_EMAIL_ERROR_PATTERN,
    REGISTRATION_FORM_CONTAINER_SELECTORS,
    REGISTRATION_FORM_TEXT_PATTERN,
    SUBSCRIPTION_PAGE_PATTERN,
    WEBCASTS_REGISTRATION_FIELD_SELECTORS,
    WEBCASTS_REGISTRATION_FORM_SELECTOR,
    WEBCASTS_REGISTRATION_SUBMIT_SELECTOR,
    domain_for_url,
    is_existing_webinar_login_surface,
    is_open_exchange_registration_url,
    is_positive_registration_consent_text,
    is_q4_custom_registration_text,
    is_q4_followup_registration_text,
    is_q4_guest_registration_text,
    redact_registration_url,
    registration_url_identity,
)


async def _click_registration_control_once(page: Any, control: Any) -> bool:
    """Dispatch one submission, including a native fallback only before dispatch.

    A visible form and an unchanged URL are normal for an AJAX registration.
    They are not evidence that a delivered click should be repeated. Keep the
    original element handle so a rerender cannot redirect the fallback to a
    different button. A timeout after a click/submit/request is still pending,
    not permission to submit the same form again.
    """
    handle = await control.element_handle()
    if handle is None:
        return False
    source_url = str(page.url)
    context = getattr(page, "context", None)
    pages_before = tuple(context.pages) if context is not None else ()
    write_requested = False

    def observe_request(request: Any) -> None:
        nonlocal write_requested
        if str(request.method).upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            write_requested = True

    await handle.evaluate("""element => {
        const state = {clicked: false, submitted: false, invalid: false};
        const form = element.form;
        state.onClick = () => { state.clicked = true; };
        state.onSubmit = () => { state.submitted = true; };
        state.onInvalid = () => { state.invalid = true; };
        state.form = form;
        element.addEventListener('click', state.onClick, true);
        if (form) {
            form.addEventListener('submit', state.onSubmit, true);
            form.addEventListener('invalid', state.onInvalid, true);
        }
        element.__ewRegistrationAttempt = state;
    }""")
    page.on("request", observe_request)
    try:
        try:
            await handle.click(force=True, timeout=8000)
            return True
        except Exception:
            if write_requested or str(page.url) != source_url:
                return True
            if context is not None and any(p not in pages_before for p in context.pages):
                return True
            # The fallback itself checks observation and submitter type in the
            # same DOM turn. Never pass type=button, a detached control, or a
            # replacement form to requestSubmit, and never use form.submit().
            try:
                return bool(await handle.evaluate("""element => {
                    const state = element.__ewRegistrationAttempt;
                    if (!state) return false;
                    if (state.clicked || state.submitted) return true;
                    if (state.invalid || !element.isConnected || element.disabled) return false;
                    const form = element.form;
                    const nativeSubmitter = ['BUTTON', 'INPUT'].includes(element.tagName)
                        && element.type === 'submit';
                    if (!nativeSubmitter || !form || form !== state.form
                        || typeof form.requestSubmit !== 'function'
                        || !form.checkValidity()) return false;
                    form.requestSubmit(element);
                    return state.submitted;
                }"""))
            except Exception:
                # A navigation can destroy the document during observation;
                # never guess that it is safe to send a second request.
                return False
    finally:
        page.remove_listener("request", observe_request)
        try:
            await handle.evaluate("""element => {
                const state = element.__ewRegistrationAttempt;
                if (!state) return;
                element.removeEventListener('click', state.onClick, true);
                if (state.form) {
                    state.form.removeEventListener('submit', state.onSubmit, true);
                    state.form.removeEventListener('invalid', state.onInvalid, true);
                }
                delete element.__ewRegistrationAttempt;
            }""")
        except Exception:
            pass


async def _wait_registration_outcome(
    agent: Any,
    owner_page: Any,
    root: Any,
    *,
    source_url: str,
    pages_before: tuple = (),
    source_body: str = '',
    timeout_error_type: type[Exception] = Exception,
    submission_depth: int = 0,
    allow_consent_continuation: bool = True,
) -> bool:
    """Observe the single dispatched submission; never click it again.

    URL changes and new tabs provide candidates, not acceptance evidence.
    Form errors, player readiness and waiting rooms are inspected in the
    candidate's own frame tree. Each recognized Q4 step may be filled once.
    """
    try:
        wait_seconds = max(1.0, min(60.0, float(os.getenv(
            'WEBCAST_REGISTRATION_POST_SUBMIT_WAIT_SECONDS', '30'))))
    except ValueError:
        wait_seconds = 30.0
    deadline = asyncio.get_running_loop().time() + wait_seconds
    context = getattr(owner_page, 'context', None)
    attached = set()
    observed = set()
    last_reason = 'no_positive_transition'
    source_kind = ('custom' if is_q4_custom_registration_text(source_body) else
                   'followup' if is_q4_followup_registration_text(source_body) else 'other')
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.25)
        candidates = []
        if context is not None:
            try:
                candidates = [p for p in context.pages
                              if p not in pages_before and p is not owner_page and not p.is_closed()]
            except Exception:
                pass
        # A valid player popup may leave its original form untouched.
        for candidate in [*candidates, owner_page]:
            try:
                if candidate.is_closed():
                    continue
                if candidate is not owner_page:
                    if await candidate.opener() is not owner_page:
                        continue
                    if candidate not in attached:
                        agent._attach_media_watchers(candidate)
                        attached.add(candidate)
                if submission_depth < 2:
                    for target in (list(getattr(candidate, 'frames', ())) or [candidate])[:12]:
                        try:
                            body = await target.locator('body').inner_text(timeout=500)
                        except Exception:
                            continue
                        kind = ('custom' if is_q4_custom_registration_text(body) else
                                'followup' if is_q4_followup_registration_text(body) else 'other')
                        # A form still showing the same step is not a reason to
                        # submit it again. Only a different known step advances.
                        if kind != 'other' and kind != source_kind:
                            agent._registration_target_page = candidate
                            return await agent._fill_generic_registration_form(
                                target, timeout_error_type,
                                owner_page=candidate if target is not candidate else None,
                                submission_depth=submission_depth + 1,
                            )
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                result = await asyncio.wait_for(registration_transition_state(
                    agent, owner_page, candidate, source_url,
                    remaining_form_root=root if candidate is owner_page else None,
                    allow_consent_continuation=allow_consent_continuation,
                ), timeout=remaining)
            except asyncio.TimeoutError:
                last_reason = 'transition_observation_timeout'
                break
            except Exception:
                last_reason = 'transition_unavailable'
                continue
            state, reason = result['state'], result['reason']
            last_reason = reason
            key = (id(candidate), state, reason)
            if key not in observed:
                observed.add(key)
                emit_live_event(ticker=agent.ticker, stage='registration',
                                event='registration_transition', status=state,
                                details={'reason': reason, 'new_tab': candidate is not owner_page,
                                         **({'validation': result['validation']} if 'validation' in result else {})})
            if state == 'passed':
                agent._registration_target_page = candidate
                agent._registration_failure_error = None
                return True
            if state == 'failed':
                # A rejected popup is diagnostic evidence, never success.
                if candidate is not owner_page:
                    continue
                prefix = 'AUTH_REQUIRED' if reason in {'access_blocked', 'registration_blocked'} else 'FORM_AUTOMATION_FAILED'
                agent._registration_failure_error = f'{prefix} registration rejected; reason={reason}'
                return False
    agent._registration_failure_error = (
        'FORM_AUTOMATION_FAILED registration submission did not transition; '
        f'reason={last_reason}'
    )
    emit_live_event(ticker=agent.ticker, stage='registration',
                    event='registration_transition_timeout', status='pending',
                    details={'reason': last_reason, 'wait_seconds': wait_seconds})
    return False


async def _commit_q4_company_lookup(root: Any, locator: Any, value: str) -> bool:
    """Commit the exact supplied company through Q4's visible directory UI.

    Q4 uses React Select DIV options without ARIA roles, with a 500 ms
    debounced lookup. Its explicit 'Enter "..." as Company Name' option
    preserves the supplied company; typing alone leaves companyName null.
    """
    expected = " ".join(value.split()).casefold()
    custom_label = f'enter "{expected}" as company name'
    max_options = 0
    max_visible_options = 0
    exact_matches = 0
    custom_matches = 0
    option_scope = "registration_root"
    scoped_option_count = 0

    async def report(step: str, **extra: Any) -> None:
        # Compare inside the page; never serialize company/input/option text.
        try:
            state = await locator.evaluate("""(element, expected) => {
                const norm = text => String(text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const section = element.closest('.event-registration-form_institution-section')
                    || element.closest('.nui-select') || element.parentElement.parentElement;
                const value = section?.querySelector('.nui-select__single-value');
                const label = value?.querySelector('.institution-select__option-name') || value;
                const wholeDocumentOptions = Array.from(document.querySelectorAll('.nui-select__option, [role="option"]'));
                return {
                    input_matches_profile: norm(element.value) === norm(expected),
                    input_empty: !element.value,
                    selected_exists: Boolean(value),
                    selected_matches: Boolean(label) && norm(label.textContent) === norm(expected),
                    document_option_count: wholeDocumentOptions.length,
                    document_visible_option_count: wholeDocumentOptions.filter(e => e.getBoundingClientRect().width && e.getBoundingClientRect().height).length,
                    aria_controls_present: Boolean(element.getAttribute('aria-controls')),
                    loading_indicator_count: document.querySelectorAll('.nui-select__loading-indicator').length,
                };
            }""", value)
        except Exception as exc:
            state = {"state_error_type": type(exc).__name__}
        emit_live_event("registration", "company_lookup_inspected", status="checking_form",
                        lookup_step=step, root_option_count=max_options,
                        root_visible_option_count=max_visible_options,
                        exact_match_count=exact_matches, custom_match_count=custom_matches,
                        option_scope=option_scope, scoped_option_count=scoped_option_count,
                        **state, **extra)

    try:
        await report("started")
        # Q4 portals its menu outside the form and supplies no aria-controls.
        # Establish ownership by closing the focused input's menu, requiring
        # no other open Q4 menu, then opening this same input's single menu.
        await locator.press("Escape")
        menu_page = locator.page
        visible_menus = menu_page.locator(".nui-select__menu:visible")
        had_no_open_menu = await visible_menus.count() == 0
        await locator.press("ArrowDown")
        await report("menu_opened")
        deadline = asyncio.get_running_loop().time() + 4.0
        while asyncio.get_running_loop().time() < deadline:
            options = root.locator(".nui-select__option, [role='option']")
            root_count = await options.count()
            max_options = max(max_options, root_count)
            if root_count == 0 and had_no_open_menu:
                focused = await locator.evaluate("element => element === document.activeElement")
                if focused and await visible_menus.count() == 1:
                    options = visible_menus.first.locator(".nui-select__option, [role='option']")
                    option_scope = "focused_company_menu"
                elif focused and await visible_menus.count() == 0:
                    # An async result can arrive after the first key event.
                    await locator.press("ArrowDown")
            scoped_option_count = await options.count()
            visible_options = 0
            for index in range(await options.count()):
                option = options.nth(index)
                if not await option.is_visible():
                    continue
                visible_options += 1
                max_visible_options = max(max_visible_options, visible_options)
                name = option.locator(".institution-select__option-name")
                text = await name.inner_text() if await name.count() == 1 else await option.inner_text()
                normalized = " ".join(text.split()).casefold()
                if normalized not in {expected, custom_label}:
                    continue
                exact_matches += int(normalized == expected)
                custom_matches += int(normalized == custom_label)
                await report("option_matched")
                await option.click(force=True)
                # The input is a search string and is cleared on selection.
                # Verify the resulting selected label, not the transient input.
                for _ in range(10):
                    selected = await locator.evaluate("""element => {
                        const section = element.closest('.event-registration-form_institution-section')
                            || element.closest('.nui-select') || element.parentElement.parentElement;
                        const value = section?.querySelector('.nui-select__single-value');
                        const label = value?.querySelector('.institution-select__option-name') || value;
                        return label?.textContent || '';
                    }""")
                    if " ".join(str(selected or "").split()).casefold() == expected:
                        await report("committed")
                        return True
                    await asyncio.sleep(0.1)
                await report("selection_not_committed")
                return False
            await asyncio.sleep(0.25)
        await report("no_matching_option")
        await locator.press("Escape")
        return False
    except Exception as exc:
        await report("lookup_exception", error_type=type(exc).__name__)
        return False


async def _try_provider_registration(agent, page: Any) -> bool | None:
    """Run explicit common recipes before generic filling, never after a POST.

    None means no common recipe completed or dispatched a submission, so the
    existing generic form handling remains applicable.
    """
    if getattr(agent, "lifecycle", "") != "live" or agent.registration_preview_only:
        return None
    if getattr(agent, "_provider_registration_pending", False):
        result = await registration_transition_state(agent, page, page, str(page.url))
        if result['state'] == 'passed':
            agent._provider_registration_pending = False
            agent._registration_target_page = page
            return True
        agent._registration_failure_error = (
            "FORM_AUTOMATION_FAILED provider registration rejected; reason=" + result['reason']
            if result['state'] == 'failed' else
            "REGISTRATION_PENDING provider submission is still processing; reason=" + result['reason']
        )
        return False
    from .learning import _load_verified_provider_steps
    from .provider_steps import apply_provider_steps

    for recipe in _load_verified_provider_steps(agent, page.url, stage="registration"):
        target, applied = await apply_provider_steps(agent, page, recipe, stage="registration")
        if applied:
            agent._registration_target_page = target
            return True
        if getattr(agent, "_provider_registration_pending", False):
            agent._registration_target_page = target
            agent._registration_failure_error = "REGISTRATION_PENDING provider submission is still processing"
            return False
    return None


def _registration_approval_error(
    agent,
    page_url: str,
    prepared_fields: list[str],
    consent_selected: bool,
) -> str | None:
    """Optionally require a per-ticker approval before POSTing."""
    if getattr(agent, "registration_preview_only", False) or getattr(agent, "discovery_only", False):
        return "REGISTRATION_PREVIEW registration submission not attempted"
    if not agent.allow_registration_submission:
        return "registration submission is disabled"
    if not agent.require_registration_approval:
        return None
    if not agent.registration_approval_file:
        return "REGISTRATION_APPROVAL_REQUIRED approval manifest is missing"
    approval = agent.registration_approval_manifest.get(agent.ticker)
    if not approval or approval.get("approved") is not True:
        return f"REGISTRATION_APPROVAL_REQUIRED {agent.ticker} is not approved"

    expected_url = registration_url_identity(approval.get("destination_url"))
    actual_url = registration_url_identity(page_url)
    if not expected_url or expected_url != actual_url:
        return "REGISTRATION_APPROVAL_REQUIRED destination does not match"

    expected_fields = {
        str(field).strip()
        for field in approval.get("prepared_fields", [])
        if str(field).strip()
    }
    actual_fields = {field for field in prepared_fields if field}
    if expected_fields != actual_fields:
        print(
            f"[{agent.ticker}] registration approval fields mismatch: "
            f"expected={sorted(expected_fields)} actual={sorted(actual_fields)}",
            flush=True,
        )
        return "REGISTRATION_APPROVAL_REQUIRED prepared fields do not match"

    if "consent_selected" in approval and bool(approval["consent_selected"]) != consent_selected:
        return "REGISTRATION_APPROVAL_REQUIRED consent state does not match"
    return None


async def fill_registration_form(agent, page: Any, timeout_error_type: type[Exception]) -> bool:
    from .diagnostics import capture_diagnostics
    await capture_diagnostics(agent, getattr(page, "context", page), "registration_before")
    if not agent.allow_registration_submission and not agent.registration_preview_only:
        agent._registration_failure_error = (
            "REGISTRATION_REQUIRED registration submission is disabled"
        )
        print(f"[{agent.ticker}] {agent._registration_failure_error}", flush=True)
        return False

    provider_result = await _try_provider_registration(agent, page)
    if provider_result is not None:
        return provider_result

    async def find_q4_custom_registration_target() -> tuple[Any, Any] | None:
        """Find Q4's delayed compact registration surface in any open tab."""
        for candidate_page in agent._playback_pages(page):
            for target in agent._registration_targets(candidate_page):
                try:
                    body_text = await target.locator("body").inner_text(timeout=1500)
                except Exception:
                    continue
                if not is_q4_custom_registration_text(body_text):
                    continue
                registration_target = await agent._find_registration_target(candidate_page)
                if registration_target is not None:
                    return candidate_page, registration_target
        return None

    # Q4 places the guest path on the same page as its account gate. The
    # gate is intentionally classified as a registration target, so this
    # must run before the generic-form branch below; otherwise the page is
    # treated as an empty form and the guest transition is skipped.
    guest_button = page.locator(
        "button:has-text('Continue as Guest'), "
        "button:has-text('Register as Guest'), "
        "button:has-text('Register as a Guest'), "
        "button:has-text('Continue without an account'), "
        "button:has-text('Continue without a Q4 account'), "
        "a:has-text('Continue as Guest'), "
        "a:has-text('Continue without an account'), "
        "a:has-text('Continue without a Q4 account')"
    ).first
    try:
        if await guest_button.count() > 0 and await guest_button.is_visible():
            print(f"[{agent.ticker}] using guest webcast registration", flush=True)
            await guest_button.click(force=True)
            await asyncio.sleep(1)
            registration_target = await agent._find_registration_target(page)
            if registration_target is not None:
                return await agent._fill_generic_registration_form(
                    registration_target,
                    timeout_error_type,
                    owner_page=page if registration_target is not page else None,
                )
            return True
    except Exception as exc:
        print(
            f"[{agent.ticker}] guest webcast transition skipped: {str(exc)[:120]}",
            flush=True,
        )

    # webinar.net shows already-registered attendees a compact email login
    # surface instead of reopening the registration form. The Attend action
    # can navigate in-place or open the player in a new tab, so preserve the
    # same target-page handling used by normal registration submission.
    if "webinar.net" in domain_for_url(str(getattr(page, "url", ""))):
        try:
            login_body = await page.locator("body").inner_text(timeout=1500)
        except Exception:
            login_body = ""
        if is_existing_webinar_login_surface(login_body):
            login_email = page.locator(
                "input[type='email'], "
                "input[placeholder*='email address' i], "
                "input[name*='email' i], "
                "input[id*='email' i]"
            ).first
            login_action = page.locator(
                "button:has-text('Attend'), "
                "button:has-text('Log In'), "
                "input[type='submit'][value*='Attend' i], "
                "input[type='button'][value*='Attend' i], "
                "[role='button']:has-text('Attend')"
            ).first
            if await login_email.count() > 0 and await login_action.count() > 0:
                if not agent.profile.email:
                    agent._registration_failure_error = (
                        "AUTH_REQUIRED webinar attendee email is missing"
                    )
                    print(f"[{agent.ticker}] {agent._registration_failure_error}", flush=True)
                    return False
                try:
                    guard = agent._registration_approval_error(page.url, ["email"], False)
                    if guard:
                        agent._registration_failure_error = guard
                        return False
                    await login_email.fill(agent.profile.email)
                    print(
                        f"[{agent.ticker}] using existing webinar attendee login",
                        flush=True,
                    )
                    source_url = str(page.url)
                    pages_before = tuple(page.context.pages)
                    if not await _click_registration_control_once(page, login_action):
                        agent._registration_failure_error = "FORM_AUTOMATION_FAILED attendee login was not dispatched"
                        return False
                    return await _wait_registration_outcome(
                        agent, page, page, source_url=source_url,
                        pages_before=pages_before, source_body=login_body,
                        timeout_error_type=timeout_error_type,
                    )
                except Exception as exc:
                    agent._registration_failure_error = (
                        f"webinar attendee login failed: {str(exc)[:120]}"
                    )
                    print(f"[{agent.ticker}] {agent._registration_failure_error}", flush=True)
                    return False

    # Q4 can reuse an already-registered session and show a compact
    # company-only form. Handle that field before the generic Q4 gate
    # clicks REGISTER FOR THIS EVENT with an empty value.
    q4_custom_target = await find_q4_custom_registration_target()
    if q4_custom_target is not None:
        owner_page, registration_target = q4_custom_target
        print(
            f"[{agent.ticker}] using Q4 company-only registration step",
            flush=True,
        )
        return await agent._fill_generic_registration_form(
            registration_target,
            timeout_error_type,
            owner_page=owner_page if registration_target is not owner_page else None,
        )

    # webinar.net and similar providers expose the form behind a separate
    # "Register Now" action. Treat that action as a registration step,
    # rather than waiting for a player that cannot exist before signup.
    register_now = page.locator("a, button").filter(
        has_text=re.compile(r"^\s*Register\s+Now\s*$", re.IGNORECASE)
    ).first
    try:
        if await register_now.count() > 0 and await register_now.is_visible():
            print(f"[{agent.ticker}] opening registration via Register Now", flush=True)
            await register_now.click(force=True)
            await asyncio.sleep(1)
            delayed_target = await agent._find_registration_target_across_pages(
                page,
                wait_seconds=8.0,
            )
            if delayed_target is not None:
                owner_page, registration_target = delayed_target
                return await agent._fill_generic_registration_form(
                    registration_target,
                    timeout_error_type,
                    owner_page=owner_page if registration_target is not owner_page else None,
                )
    except Exception as exc:
        print(
            f"[{agent.ticker}] Register Now transition skipped: {str(exc)[:120]}",
            flush=True,
        )

    registration_target = await agent._find_registration_target(page)
    if registration_target is None:
        delayed_target = await agent._find_registration_target_across_pages(
            page,
            wait_seconds=8.0,
        )
        if delayed_target is not None:
            owner_page, registration_target = delayed_target
            return await agent._fill_generic_registration_form(
                registration_target,
                timeout_error_type,
                owner_page=owner_page if registration_target is not owner_page else None,
            )
    if registration_target is not None:
        q4_custom_target = await find_q4_custom_registration_target()
        if q4_custom_target is not None:
            owner_page, registration_target = q4_custom_target
            print(
                f"[{agent.ticker}] using Q4 company-only registration step",
                flush=True,
            )
            return await agent._fill_generic_registration_form(
                registration_target,
                timeout_error_type,
                owner_page=owner_page if registration_target is not owner_page else None,
            )
        print(
            f"[{agent.ticker}] using generic registration form detection",
            flush=True,
        )
        return await agent._fill_generic_registration_form(
            registration_target,
            timeout_error_type,
            owner_page=page if registration_target is not page else None,
        )
    if registration_target is None and agent.media_candidates:
        print(
            f"[{agent.ticker}] provider media discovered without a registration "
            "form; continuing to playback",
            flush=True,
        )
        return True

    selectors = [
        WEBCASTS_REGISTRATION_FORM_SELECTOR,
        "button#registration-box_signup-button",
        "button:has-text('Register for event')",
        "a:has-text('Register for event')",
        "a:has-text('Register Now')",
        "button:has-text('Register Now')",
        "form#fmRegister",
        "form[action*='register' i]",
    ]
    registration_control_found = False
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = min(await locator.count(), 12)
                if any(
                    [
                        await locator.nth(index).is_visible()
                        for index in range(count)
                    ]
                ):
                    registration_control_found = True
                    break
            except Exception:
                continue
        if registration_control_found:
            break
        await asyncio.sleep(0.5)

    # Some event pages have a legal notice overlay but no registration
    # form. Dismiss it before the early return so player inspection can
    # continue on the unobstructed page.
    await agent.accept_cookie_banners(page)

    if not registration_control_found:
        if await agent.has_registration_form(page):
            print(
                f"[{agent.ticker}] using generic registration form detection",
                flush=True,
            )
            return await agent._fill_generic_registration_form(
                page,
                timeout_error_type,
            )
        print(
            f"[{agent.ticker}] no visible registration controls after 15s",
            flush=True,
        )
        return True

    try:
        guest_button = page.locator(
            "button:has-text('Continue as Guest'), "
            "button:has-text('Register as Guest'), "
            "button:has-text('Register as a Guest'), "
            "button:has-text('Continue without an account'), "
            "button:has-text('Continue without a Q4 account'), "
            "a:has-text('Continue as Guest'), "
            "a:has-text('Continue without an account'), "
            "a:has-text('Continue without a Q4 account')"
        ).first
        if await guest_button.count() > 0 and await guest_button.is_visible():
            print(f"[{agent.ticker}] using guest webcast registration", flush=True)
            await guest_button.click(force=True)
            await asyncio.sleep(1)
            return await agent._fill_generic_registration_form(
                page,
                timeout_error_type,
            )

        q4_gate_button = page.locator(
            "button#registration-box_signup-button, "
            "button:has-text('Register with a Q4 Account'), "
            "button:has-text('Register for event'), "
            "button:has-text('Register for this event'), "
            "input[type='submit'][value*='Register for this event' i], "
            "a:has-text('Register for event')"
        ).first
        if await q4_gate_button.count() > 0 and await q4_gate_button.is_visible():
            await q4_gate_button.click(force=True)
            try:
                await page.wait_for_selector("input#email", state="visible", timeout=10000)
            except timeout_error_type:
                if await agent.detect_active_playback(page):
                    return True
                if not await agent.has_registration_form(page):
                    return True

        q4_email_field = page.locator("input#email").first
        if await q4_email_field.count() > 0 and await q4_email_field.is_visible():
            if not agent.profile.q4_email:
                print(f"[{agent.ticker}] email field found but Q4_EMAIL/WEBCAST_EMAIL is missing")
                return False
            guard = agent._registration_approval_error(page.url, ["q4_email"], False)
            if guard:
                agent._registration_failure_error = guard
                return False
            await q4_email_field.fill(agent.profile.q4_email)
            next_button = page.locator("button").filter(
                has_text=re.compile(r"^Next$", re.IGNORECASE)
            ).first
            if await next_button.count() > 0 and await next_button.is_visible():
                if not await _click_registration_control_once(page, next_button):
                    agent._registration_failure_error = "FORM_AUTOMATION_FAILED email step was not dispatched"
                    return False
                await page.wait_for_selector("input#password", state="visible", timeout=10000)

        q4_password_field = page.locator("input#password").first
        if await q4_password_field.count() > 0 and await q4_password_field.is_visible():
            if not agent.profile.q4_password:
                print(
                    f"[{agent.ticker}] AUTH_REQUIRED "
                    "WEBCAST_PASSWORD/Q4_PASSWORD is missing",
                    flush=True,
                )
                return False
            guard = agent._registration_approval_error(page.url, ["q4_password"], False)
            if guard:
                agent._registration_failure_error = guard
                return False
            await q4_password_field.fill(agent.profile.q4_password)
            login_button = page.locator("button").filter(
                has_text=re.compile(r"^Log in$|Sign in", re.IGNORECASE)
            ).first
            if await login_button.count() > 0 and await login_button.is_visible():
                source_url = str(page.url)
                pages_before = tuple(page.context.pages)
                if not await _click_registration_control_once(page, login_button):
                    agent._registration_failure_error = "FORM_AUTOMATION_FAILED login was not dispatched"
                    return False
                await asyncio.sleep(1)
                return await _wait_registration_outcome(agent, page, page, source_url=source_url, pages_before=pages_before, timeout_error_type=timeout_error_type)

        return await agent._fill_generic_registration_form(
            page,
            timeout_error_type,
        )
    except Exception as exc:
        print(f"[{agent.ticker}] registration form handling error: {exc}")
        return False


async def handle_registration_form(
    agent,
    page: Any,
    timeout_error_type: type[Exception],
) -> bool:
    from .diagnostics import capture_diagnostics
    print(f"[{agent.ticker}] checking webcast registration", flush=True)
    emit_live_event("registration", "registration_started", status="checking_form",
                    ticker=agent.ticker, url=str(page.url))
    agent._registration_target_page = None
    agent._registration_failure_error = None
    success = False
    try:
        if (not agent.allow_registration_submission and not agent.registration_preview_only
                and await agent.has_registration_form(page)):
            agent._registration_failure_error = "REGISTRATION_REQUIRED registration submission is disabled"
            print(f"[{agent.ticker}] {agent._registration_failure_error}", flush=True)
            return False
        success = await asyncio.wait_for(
            agent.fill_registration_form(page, timeout_error_type),
            timeout=agent.registration_timeout_seconds,
        )
        return success
    except asyncio.TimeoutError:
        agent._registration_failure_error = "registration handling timed out"
        print(f"[{agent.ticker}] registration handling timed out after "
              f"{agent.registration_timeout_seconds:g}s", flush=True)
        return False
    finally:
        target = agent._registration_target_page or page
        artifact = await capture_diagnostics(agent, getattr(target, "context", target),
                                             "registration_after" if success else "registration_failed")
        emit_live_event("registration", "registration_completed", status="passed" if success else "failed",
                        progress=bool(success), ticker=agent.ticker, url=str(target.url),
                        error=agent._registration_failure_error, artifact_path=artifact)


def _registration_error(agent) -> str:
    return agent._registration_failure_error or "registration form handling failed"


async def _resolve_registration_barrier_with_human(
    agent,
    page: Any,
) -> tuple[str | None, Any]:
    current_page = page
    barrier = await agent._detect_registration_barrier(current_page)
    for _ in range(agent.human_retry_limit):
        if not barrier:
            return None, current_page
        if not await agent._human_handoff(
            current_page,
            stage="registration",
            reason=f"등록폼 접근이 막혔습니다: {barrier}",
        ):
            break
        current_page = agent._page_after_human_handoff(current_page)
        barrier = await agent._detect_registration_barrier(current_page)
    return barrier, current_page


async def _complete_registration_with_human(
    agent,
    page: Any,
    timeout_error_type: type[Exception],
) -> tuple[bool, Any]:
    """Fill registration, returning to the same stage after each human assist."""
    agent._promote_pending_human_workflows(HumanPageAssessment("registration"))
    current_page = page
    form_success = await agent.handle_registration_form(
        current_page,
        timeout_error_type,
    )
    current_page = agent._registration_target_page or current_page
    for _ in range(agent.human_retry_limit):
        if form_success:
            return True, current_page
        if not await agent._human_handoff(
            current_page,
            stage="registration",
            reason=agent._registration_error(),
        ):
            break
        current_page = agent._page_after_human_handoff(current_page)
        assessment = await agent._classify_human_page(current_page)
        agent._promote_pending_human_workflows(assessment)
        if assessment.state in {"player", "playback", "earnings_event"}:
            return True, current_page
        if not await agent.has_registration_form(current_page):
            # Some providers briefly show an empty redirect shell before the
            # player tab appears. Let the playback dispatcher perform the
            # definitive check instead of submitting the old form again.
            return True, current_page
        form_success = await agent.handle_registration_form(
            current_page,
            timeout_error_type,
        )
        current_page = agent._registration_target_page or current_page
    return form_success, current_page


async def _submit_metameetings_privacy_consent(agent, page: Any) -> bool:
    """Submit MetaMeetings' post-login privacy choice without opting in."""
    if (not agent.allow_privacy_consent_submission
            or getattr(agent, "registration_preview_only", False)
            or getattr(agent, "discovery_only", False)):
        return False
    if "metameetings.net" not in domain_for_url(str(getattr(page, "url", ""))):
        return False

    privacy_pattern = re.compile(
        r"map\s+digital.*privacy\s+and\s+data\s+policy|"
        r"submit\s+your\s+consent|audio\s+stream\s+of\s+this\s+session",
        re.IGNORECASE | re.DOTALL,
    )
    for frame in page.frames:
        try:
            body_text = (await frame.locator("body").inner_text(timeout=2000))[:6000]
        except Exception:
            continue
        if not privacy_pattern.search(body_text):
            continue

        radios = frame.locator("input[type='radio']")
        radio_count = await radios.count()
        selected = False
        opt_out = None
        for index in range(radio_count):
            radio = radios.nth(index)
            try:
                metadata = await radio.evaluate(
                    """element => {
                        const parts = [
                            element.value,
                            element.name,
                            element.id,
                            element.getAttribute('aria-label'),
                            element.getAttribute('title'),
                        ];
                        if (element.id) {
                            const label = document.querySelector(
                                `label[for="${CSS.escape(element.id)}"]`
                            );
                            if (label) parts.push(label.innerText || label.textContent || '');
                        }
                        const parent = element.closest('label') || element.parentElement;
                        if (parent) parts.push(parent.innerText || parent.textContent || '');
                        return {
                            text: parts.filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim(),
                            checked: Boolean(element.checked),
                        };
                    }"""
                )
            except Exception:
                continue
            text = str(metadata.get("text") or "")
            if metadata.get("checked"):
                selected = True
            if re.search(r"opt\s*-?\s*out", text, re.IGNORECASE):
                opt_out = radio

        if not selected:
            if opt_out is None:
                print(
                    f"[{agent.ticker}] MetaMeetings privacy choice has no safe opt-out option",
                    flush=True,
                )
                return False
            try:
                await opt_out.check(force=True, timeout=5000)
                selected = True
            except Exception:
                return False

        submit_candidates = frame.locator(
            "button, input[type='submit'], input[type='button'], [role='button']"
        )
        for index in range(await submit_candidates.count()):
            submit = submit_candidates.nth(index)
            try:
                if not await submit.is_visible():
                    continue
                label = await submit.evaluate(
                    """element => [
                        element.value,
                        element.innerText,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                    ].filter(Boolean).join(' ')"""
                )
                if not re.search(r"submit\s+your\s+consent", str(label), re.IGNORECASE):
                    continue
                # A delivered consent click is never retried on another button.
                source_url = str(page.url)
                pages_before = tuple(page.context.pages)
                try:
                    dispatched = await _click_registration_control_once(page, submit)
                except Exception:
                    agent._registration_failure_error = "FORM_AUTOMATION_FAILED consent dispatch unresolved"
                    return False
                if not dispatched:
                    agent._registration_failure_error = "FORM_AUTOMATION_FAILED consent was not dispatched"
                    return False
                print(
                    f"[{agent.ticker}] MetaMeetings privacy choice submitted "
                    "without changing the selected option",
                    flush=True,
                )
                return await _wait_registration_outcome(
                    agent, page, frame, source_url=source_url, pages_before=pages_before,
                    allow_consent_continuation=False,
                )
            except Exception:
                continue
    return False


def _registration_targets(page: Any) -> list[Any]:
    targets = [page]
    try:
        targets.extend(frame for frame in page.frames if frame is not page)
    except Exception:
        pass
    return targets


async def _has_registration_form_in_target(agent, target: Any) -> bool:
    target_url = str(getattr(target, "url", "") or "")
    if SUBSCRIPTION_PAGE_PATTERN.search(target_url):
        return False
    try:
        evidence = await asyncio.wait_for(
            target.evaluate(
                """() => {
                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none';
                    };
                    const label = element => [
                        element.innerText,
                        element.value,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                    ].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim().slice(0, 400);
                    const controls = Array.from(
                        document.querySelectorAll('button, a')
                    ).filter(visible);
                    const fields = Array.from(document.querySelectorAll(
                        "input:not([type='hidden']):not([type='submit']):not([type='button']), "
                        + "select, textarea"
                    )).filter(visible);
                    const fieldLabel = element => {
                        const values = [
                            element.type,
                            element.name,
                            element.id,
                            element.placeholder,
                            element.getAttribute('aria-label'),
                            element.getAttribute('autocomplete'),
                        ];
                        if (element.id) {
                            const associated = document.querySelector(
                                `label[for="${CSS.escape(element.id)}"]`
                            );
                            if (associated) values.push(associated.innerText, associated.textContent);
                        }
                        const parentLabel = element.closest('label');
                        if (parentLabel) values.push(parentLabel.innerText, parentLabel.textContent);
                        return values.filter(Boolean).join(' ')
                            .replace(/\\s+/g, ' ').trim().slice(0, 500);
                    };
                    const submits = Array.from(document.querySelectorAll(
                        "button, input[type='submit']"
                    )).filter(visible);
                    const webcastsRegistrationForm = document.querySelector(
                        'form#frmRegister'
                    );
                    const webcastsRegistrationFields = webcastsRegistrationForm
                        ? fields.filter(field => field.closest('form') === webcastsRegistrationForm)
                        : [];
                    const fieldForms = Array.from(new Set(
                        fields.map(field => field.closest('form')).filter(Boolean)
                    ));
                    const formTexts = fieldForms.map(form =>
                        String(form.innerText || form.textContent || '')
                            .replace(/\\s+/g, ' ').trim().slice(0, 2000)
                    );
                    const localFormContexts = fieldForms.map(form => {
                        const parts = [];
                        const markedContainer = form.closest(
                            '[id*="subscribe" i], [class*="subscribe" i], '
                            + '[id*="newsletter" i], [class*="newsletter" i], '
                            + '[id*="email-alert" i], [class*="email-alert" i], '
                            + '[id*="emailalert" i], [class*="emailalert" i]'
                        );
                        if (markedContainer) {
                            parts.push(markedContainer.innerText, markedContainer.textContent);
                        }
                        const headings = Array.from(document.querySelectorAll(
                            'h1, h2, h3, h4, h5, h6, [role="heading"]'
                        ));
                        const preceding = headings.filter(heading => Boolean(
                            heading.compareDocumentPosition(form) &
                            Node.DOCUMENT_POSITION_FOLLOWING
                        )).pop();
                        if (preceding) {
                            parts.push(preceding.innerText, preceding.textContent);
                        }
                        return parts.filter(Boolean).join(' ')
                            .replace(/\\s+/g, ' ').trim().slice(0, 3000);
                    });
                    const submitLabels = submits.map(label).slice(0, 80);
                    const formSubmitLabels = submits
                        .filter(submit => {
                            const form = submit.closest('form');
                            return form && fieldForms.includes(form);
                        })
                        .map(label)
                        .slice(0, 80);
                    const fieldLabels = fields.map(fieldLabel);
                    const formMetadata = [
                        ...formTexts,
                        ...fieldForms.map(form => [
                            form.getAttribute('action'),
                            form.id,
                            form.className,
                        ].filter(Boolean).join(' ')),
                        ...formSubmitLabels,
                    ].join(' ');
                    const localFormMetadata = localFormContexts.join(' ');
                    const pageText = String(document.body?.innerText || '')
                        .replace(/\\s+/g, ' ').trim().slice(0, 6000);
                    const eventSpecific = /(?:webcast|conference call|register for (?:the )?event|enter (?:the )?webcast|join (?:the )?webcast)/i.test(formMetadata);
                    const metameetingsGuestAccess = /(?:general access|first time visitor|returning visitor|audio stream of this session|signing in through this page)/i.test(
                        `${formMetadata} ${localFormMetadata} ${pageText}`
                    ) && /sign\\s*(?:back\\s*)?in/i.test(
                        `${formSubmitLabels.join(' ')} ${formMetadata} ${pageText}`
                    );
                    const existingWebinarLogin = /(?:log\\s+in\\s+now|already\\s+registered\\??)/i.test(
                        `${formMetadata} ${localFormMetadata} ${pageText}`
                    ) && /(?:attend|log\\s*in|access)/i.test(
                        `${formSubmitLabels.join(' ')} ${formMetadata} ${pageText}`
                    ) && /(?:webinar\\.net|join\\.webinar\\.net)/i.test(location.hostname);
                    const identityFieldCount = fieldLabels.filter(value =>
                        /(?:first|last|full)[ _-]*name|given[ _-]*name|family[ _-]*name|company|organization|job[ _-]*title|occupation|industry|affiliation|country/i.test(value)
                    ).length;
                    const emailFieldCount = fieldLabels.filter(value =>
                        /email|e-mail/i.test(value)
                    ).length;
                    const subscriptionOnly =
                        /(?:subscribe|email alerts?|newsletter|notifications?|unsubscribe)/i.test(
                            `${formMetadata} ${localFormMetadata}`
                        ) &&
                        !eventSpecific;
                    return {
                        gate_labels: controls
                            .map(label)
                            .filter(value => /register|q4/i.test(value))
                            .slice(0, 40),
                        field_count: fields.length,
                        identity_field_count: identityFieldCount,
                        email_field_count: emailFieldCount,
                        submit_labels: formSubmitLabels,
                        form_text: formMetadata.slice(0, 6000),
                        local_form_context: localFormMetadata.slice(0, 3000),
                        body_text: fields.length >= 2 ? pageText : '',
                        event_specific: eventSpecific,
                        metameetings_guest_access: metameetingsGuestAccess,
                        existing_webinar_login: existingWebinarLogin,
                        subscription_only: subscriptionOnly,
                        webcasts_registration_form: Boolean(
                            webcastsRegistrationForm
                            && visible(webcastsRegistrationForm)
                            && webcastsRegistrationFields.length > 0
                        ),
                    };
                }"""
            ),
            timeout=3,
        )
        if os.getenv("WEBCAST_REGISTRATION_DIAGNOSTICS", "false").lower() == "true":
            print(
                f"[{agent.ticker}] registration evidence "
                f"fields={int(evidence.get('field_count') or 0)} "
                f"identity={int(evidence.get('identity_field_count') or 0)} "
                f"email={int(evidence.get('email_field_count') or 0)} "
                f"submits={str(evidence.get('submit_labels') or [])[:240]} "
                f"local={str(evidence.get('local_form_context') or '')[:240]} "
                f"subscription_only={bool(evidence.get('subscription_only'))} "
                f"event_specific={bool(evidence.get('event_specific'))}",
                flush=True,
            )
        if bool(evidence.get("subscription_only")):
            return False
        identity_field_count = int(evidence.get("identity_field_count") or 0)
        email_field_count = int(evidence.get("email_field_count") or 0)
        if bool(evidence.get("webcasts_registration_form")):
            return True
        # Open Exchange can render its registration shell a moment after
        # the provider URL opens. Its fields are stable, but the generic
        # event-context text is not always present in the first DOM pass.
        # Treat the provider's registration URL plus its identity/email
        # fields and Register action as a registration surface.
        if (
            is_open_exchange_registration_url(target_url)
            and identity_field_count >= 1
            and email_field_count >= 1
            and any(
                re.search(r"register|submit|enter|join", str(label or ""), re.IGNORECASE)
                for label in evidence.get("submit_labels", [])
            )
        ):
            return True
        # MetaMeetings exposes a guest audio gate as "General Access" with
        # First Time Visitor fields and a Sign In button. Treat it as a
        # registration-like step even though it may not say "register".
        if bool(evidence.get("metameetings_guest_access")):
            return True
        # webinar.net exposes an already-registered attendee as a one-field
        # email login screen ("Log In Now" + "Attend"), not as a normal
        # registration form. It still needs to be handled before playback.
        if bool(evidence.get("existing_webinar_login")):
            return True
        submit_text = " ".join(
            str(label or "") for label in evidence.get("submit_labels", [])
        )
        if (
            identity_field_count == 0
            and email_field_count >= 2
            and re.search(r"\blog\s*in\b", submit_text, re.IGNORECASE)
        ):
            return False
        if any(
            Q4_EVENT_GATE_PATTERN.search(str(label or ""))
            for label in evidence.get("gate_labels", [])
        ):
            return True
        # Investor-relations pages commonly contain a footer newsletter
        # form with one email field and a generic Submit button. It is not
        # a webcast gate even when the surrounding page contains webcast
        # links. The explicit Webcasts marker above handles provider forms
        # that intentionally omit identity fields.
        if (
            identity_field_count == 0
            and email_field_count <= 1
        ):
            return False
        if int(evidence.get("field_count") or 0) < 2:
            return False
        if any(
            re.search(r"register|enter|join", str(label or ""), re.IGNORECASE)
            for label in evidence.get("submit_labels", [])
        ):
            return True
        if bool(evidence.get("event_specific")) and email_field_count:
            # A page-level form can inherit webcast wording from nearby
            # IR content. Require an event-registration action as well;
            # search/subscribe forms must not block candidate discovery.
            if any(
                re.search(r"register|enter|join|submit", str(label or ""), re.IGNORECASE)
                for label in evidence.get("submit_labels", [])
            ):
                return True
            return False
        if identity_field_count and email_field_count and any(
            re.search(r"submit", str(label or ""), re.IGNORECASE)
            for label in evidence.get("submit_labels", [])
        ):
            return True
        form_text = str(evidence.get("form_text") or "")
        if REGISTRATION_FORM_TEXT_PATTERN.search(form_text):
            return True
    except Exception:
        return False
    return False


async def _find_registration_target(agent, page: Any) -> Any | None:
    for target in agent._registration_targets(page):
        if await agent._has_registration_form_in_target(target):
            return target
    return None


async def has_registration_form(
    agent,
    page: Any,
    *,
    wait_seconds: float = 0.0,
) -> bool:
    """Detect a registration form, allowing delayed provider rendering."""
    deadline = asyncio.get_running_loop().time() + max(0.0, wait_seconds)
    while True:
        if await agent._find_registration_target(page) is not None:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.5)


async def _find_registration_target_across_pages(
    agent,
    page: Any,
    *,
    wait_seconds: float = 0.0,
) -> tuple[Any, Any] | None:
    """Find a delayed registration form in the current page or popup tabs."""
    deadline = asyncio.get_running_loop().time() + max(0.0, wait_seconds)
    while True:
        for candidate_page in agent._playback_pages(page):
            try:
                if candidate_page.is_closed():
                    continue
            except Exception:
                pass
            try:
                await agent._wait_for_dynamic_page(candidate_page)
                target = await agent._find_registration_target(candidate_page)
            except Exception:
                continue
            if target is not None:
                return candidate_page, target
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.5)


async def _fill_generic_registration_form(
    agent,
    page: Any,
    timeout_error_type: type[Exception],
    owner_page: Any | None = None,
    submission_depth: int = 0,
) -> bool:
    observation_page = owner_page or page
    await agent._wait_for_dynamic_page(observation_page)
    root = page
    for _ in range(10):
        for selector in REGISTRATION_FORM_CONTAINER_SELECTORS:
            locator = page.locator(selector).first
            if await locator.count() > 0 and await locator.is_visible():
                root = locator
                break
        if root is not page:
            break
        await asyncio.sleep(0.5)

    try:
        registration_body_text = await page.locator("body").inner_text(
            timeout=1500
        )
    except Exception:
        registration_body_text = ""
    q4_custom_surface = is_q4_custom_registration_text(registration_body_text)
    q4_guest_surface = is_q4_guest_registration_text(registration_body_text)

    structured_choices: dict[str, dict[str, Any]] = {}

    async def choose_structured(locator: Any, value: str, label_text: str, *, fill: bool) -> bool:
        key = await locator.evaluate("""element => {
            if (!element.__ewChoiceKey) {
                const doc = element.ownerDocument;
                doc.__ewChoiceSequence = (doc.__ewChoiceSequence || 0) + 1;
                element.__ewChoiceKey = String(doc.__ewChoiceSequence);
            }
            return element.__ewChoiceKey;
        }""")
        prior = structured_choices.get(key)
        if prior and prior['value'] == value:
            return prior['success']
        aliases = ('United States of America', 'USA', 'US') if value.casefold() == 'united states' else ()
        result = await select_custom_option(locator, value, fill=fill, aliases=aliases)
        field = re.sub(r'[^a-z0-9]+', '_', label_text.casefold()).strip('_')
        structured_choices[key] = {'success': result.success, 'value': value,
                                   'locator': locator, 'field': field, 'reason': result.reason}
        emit_live_event(ticker=agent.ticker, stage='registration',
                        event='registration_field_choice',
                        status='passed' if result.success else 'blocked',
                        details={'field': field, 'reason': result.reason, 'kind': result.kind})
        return result.success

    async def fill_editable_field(locator: Any, value: str, label_text: str) -> bool:
        """Fill a provider field after its client-side form has settled.

        Q4 and a few replay providers briefly render the input as visible but
        disabled/read-only while hydration and validation state are applied.
        A single Playwright ``fill`` then produces the misleading
        ``element is not editable`` failure. Wait for the same located
        control to become editable, keeping the provider's normal events.
        """
        for attempt in range(10):
            try:
                if await locator.count() == 0:
                    return False
                # Providers sometimes reuse a visible label such as
                # ``State`` for a consent checkbox or radio group.  A
                # semantic label lookup can therefore return a control
                # that is visible but cannot accept text.  Keep those
                # controls exclusively in the consent/select handlers.
                control_type = (
                    (await locator.get_attribute("type")) or ""
                ).strip().lower()
                if control_type in {
                    "checkbox",
                    "radio",
                    "hidden",
                    "submit",
                    "button",
                    "reset",
                    "image",
                }:
                    return False
                tag_name = (
                    await locator.evaluate(
                        "element => element.tagName.toLowerCase()"
                    )
                ).strip().lower()
                if tag_name not in {"input", "textarea"}:
                    return False
                if not await locator.is_visible():
                    raise RuntimeError("field is not visible")
                try:
                    editable = await locator.is_editable(timeout=1000)
                except Exception:
                    # Lightweight test doubles and older Playwright shims may
                    # not expose is_editable; fill() remains the authority.
                    editable = True
                if not editable:
                    raise RuntimeError("field is not editable")
                if await locator.get_attribute('id') == 'GuestRegistrationInstitutionLookupInput':
                    return False
                if await is_structured_choice(locator):
                    return await choose_structured(locator, value, label_text, fill=True)
                await locator.fill(value)
                return True
            except Exception as exc:
                if attempt == 9:
                    print(
                        f"[{agent.ticker}] registration field unavailable: "
                        f"{label_text} ({str(exc)[:100]})",
                        flush=True,
                    )
                    return False
                await asyncio.sleep(0.35)
        return False

    async def fill_field(label_text: str, value: str, fallbacks: list[str]) -> bool:
        if not value:
            return False
        try:
            locator = root.get_by_label(label_text, exact=False).first
            if await fill_editable_field(locator, value, label_text):
                return True
        except Exception:
            pass
        for selector in fallbacks:
            matches = root.locator(selector)
            try:
                count = min(await matches.count(), 12)
            except Exception:
                count = 0
            for index in range(count):
                if await fill_editable_field(matches.nth(index), value, label_text):
                    return True
        unlabeled_fields = root.locator(
            "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea"
        )
        for index in range(await unlabeled_fields.count()):
            locator = unlabeled_fields.nth(index)
            if not await locator.is_visible():
                continue
            surrounding_text = await locator.evaluate(
                """element => {
                    let current = element;
                    for (let depth = 0; current && depth < 5; depth += 1) {
                        if (current.matches('form, body, html')) break;
                        const peers = current.querySelectorAll('input:not([type="hidden"]), select, textarea, [role="combobox"]');
                        if (Array.from(peers).some(peer => peer !== element && !peer.contains(element) && !element.contains(peer))) break;
                        const text = (current.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (text && text.length <= 220) return text;
                        current = current.parentElement;
                    }
                    return '';
                }"""
            )
            if re.search(rf"\b{re.escape(label_text)}\b", surrounding_text, re.IGNORECASE):
                if await fill_editable_field(locator, value, label_text):
                    return True

        # Some webcast providers generate opaque id/name values on every
        # request. Resolve the field from its accessible metadata instead
        # of depending on those unstable values.
        expected_terms = re.findall(r"[a-z0-9]+", label_text.lower())
        for index in range(await unlabeled_fields.count()):
            locator = unlabeled_fields.nth(index)
            if not await locator.is_visible():
                continue
            try:
                metadata = await locator.evaluate(
                    """element => {
                        const parts = [
                            element.getAttribute('title'),
                            element.getAttribute('aria-label'),
                            element.getAttribute('placeholder'),
                            element.getAttribute('autocomplete'),
                            element.getAttribute('name'),
                            element.getAttribute('id'),
                        ];
                        if (element.id) {
                            const label = document.querySelector(
                                `label[for="${CSS.escape(element.id)}"]`
                            );
                            if (label) parts.push(label.innerText, label.textContent);
                        }
                        const parentLabel = element.closest('label');
                        if (parentLabel) {
                            parts.push(parentLabel.innerText, parentLabel.textContent);
                        }
                        return parts.filter(Boolean).join(' ')
                            .replace(/\\s+/g, ' ').trim().toLowerCase();
                    }"""
                )
            except Exception:
                continue
            metadata_terms = set(re.findall(r"[a-z0-9]+", str(metadata or "")))
            if expected_terms and all(term in metadata_terms for term in expected_terms):
                if await fill_editable_field(locator, value, label_text):
                    return True
        return False

    async def fill_autocomplete_field(
        label_text: str,
        value: str,
        fallbacks: list[str],
    ) -> bool:
        """Fill a provider autocomplete and commit a visible suggestion."""
        if not value:
            return False
        # Prefer provider selectors before the accessible-label fallback.
        # Some providers associate a label with a wrapper rather than the
        # actual select, so a wrapper click can look successful while the
        # required value remains empty.
        candidates = [root.locator(selector).first for selector in fallbacks]
        try:
            candidates.append(root.get_by_label(label_text, exact=False).first)
        except Exception:
            pass
        for locator in candidates:
            try:
                if await locator.count() == 0 or not await locator.is_visible():
                    continue
                if await locator.get_attribute("id") == "GuestRegistrationInstitutionLookupInput":
                    await locator.fill(value)
                    return await _commit_q4_company_lookup(root, locator, value)
                if await is_structured_choice(locator):
                    return await choose_structured(locator, value, label_text, fill=True)
                return await fill_editable_field(locator, value, label_text)
            except Exception:
                continue
        return False

    async def select_individual_attendee() -> bool:
        """Use the provider-offered personal path after company selection fails."""
        controls = root.locator("input[type='checkbox']")
        for index in range(await controls.count()):
            control = controls.nth(index)
            try:
                metadata = await control.evaluate(
                    """element => {
                        const parts = [
                            element.value,
                            element.name,
                            element.id,
                            element.getAttribute('aria-label'),
                            element.getAttribute('title'),
                        ];
                        if (element.id) {
                            const label = document.querySelector(
                                `label[for="${CSS.escape(element.id)}"]`
                            );
                            if (label) parts.push(label.innerText || label.textContent || '');
                        }
                        const parent = element.closest('label') || element.parentElement;
                        if (parent) parts.push(parent.innerText || parent.textContent || '');
                        return parts.filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                    }"""
                )
                if not re.search(r"individual\s+attendee", str(metadata or ""), re.IGNORECASE):
                    continue
                if not await control.is_checked():
                    await control.check(force=True, timeout=5000)
                print(
                    f"[{agent.ticker}] selected Q4 individual attendee option",
                    flush=True,
                )
                return True
            except Exception:
                continue
        return False

    first_name_filled = await fill_field(
        "First Name",
        agent.profile.first_name,
        [
            WEBCASTS_REGISTRATION_FIELD_SELECTORS["first_name"],
            "#GuestRegistrationFirstNameInput",
            "input[title*='First' i]",
            "input[name*='first' i]",
            "input[name*='fname' i]",
            "input[id*='first' i]",
            "input[id*='fname' i]",
            "input[placeholder*='first' i]",
            "input[aria-label*='first' i]",
            "input[placeholder='First' i]",
            "input[aria-label='First' i]",
        ],
    )
    last_name_filled = await fill_field(
        "Last Name",
        agent.profile.last_name,
        [
            WEBCASTS_REGISTRATION_FIELD_SELECTORS["last_name"],
            "#GuestRegistrationLastNameInput",
            "input[title*='Last' i]",
            "input[name*='last' i]",
            "input[name*='lname' i]",
            "input[id*='last' i]",
            "input[id*='lname' i]",
            "input[placeholder*='last' i]",
            "input[aria-label*='last' i]",
            "input[placeholder='Last' i]",
            "input[aria-label='Last' i]",
        ],
    )

    async def fill_full_name_field() -> bool:
        if not agent.profile.full_name or first_name_filled or last_name_filled:
            return False
        candidates = [
            root.get_by_label(
                re.compile(r"^\s*(?:full\s+)?name\s*\*?\s*$", re.IGNORECASE)
            ).first,
            root.locator("input[name='name' i]").first,
            root.locator("input[id='name' i]").first,
            root.locator("input[name*='full_name' i]").first,
            root.locator("input[id*='full_name' i]").first,
            root.locator("input[placeholder='Name' i]").first,
            root.locator("input[aria-label='Name' i]").first,
        ]
        for locator in candidates:
            try:
                if await locator.count() == 0 or not await locator.is_visible():
                    continue
                await locator.fill(agent.profile.full_name)
                return True
            except Exception:
                continue
        return False

    q4_company_lookup_uncommitted = False

    async def fill_company_name_field() -> bool:
        """Fill company fields without confusing Q4 text with a selected object."""
        nonlocal q4_company_lookup_uncommitted
        filled = await fill_autocomplete_field(
            "Company Name",
            agent.profile.company,
            [
                "#GuestRegistrationInstitutionLookupInput",
                "input[title*='Company Name' i]",
                "input[name*='company' i]",
                "input[id*='company' i]",
                "input[placeholder*='company' i]",
                "input[aria-label*='company' i]",
                "[role='combobox'][name*='company' i]",
                "[role='combobox'][id*='company' i]",
                "[role='combobox'][aria-label*='company' i]",
            ],
        )
        if filled:
            return True
        if q4_guest_surface and await root.locator("#GuestRegistrationInstitutionLookupInput").count():
            # This control validates a selected institution, not the input's
            # text. A second plain fill used to hide lookup failure and skip
            # the valid individual-attendee path, yielding "Company name required".
            q4_company_lookup_uncommitted = True
            return False
        # Some Q4 pages render Company Name as a regular input without
        # autocomplete metadata. Do not leave the field empty just
        # because no suggestion list was exposed.
        return await fill_field(
            "Company Name",
            agent.profile.company,
            [
                "#EventRegistrationViewCustomRegistrationForm input:not([type='hidden'])",
                "input[title*='Company Name' i]",
                "input[name*='company' i]",
                "input[id*='company' i]",
                "input[placeholder*='company' i]",
                "input[aria-label*='company' i]",
            ],
        )

    # Q4's full guest form has an explicit individual-attendee path. Keep
    # it pending until the editable fields are filled: selecting it too
    # early makes Q4 mark Company Role readonly, even though that field is
    # still required by the form. The fallback below selects the individual
    # path after the role has been committed.
    individual_attendee_selected = False

    filled_fields = {
        "first_name": first_name_filled,
        "last_name": last_name_filled,
        "full_name": await fill_full_name_field(),
        "title": await fill_field(
            "Title",
            agent.profile.job_title,
            [
                "input[title*='Title' i]",
                "input[name*='title' i]",
                "input[id*='title' i]",
                "input[placeholder*='title' i]",
                "input[aria-label*='title' i]",
            ],
        ),
        "company": await fill_field(
            "Company",
            agent.profile.company,
            [
                WEBCASTS_REGISTRATION_FIELD_SELECTORS["company"],
                "input[title*='Company' i]",
                "input[name*='company' i]",
                "input[id*='company' i]",
                "input[placeholder*='company' i]",
                "input[aria-label*='company' i]",
            ],
        ),
        "company_name": (
            False
            if individual_attendee_selected
            else await fill_company_name_field()
        ),
        "phone_number": await fill_field(
            "Phone Number",
            agent.profile.phone_number,
            [
                "input[title*='Phone Number' i]",
                "input[aria-label*='Phone Number' i]",
                "input[placeholder*='Phone Number' i]",
                "input[name*='phone' i]",
                "input[id*='phone' i]",
                "input[name*='telephone' i]",
                "input[id*='telephone' i]",
                "input[type='tel']",
            ],
        ),
        "city": await fill_field(
            "City",
            agent.profile.city,
            [
                "input[title*='City' i]",
                "input[name*='city' i]",
                "input[id*='city' i]",
                "input[placeholder*='city' i]",
                "input[aria-label*='city' i]",
            ],
        ),
        "state": await fill_field(
            "State",
            agent.profile.state,
            [
                "input[title*='State' i]",
                "input[name*='state' i]",
                "input[id*='state' i]",
                "input[placeholder*='state' i]",
                "input[aria-label*='state' i]",
            ],
        ),
        "organization": await fill_field(
            "Organization",
            agent.profile.company,
            [
                "input[title*='Organization' i]",
                "input[name*='organization' i]",
                "input[name*='org' i]",
                "input[id*='organization' i]",
                "input[id*='org' i]",
                "input[placeholder*='organization' i]",
                "input[aria-label*='organization' i]",
            ],
        ),
        "affiliation": await fill_field(
            "Affiliation",
            agent.profile.industry_affiliation,
            [
                "input[title*='Affiliation' i]",
                "input[name*='affiliation' i]",
                "input[id*='affiliation' i]",
                "input[placeholder*='affiliation' i]",
                "input[aria-label*='affiliation' i]",
            ],
        ),
        "job_title": await fill_field(
            "Job Title",
            agent.profile.job_title,
            [
                "input[title*='Job Title' i]",
                "input[name*='job_title' i]",
                "input[name*='jobtitle' i]",
                "input[id*='job_title' i]",
                "input[id*='jobtitle' i]",
                "input[placeholder*='Job Title' i]",
                "input[aria-label*='Job Title' i]",
                "input[name='position' i]",
                "input[id='position' i]",
            ],
        ),
        "company_role": await fill_field(
            "Company Role",
            agent.profile.job_title,
            [
                "#GuestRegistrationRoleFieldInput",
                "input[title*='Company Role' i]",
                "input[name*='role' i]",
                "input[id*='role' i]",
                "input[placeholder*='role' i]",
                "input[aria-label*='role' i]",
            ],
        ),
        "country": await fill_field(
            "Country",
            agent.profile.country,
            [
                "input[title*='Country' i]",
                "input[name*='country' i]",
                "input[id*='country' i]",
                "input[placeholder*='country' i]",
                "input[aria-label*='country' i]",
            ],
        ),
        "email": await fill_field(
            "Email",
            agent.profile.email,
            [
                WEBCASTS_REGISTRATION_FIELD_SELECTORS["email"],
                "#GuestRegistrationEmailInput",
                "input[type='email']",
                "input[title*='Email' i]",
                "input[name*='mail' i]",
                "input[id*='mail' i]",
                "input[placeholder*='mail' i]",
                "input[aria-label*='mail' i]",
            ],
        ),
    }

    async def select_field(
        label_text: str,
        value: str,
        fallbacks: list[str],
    ) -> bool:
        if not value:
            return False
        candidates = []
        try:
            candidates.append(root.get_by_label(label_text, exact=False))
        except Exception:
            pass
        candidates.extend(root.locator(selector).first for selector in fallbacks)
        for locator in candidates:
            try:
                if await locator.count() == 0 or not await locator.is_visible():
                    continue
                await locator.select_option(label=value)
                return True
            except Exception:
                continue
        return False

    async def choose_option_field(
        label_text: str,
        value: str,
        fallbacks: list[str],
        *,
        fallback_first_valid: bool = False,
    ) -> bool:
        if not value:
            return False

        async def select_value(locator: Any) -> bool:
            tag_name = await locator.evaluate("element => element.tagName.toLowerCase()")
            if tag_name != "select":
                # Label fallbacks can resolve the same free-text input that
                # fill_field already completed (for example Q4 Company Role).
                # Only an actual choice widget needs a committed menu option.
                if tag_name in {"input", "textarea"} and not await is_structured_choice(locator):
                    return False
                return await choose_structured(locator, value, label_text, fill=False)

            try:
                await locator.select_option(label=value, timeout=3_000)
                return True
            except Exception:
                try:
                    await locator.select_option(value=value, timeout=3_000)
                    return True
                except Exception:
                    pass

            # GlobalMeet and similar forms use opaque option values and
            # occasionally spell United States as "United States of
            # America". Match known country aliases before giving up.
            normalized_requested = " ".join(value.split()).casefold()
            option_aliases = {
                "united states": ("united states of america", "usa", "us"),
            }.get(normalized_requested, ())
            preferred_labels = (normalized_requested, *option_aliases)
            options = locator.locator("option")
            for preferred_label in preferred_labels:
                for option_index in range(await options.count()):
                    option = options.nth(option_index)
                    try:
                        option_data = await option.evaluate(
                            """element => ({
                                value: element.value || '',
                                label: element.label || element.textContent || '',
                                disabled: Boolean(element.disabled),
                            })"""
                        )
                    except Exception:
                        continue
                    option_label = " ".join(
                        str(option_data.get("label") or "").split()
                    ).casefold()
                    if option_data.get("disabled") or option_label != preferred_label:
                        continue
                    try:
                        await locator.select_option(
                            value=str(option_data.get("value") or ""),
                            timeout=3_000,
                        )
                        print(
                            f"[{agent.ticker}] selected option alias: "
                            f"{label_text}={option_label[:80]}",
                            flush=True,
                        )
                        return True
                    except Exception:
                        continue

            if not fallback_first_valid:
                return False
            # Some Angular webcast forms populate the native select only
            # after it receives focus. Activate it before inspecting options.
            try:
                await locator.click(force=True, timeout=3_000)
            except Exception:
                pass
            options = locator.locator("option")
            option_data_values: list[dict[str, Any]] = []
            for _ in range(10):
                option_data_values = []
                for option_index in range(await options.count()):
                    option = options.nth(option_index)
                    try:
                        option_data = await option.evaluate(
                            """element => ({
                                value: element.value || '',
                                label: element.label || element.textContent || '',
                                disabled: Boolean(element.disabled),
                            })"""
                        )
                    except Exception:
                        continue
                    option_value = str(option_data.get("value") or "").strip()
                    option_label = " ".join(
                        str(option_data.get("label") or "").split()
                    ).strip()
                    if option_data.get("disabled"):
                        continue
                    if not option_value and not option_label:
                        continue
                    if re.match(
                        r"^(?:--|select|choose|please select|attendee type)\b",
                        option_label,
                        re.IGNORECASE,
                    ):
                        continue
                    option_data_values.append(
                        {"value": option_value, "label": option_label}
                    )
                if option_data_values:
                    break
                await asyncio.sleep(0.5)

            normalized_value = " ".join(value.split()).casefold()
            ordered_options = sorted(
                option_data_values,
                key=lambda option: (
                    " ".join(str(option["label"]).split()).casefold()
                    != normalized_value
                    and str(option["value"]).casefold() != normalized_value,
                ),
            )
            for option_data in ordered_options:
                option_value = str(option_data["value"] or "").strip()
                option_label = str(option_data["label"] or "").strip()
                try:
                    if option_value:
                        await locator.select_option(value=option_value, timeout=3_000)
                    else:
                        await locator.select_option(label=option_label, timeout=3_000)
                    selected_display = option_label or option_value
                    print(
                        f"[{agent.ticker}] selected fallback option: "
                        f"{label_text}={selected_display[:80]}",
                        flush=True,
                    )
                    return True
                except Exception:
                    continue
            return False

        # Prefer provider selectors before the accessible-label fallback.
        # Some providers associate a label with a wrapper rather than the
        # actual select, so a wrapper click can look successful while the
        # required value remains empty.
        candidates = [root.locator(selector).first for selector in fallbacks]
        try:
            candidates.append(root.get_by_label(label_text, exact=False).first)
        except Exception:
            pass
        for locator in candidates:
            try:
                if await locator.count() == 0 or not await locator.is_visible():
                    continue
                if await select_value(locator):
                    return True
            except Exception:
                continue

        # A number of registration providers render a labelled custom
        # dropdown as a plain button with an opaque id. Resolve it from
        # the surrounding label/group text rather than requiring a stable
        # provider-specific selector.
        expected_terms = set(re.findall(r"[a-z0-9]+", label_text.lower()))
        controls = root.locator("select, [role='combobox'], button")
        for index in range(await controls.count()):
            locator = controls.nth(index)
            try:
                if not await locator.is_visible():
                    continue
                metadata = await locator.evaluate(
                    """element => {
                        const parts = [
                            element.innerText,
                            element.value,
                            element.getAttribute('aria-label'),
                            element.getAttribute('title'),
                            element.getAttribute('name'),
                            element.getAttribute('id'),
                        ];
                        let current = element;
                        for (let depth = 0; current && depth < 3; depth += 1) {
                            if (current.matches('form, body, html')) break;
                            const peers = current.querySelectorAll('input:not([type="hidden"]), select, textarea, button, [role="combobox"]');
                            if (Array.from(peers).some(peer => peer !== element && !peer.contains(element) && !element.contains(peer))) break;
                            parts.push(current.innerText || current.textContent || '');
                            current = current.parentElement;
                        }
                        const previous = element.previousElementSibling;
                        if (previous && previous.matches('label, span, legend') && !previous.querySelector('input,select,textarea,button')) parts.push(previous.innerText || previous.textContent || '');
                        return parts.filter(Boolean).join(' ')
                            .replace(/\\s+/g, ' ').trim().slice(0, 1800);
                    }"""
                )
                metadata_terms = set(
                    re.findall(r"[a-z0-9]+", str(metadata or "").lower())
                )
                if not expected_terms.issubset(metadata_terms):
                    continue
                control_label = str(await locator.inner_text() or "").strip()
                if re.search(r"submit|register|enter|join|create", control_label, re.I):
                    continue
                if await select_value(locator):
                    return True
            except Exception:
                continue

        if fallback_first_valid and (
            "attendee" in label_text.lower()
            or "country" in label_text.lower()
        ):
            required_selects = root.locator(
                "select:required, select[aria-required='true']"
            )
            expected_terms = set(re.findall(r"[a-z0-9]+", label_text.lower()))
            for index in range(await required_selects.count()):
                locator = required_selects.nth(index)
                try:
                    if not await locator.is_visible():
                        continue
                    metadata = await locator.evaluate(
                        """element => {
                            const parts = [
                                element.getAttribute('title'),
                                element.getAttribute('aria-label'),
                                element.getAttribute('name'),
                                element.getAttribute('id'),
                            ];
                            if (element.id) {
                                const label = document.querySelector(
                                    `label[for="${CSS.escape(element.id)}"]`
                                );
                                if (label) parts.push(label.innerText || label.textContent || '');
                            }
                            let current = element.parentElement;
                            for (let depth = 0; current && depth < 3; depth += 1, current = current.parentElement) {
                                if (current.matches('form, body, html')) break;
                                const peers = current.querySelectorAll('input:not([type="hidden"]), select, textarea, button, [role="combobox"]');
                                if (Array.from(peers).some(peer => peer !== element && !peer.contains(element) && !element.contains(peer))) break;
                                parts.push(current.innerText || current.textContent || '');
                            }
                            return parts.filter(Boolean).join(' ')
                                .replace(/\\s+/g, ' ').trim().toLowerCase();
                        }"""
                    )
                except Exception:
                    continue
                metadata_terms = set(re.findall(r"[a-z0-9]+", str(metadata or "")))
                allow_single_required_fallback = (
                    await required_selects.count() == 1
                    and "country" in label_text.lower()
                )
                if expected_terms.issubset(metadata_terms) or allow_single_required_fallback:
                    if await select_value(locator):
                        return True
        return False

    async def registration_control_state() -> list[dict[str, Any]]:
        """Collect redacted select state for provider-specific diagnostics."""
        controls = root.locator(
            "select, [role='combobox'], input:not([type='hidden']):not([type='submit'])"
        )
        state: list[dict[str, Any]] = []
        for index in range(await controls.count()):
            locator = controls.nth(index)
            try:
                if not await locator.is_visible():
                    continue
                data = await locator.evaluate(
                    """element => {
                        const labelFor = element.id
                            ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`)
                            : null;
                        const parent = element.closest('label, fieldset, div, section');
                        const text = value => String(value || '')
                            .replace(/\\s+/g, ' ').trim().slice(0, 120);
                        const selected = element.tagName.toLowerCase() === 'select'
                            ? Array.from(element.selectedOptions || []).map(option => text(option.textContent)).join('|')
                            : '';
                        return {
                            tag: element.tagName.toLowerCase(),
                            type: text(element.type),
                            id: text(element.id),
                            name: text(element.getAttribute('name')),
                            role: text(element.getAttribute('role')),
                            aria_label: text(element.getAttribute('aria-label')),
                            label: text(labelFor?.innerText || labelFor?.textContent),
                            parent_text: text(parent?.innerText || parent?.textContent),
                            selected,
                            has_value: Boolean(element.value),
                        };
                    }"""
                )
                state.append(data)
            except Exception:
                continue
        return state

    selected_fields = {
        "industry_affiliation": await choose_option_field(
            "Industry Affiliation",
            agent.profile.industry_affiliation,
            [
                "select[title*='Industry Affiliation' i]",
                "select[name*='industry' i]",
                "select[id*='industry' i]",
                "[role='combobox'][aria-label*='industry' i]",
                "[role='combobox'][id*='industry' i]",
                "button[aria-label*='industry' i]",
                "button[id*='industry' i]",
            ],
            fallback_first_valid=True,
        ),
        "affiliation": await choose_option_field(
            "Affiliation",
            agent.profile.industry_affiliation,
            [
                "select[name*='affiliation' i]",
                "select[id*='affiliation' i]",
                "select[title*='affiliation' i]",
                "select[aria-label*='affiliation' i]",
                "[role='combobox'][aria-label*='affiliation' i]",
                "[role='combobox'][id*='affiliation' i]",
                "button[aria-label*='affiliation' i]",
                "button[id*='affiliation' i]",
            ],
            fallback_first_valid=True,
        ),
        "occupation": await choose_option_field(
            "Occupation",
            agent.profile.occupation,
            [
                "select[name*='occupation' i]",
                "[role='combobox'][aria-label*='occupation' i]",
                "button[aria-label*='occupation' i]",
                "button[id*='occupation' i]",
            ],
        ),
        "country_select": await choose_option_field(
            "Country",
            agent.profile.country,
            [
                "select[name*='country' i]",
                "select[id*='country' i]",
                "select[title*='country' i]",
                "select[aria-label*='country' i]",
                "[role='combobox'][name*='country' i]",
                "[role='combobox'][id*='country' i]",
                "[role='combobox'][aria-label*='country' i]",
                "button[aria-label*='country' i]",
                "button[id*='country' i]",
                # Media Server's country control has varied between
                # labelled and opaque native selects. Its registration
                # container normally contains only this one select.
                "select",
            ],
            fallback_first_valid=True,
        ),
        "classification": await choose_option_field(
            "Classification",
            agent.profile.industry_affiliation or agent.profile.other_option,
            [
                "select[name*='classification' i]",
                "select[id*='classification' i]",
                "select[title*='classification' i]",
                "select[aria-label*='classification' i]",
                "[role='combobox'][name*='classification' i]",
                "[role='combobox'][id*='classification' i]",
                "[role='combobox'][aria-label*='classification' i]",
                "button[aria-label*='classification' i]",
                "button[id*='classification' i]",
            ],
            fallback_first_valid=True,
        ),
        "attendee_type": await choose_option_field(
            "Attendee Type",
            agent.profile.attendee_type,
            [
                "select[name*='attendee' i]",
                "select[id*='attendee' i]",
                "select[title*='attendee' i]",
                "select[aria-label*='attendee' i]",
                "[role='combobox'][aria-label*='attendee' i]",
                "[role='combobox'][id*='attendee' i]",
            ],
            fallback_first_valid=True,
        ),
        "company_role_select": await choose_option_field(
            "Company Role",
            agent.profile.other_option or agent.profile.job_title,
            [
                "select[name*='role' i]",
                "select[id*='role' i]",
                "select[title*='role' i]",
                "select[aria-label*='role' i]",
                "[role='combobox'][name*='role' i]",
                "[role='combobox'][id*='role' i]",
                "[role='combobox'][aria-label*='role' i]",
                "button[aria-label*='role' i]",
                "button[id*='role' i]",
            ],
            fallback_first_valid=True,
        ),
        "other": await choose_option_field(
            "Select One",
            agent.profile.other_option,
            [
                "select[title*='Select One' i]",
                "select[name*='select' i]",
                "select[id*='select' i]",
                "select[aria-label*='Select One' i]",
                "[role='combobox'][aria-label*='Select One' i]",
                "[role='combobox'][id*='select' i]",
            ],
        ),
    }
    has_any_field = any(filled_fields.values()) or any(selected_fields.values())

    if not has_any_field:
        agent._registration_failure_error = "FORM_AUTOMATION_FAILED no registration field could be completed"
        emit_live_event(ticker=agent.ticker, stage='registration', event='registration_fields_unresolved',
                        status='blocked', details={'choice_reasons': sorted({c['reason'] for c in structured_choices.values()})})
        return False
    print(
        f"[{agent.ticker}] registration fields prepared: "
        f"{','.join(name for name, filled in {**filled_fields, **selected_fields}.items() if filled)}",
        flush=True,
    )

    if not filled_fields.get("company_name") and not individual_attendee_selected:
        individual_attendee_selected = await select_individual_attendee()

    if q4_company_lookup_uncommitted and not individual_attendee_selected:
        agent._registration_failure_error = (
            "FORM_AUTOMATION_FAILED REGISTRATION_FIELD_UNRESOLVED Q4 company lookup did not select a matching company"
        )
        print(f"[{agent.ticker}] {agent._registration_failure_error}", flush=True)
        return False

    # Providers do not consistently mark consent controls as `required`.
    # For example, webinar.net renders the affirmative option as a radio
    # with value="yes" and only reports the missing consent after submit.
    consent_selectors = (
        "input[type='radio'][value='yes' i]",
        "input[type='radio'][value='agree' i]",
        "input[type='radio'][value='accept' i]",
        "input[type='radio'][id*='consent' i]",
        "input[type='radio'][name*='consent' i]",
        "input[type='radio'][id*='term' i]",
        "input[type='radio'][name*='term' i]",
        "input[type='checkbox'][id*='consent' i]",
        "input[type='checkbox'][name*='consent' i]",
        "input[type='checkbox'][id*='term' i]",
        "input[type='checkbox'][name*='term' i]",
        "input[type='checkbox']:required",
        "input[type='radio']:required",
        "input[type='checkbox'][aria-required='true']",
        "input[type='radio'][aria-required='true']",
        "[role='checkbox'][aria-required='true']",
        "[role='radio'][aria-required='true']",
    )
    consent_candidates = []
    seen_control_ids: set[str] = set()
    for selector in consent_selectors:
        matches = root.locator(selector)
        for index in range(await matches.count()):
            control = matches.nth(index)
            try:
                identity = await control.evaluate(
                    "element => element.outerHTML.slice(0, 1000)"
                )
            except Exception:
                identity = f"{selector}:{index}"
            if identity in seen_control_ids:
                continue
            seen_control_ids.add(identity)
            consent_candidates.append(control)

    # Include unlabelled controls as a final fallback. The surrounding
    # label text is the reliable signal on providers with generated ids.
    all_controls = root.locator(
        "input[type='checkbox'], input[type='radio'], "
        "[role='checkbox'], [role='radio']"
    )
    for index in range(await all_controls.count()):
        control = all_controls.nth(index)
        try:
            identity = await control.evaluate(
                "element => element.outerHTML.slice(0, 1000)"
            )
        except Exception:
            identity = f"all:{index}"
        if identity not in seen_control_ids:
            seen_control_ids.add(identity)
            consent_candidates.append(control)

    consent_selected = False
    for control in consent_candidates:
        try:
            control_type = (
                (await control.get_attribute("type")) or ""
            ).strip().lower()
            control_role = (
                (await control.get_attribute("role")) or ""
            ).strip().lower()
            if not await control.is_visible() and control_type not in {
                "checkbox",
                "radio",
            } and control_role not in {"checkbox", "radio"}:
                continue
            control_value = (
                (await control.get_attribute("value")) or ""
            ).strip().casefold()
            consent_text = await control.evaluate(
                """element => {
                    const parts = [
                        element.value,
                        element.name,
                        element.id,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                    ];
                    if (element.id) {
                        const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
                        if (label) parts.push(label.innerText || label.textContent || '');
                    }
                    const ownLabel = element.closest('label');
                    if (ownLabel) parts.push(ownLabel.innerText || ownLabel.textContent || '');
                    if (parts.length <= 5) {
                        let current = element.parentElement;
                        for (let depth = 0; current && depth < 4; depth += 1, current = current.parentElement) {
                            const text = String(current.innerText || current.textContent || '')
                                .replace(/\\s+/g, ' ').trim();
                            if (text && text.length <= 700) parts.push(text);
                        }
                    }
                    return parts.filter(Boolean).join(' ').slice(0, 1400);
                }"""
            )
            affirmative_value = control_value in {
                "yes",
                "agree",
                "accepted",
                "accept",
                "true",
                "1",
            }
            if not affirmative_value and not is_positive_registration_consent_text(
                consent_text
            ):
                continue
            aria_checked = (
                (await control.get_attribute("aria-checked")) or ""
            ).strip().lower()
            try:
                already_checked = await control.is_checked()
            except Exception:
                already_checked = aria_checked in {"true", "mixed"}
            if not already_checked and aria_checked not in {"true", "mixed"}:
                try:
                    if control_role in {"checkbox", "radio"}:
                        await control.click(force=True, timeout=5000)
                    else:
                        await control.check(force=True, timeout=5000)
                except Exception:
                    # Some providers visually hide the native radio and
                    # expose only its label as the clickable surface.
                    await control.evaluate(
                        """element => {
                            const label = element.id
                                ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`)
                                : element.closest('label');
                            (label || element).click();
                        }"""
                    )
            consent_selected = True
            print(
                f"[{agent.ticker}] registration consent selected: yes",
                flush=True,
            )
            break
        except Exception:
            continue

    # A few webcast providers render the privacy/consent choice as a
    # required native select instead of a checkbox or radio group. Treat
    # only selects whose surrounding text clearly describes consent as
    # consent controls; country, occupation, and attendee-type selects
    # must continue through their regular field handlers above.
    consent_selects = root.locator("select")
    for index in range(await consent_selects.count()):
        control = consent_selects.nth(index)
        try:
            if not await control.is_visible():
                continue
            metadata = await control.evaluate(
                """element => {
                    const labelFor = element.id
                        ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`)
                        : null;
                    const parent = element.closest('label, fieldset, div, section');
                    return [
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                        element.getAttribute('name'),
                        element.id,
                        labelFor?.innerText || labelFor?.textContent || '',
                        parent?.innerText || parent?.textContent || '',
                    ].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                }"""
            )
            if not re.search(
                r"privacy|consent|terms?|agree|accept|information.*(?:use|transfer)|"
                r"read\s+and\s+agree",
                str(metadata or ""),
                re.IGNORECASE,
            ):
                continue
            options = control.locator("option")
            for option_index in range(await options.count()):
                option = options.nth(option_index)
                option_text = await option.inner_text()
                option_value = await option.get_attribute("value") or ""
                option_label = " ".join(str(option_text or "").split())
                if not is_positive_registration_consent_text(
                    f"{option_label} {option_value}"
                ):
                    continue
                await control.select_option(
                    value=option_value if option_value else None,
                    label=None if option_value else option_label,
                    timeout=5000,
                )
                consent_selected = True
                print(
                    f"[{agent.ticker}] registration consent selected: "
                    f"{option_label[:80]}",
                    flush=True,
                )
                break
            if consent_selected:
                break
        except Exception:
            continue

    if not consent_selected:
        # A form may not require consent. Keep that case compatible while
        # making a missing affirmative option visible in diagnostics.
        print(
            f"[{agent.ticker}] registration consent control not detected",
            flush=True,
        )

    validation = await collect_registration_validation(root)
    unresolved_choices = []
    for choice in structured_choices.values():
        if choice['success']:
            continue
        if individual_attendee_selected and choice['field'] in {'company', 'company_name', 'organization'}:
            continue
        try:
            if await choice['locator'].is_visible() and await choice['locator'].is_enabled():
                unresolved_choices.append({'field': choice['field'], 'codes': [choice['reason']]})
        except Exception:
            continue
    invalid_count = validation['invalid_field_count'] + len(unresolved_choices)
    emit_live_event(ticker=agent.ticker, stage='registration',
                    event='registration_validation',
                    status='blocked' if invalid_count or validation['error_codes'] else 'prepared',
                    details={**validation, 'unresolved_choices': unresolved_choices,
                             'unresolved_choice_count': len(unresolved_choices)})

    if agent.registration_preview_only:
        # Never include values here: the preview is intended to be safe to
        # review and persist even when the profile contains personal data.
        prepared_fields = [
            name
            for name, filled in {**filled_fields, **selected_fields}.items()
            if filled
        ]
        print(
            f"[{agent.ticker}] REGISTRATION_PREVIEW "
            f"{json.dumps({
                'ticker': agent.ticker,
                'destination_url': redact_registration_url(observation_page.url),
                'prepared_fields': prepared_fields,
                'invalid_field_count': validation['invalid_field_count'],
                'unresolved_choice_count': len(unresolved_choices),
                'consent_selected': consent_selected,
                'submission_attempted': False,
            }, ensure_ascii=True, sort_keys=True)}",
            flush=True,
        )
        agent._registration_failure_error = (
            "REGISTRATION_PREVIEW registration submission not attempted"
        )
        return False

    if invalid_count:
        agent._registration_failure_error = (
            "FORM_AUTOMATION_FAILED form validation failed; "
            f"invalid_fields={validation['invalid_field_count']} "
            f"unresolved_choices={len(unresolved_choices)} "
            f"codes={','.join(validation['error_codes'])}"
        )
        print(
            f"[{agent.ticker}] registration validation blocked: "
            f"invalid_fields={validation['invalid_field_count']} "
            f"unresolved_choices={len(unresolved_choices)}",
            flush=True,
        )
        return False

    prepared_fields = [
        name
        for name, filled in {**filled_fields, **selected_fields}.items()
        if filled
    ]
    approval_error = agent._registration_approval_error(
        observation_page.url,
        prepared_fields,
        consent_selected,
    )
    if approval_error:
        agent._registration_failure_error = approval_error
        print(f"[{agent.ticker}] {approval_error}", flush=True)
        return False

    submit_button = root.locator(
        f"{WEBCASTS_REGISTRATION_SUBMIT_SELECTOR}, "
        "#GuestRegistrationSubmitButton, "
        "input[type='submit'][value*='Submit' i], "
        "input[type='submit'][value*='Register' i], "
        "input[type='submit'][value*='Enter' i], "
        "input[type='submit'][value*='Join' i], "
        "input[type='submit'][value*='Sign In' i], "
        "input[type='submit'][value*='Sign Back In' i]"
    ).first
    if await submit_button.count() == 0 or not await submit_button.is_visible():
        submit_button = root.locator("button[type='submit'], button").filter(
            has_text=re.compile(
                r"Submit|Register|Enter|Join|Create|Sign\s+(?:Back\s+)?In",
                re.IGNORECASE,
            )
        ).first
    if await submit_button.count() == 0 or not await submit_button.is_visible():
        submit_button = root.locator(
            "[role='button'], input[type='button']"
        ).filter(
            has_text=re.compile(
                r"Submit|Register|Enter|Join|Create|Sign\s+(?:Back\s+)?In",
                re.IGNORECASE,
            )
        ).first
    if await submit_button.count() == 0 or not await submit_button.is_visible():
        # `input` elements have no inner text, so provider buttons whose
        # label is stored in value/title can evade Playwright's text filter.
        submit_candidates = root.locator(
            "input[type='submit'], input[type='button'], button"
        )
        visible_candidates = []
        for index in range(await submit_candidates.count()):
            candidate = submit_candidates.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                label = await candidate.evaluate(
                    """element => [
                        element.value,
                        element.innerText,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                    ].filter(Boolean).join(' ')"""
                )
            except Exception:
                continue
            visible_candidates.append((candidate, str(label or "")))
        matching_candidates = [
            candidate
            for candidate, label in visible_candidates
            if re.search(
                r"Submit|Register|Enter|Join|Create|Sign\s+(?:Back\s+)?In",
                label,
                re.IGNORECASE,
            )
        ]
        if matching_candidates:
            submit_button = matching_candidates[0]
        elif len(visible_candidates) == 1:
            submit_button = visible_candidates[0][0]
    if await submit_button.count() == 0 or not await submit_button.is_visible():
        agent._registration_failure_error = "registration submit control not found"
        print(f"[{agent.ticker}] {agent._registration_failure_error}", flush=True)
        return False

    if await submit_button.count() > 0 and await submit_button.is_visible():
        print(f"[{agent.ticker}] submitting webcast registration form", flush=True)
        source_url = observation_page.url
        context = getattr(observation_page, "context", None)
        pages_before = tuple(context.pages) if context is not None else ()
        if not await _click_registration_control_once(observation_page, submit_button):
            agent._registration_failure_error = "FORM_AUTOMATION_FAILED registration submit control could not be activated"
            return False
        return await _wait_registration_outcome(
            agent, observation_page, root, source_url=source_url,
            pages_before=pages_before, source_body=registration_body_text,
            timeout_error_type=timeout_error_type, submission_depth=submission_depth,
        )
    return False
