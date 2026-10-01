"""Read-only registration validation evidence with no attendee values.

Both native browser constraints and application-rendered errors are relevant:
React/Vue controls can reject an uncommitted choice without setting :invalid.
The result deliberately contains canonical field names and reason codes only.
Pass the registration form/container (or its owning frame), never a different
top-level page when the form lives in an iframe.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

from .access_barriers import flow_surfaces, frame_flow_context


_VALIDATION_SCRIPT = r"""root => {
    const scope = root && root.querySelectorAll ? root : document;
    const doc = scope.ownerDocument || document;
    const visible = element => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return !element.closest('[hidden], [inert], [aria-hidden="true"]')
            && style.display !== 'none' && style.visibility !== 'hidden'
            && rect.width > 0 && rect.height > 0;
    };
    const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
    const canonicalField = (element, index) => {
        const labelParts = [element.name, element.id, element.type,
            element.getAttribute('aria-label'), element.getAttribute('autocomplete')];
        for (const label of Array.from(element.labels || [])) labelParts.push(label.textContent);
        for (const id of normalize(element.getAttribute('aria-labelledby')).split(' ')) {
            if (id) labelParts.push(doc.getElementById(id)?.textContent);
        }
        const parentLabel = element.closest('label');
        if (parentLabel) labelParts.push(parentLabel.textContent);
        const metadata = normalize(labelParts.filter(Boolean).join(' '));
        for (const [name, pattern] of [
            ['email', /email|e-mail/i], ['password', /password/i],
            ['first_name', /first.?name|given.?name|given-name/i],
            ['last_name', /last.?name|family.?name|surname/i],
            ['job_title', /job.?title|company.?role|occupation|designation/i],
            ['company', /company|institution|organization|organisation|affiliation/i],
            ['country', /country/i], ['state', /state|province|region/i],
            ['city', /city|town/i], ['phone', /phone|telephone|tel\b/i],
            ['postal_code', /postal|zip.?code/i],
            ['consent', /consent|privacy|terms|agree/i],
            ['attendee_type', /attendee.?type|investor.?type/i],
            ['name', /full.?name|name/i],
        ]) if (pattern.test(metadata)) return name;
        return `field_${index + 1}`;
    };
    const errorCodes = text => {
        const codes = [];
        if (/\brequired\b|\bmandatory\b|please\s+(?:enter|select|provide|choose|complete)|must\s+(?:enter|select|provide|choose|complete)/i.test(text)) {
            codes.push('required');
        }
        if (/invalid|not\s+valid|valid\s+(?:e-?mail|address|number|value)/i.test(text)) codes.push('invalid_value');
        if (/already\s+(?:been\s+)?registered|registration\s+(?:already\s+)?exists/i.test(text)) codes.push('already_registered');
        if (/unable\s+to|could\s+not|couldn't|failed|try\s+again|something\s+went\s+wrong/i.test(text)) codes.push('submission_error');
        return codes;
    };
    const fields = [];
    const controls = Array.from(scope.querySelectorAll(
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea, [role="combobox"], [role="checkbox"]'
    )).slice(0, 150);
    for (const [index, element] of controls.entries()) {
        if (!visible(element) || element.disabled || element.matches(':disabled')
            || element.getAttribute('aria-disabled') === 'true') continue;
        const codes = new Set();
        const validity = element.validity;
        if (element.willValidate && validity && !validity.valid) {
            if (validity.valueMissing) codes.add('required');
            if (validity.typeMismatch) codes.add('type_mismatch');
            if (validity.patternMismatch) codes.add('pattern_mismatch');
            if (validity.customError) codes.add('custom_validation');
            if (validity.tooLong || validity.tooShort) codes.add('length');
            if (validity.rangeOverflow || validity.rangeUnderflow || validity.stepMismatch || validity.badInput) codes.add('invalid_value');
            if (!codes.size) codes.add('native_invalid');
        }
        const ariaInvalid = element.getAttribute('aria-invalid');
        if (ariaInvalid && ariaInvalid !== 'false') codes.add('aria_invalid');
        // Do not infer whether a custom select has committed a value from its
        // input text. Provider-specific selection logic remains authoritative.
        if (element.getAttribute('aria-required') === 'true'
            && ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName)
            && !element.readOnly && element.getAttribute('role') !== 'combobox') {
            const empty = ['checkbox', 'radio'].includes(element.type)
                ? !element.checked : !normalize(element.value);
            if (empty) codes.add('required');
        }
        for (const attr of ['aria-errormessage', 'aria-describedby']) {
            for (const id of normalize(element.getAttribute(attr)).split(' ')) {
                const message = id ? doc.getElementById(id) : null;
                const errorMessage = message && (attr === 'aria-errormessage'
                    || codes.size || message.matches('[role="alert"], [class*="error" i], .invalid-feedback'));
                if (errorMessage && visible(message)) {
                    for (const code of errorCodes(normalize(message.textContent))) codes.add(code);
                }
            }
        }
        if (codes.size) fields.push({field: canonicalField(element, index), codes: Array.from(codes).sort()});
    }
    const globalCodes = new Set();
    let visibleErrorCount = 0;
    const messages = Array.from(scope.querySelectorAll(
        '[role="alert"], [aria-live="assertive"], [class*="error" i], .invalid-feedback, [data-error]'
    )).slice(0, 150);
    for (const message of messages) {
        if (!visible(message)) continue;
        // The text is only classified inside the browser. Never return it:
        // validation messages often echo an attendee's email or company.
        const codes = errorCodes(normalize(message.textContent).slice(0, 2000));
        if (!codes.length) continue;
        visibleErrorCount += 1;
        for (const code of codes) globalCodes.add(code);
    }
    return {invalid_field_count: fields.length, fields,
        error_codes: Array.from(globalCodes).sort(), visible_error_count: visibleErrorCount};
}"""


async def collect_registration_validation(root: Any) -> dict[str, Any]:
    """Collect bounded, redacted validation from a Locator, Page, or Frame.

    ``available=False`` explicitly distinguishes navigation/detachment from
    a genuinely clean validation result. This helper never submits, alters
    constraints, or calls checkValidity (which dispatches invalid events).
    """
    try:
        frame = root if getattr(root, 'parent_frame', None) is not None else None
        if frame is None and callable(getattr(root, 'owner_frame', None)):
            frame = await asyncio.wait_for(root.owner_frame(), .5)
        if frame is None and callable(getattr(root, 'element_handle', None)):
            handle = await asyncio.wait_for(root.element_handle(timeout=500), .6)
            if handle is not None:
                try:
                    frame = await asyncio.wait_for(handle.owner_frame(), .5)
                finally:
                    await asyncio.wait_for(handle.dispose(), .2)
        if frame is not None:
            context = await asyncio.wait_for(frame_flow_context(frame), 1.2)
            if not context['visible']:
                return {'available': context['reason'] == 'hidden_embedding',
                        'ignored_surface': context['reason'], 'invalid_field_count': 0,
                        'fields': [], 'error_codes': [], 'visible_error_count': 0}
        evidence = await asyncio.wait_for(root.evaluate(_VALIDATION_SCRIPT), 1.5)
        if not isinstance(evidence, dict):
            raise TypeError('validation evidence is not an object')
        return {"available": True, **evidence}
    except Exception:
        return {"available": False, "invalid_field_count": 0, "fields": [],
                "error_codes": [], "visible_error_count": 0}


async def registration_transition_state(
    agent: Any,
    owner_page: Any,
    candidate_page: Any,
    source_url: str,
    remaining_form_root: Any | None = None,
    *,
    allow_consent_continuation: bool = True,
) -> dict[str, Any]:
    """Observe one post-submit checkpoint, without waiting loops or resubmits.

    Form disappearance, URL changes and popups are *progress*, not proof of
    success. Only a current-page player or a provider waiting room without a
    remaining registration form passes. The caller owns the bounded retry
    loop and may handle recognized multi-step forms before calling this.
    """
    try:
        return await asyncio.wait_for(_registration_transition_state(
            agent, owner_page, candidate_page, source_url, remaining_form_root,
            allow_consent_continuation,
        ), 6)
    except asyncio.TimeoutError:
        return {"state": "pending", "reason": "transition_check_timeout"}


async def _registration_transition_state(
    agent: Any, owner_page: Any, candidate_page: Any, source_url: str,
    remaining_form_root: Any | None,
    allow_consent_continuation: bool,
) -> dict[str, Any]:
    def result(state: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {"state": state, "reason": reason, **extra}

    try:
        if candidate_page.is_closed():
            return result('pending', 'target_closed')
        if candidate_page is not owner_page and await candidate_page.opener() is not owner_page:
            return result('unrelated', 'unrelated_popup')
        destination = str(candidate_page.url)
        if destination in {'', 'about:blank', 'about:srcdoc'}:
            return result('pending', 'target_loading')
        path = urlparse(destination).path
        if re.search(r'(?:^|[/_.-])(?:survey|feedback|subscribe|error|denied)(?:[/_.?-]|$)', path, re.I):
            return result('failed', 'non_player_destination')
        # A same-origin application route can complete in-place. A cross-host
        # popup/redirect additionally needs the existing event proof chain.
        if urlparse(destination).hostname != urlparse(source_url).hostname:
            validator = getattr(agent, '_validate_live_target_page', None)
            if validator is None or not await asyncio.wait_for(validator(candidate_page), 3):
                return result('pending', 'unverified_destination')
    except Exception:
        return result('pending', 'target_unavailable')

    try:
        # An unchanged login form shortly after submission is a pending AJAX
        # response, not evidence that credentials were rejected. Security
        # challenges still fail immediately; no challenge is bypassed.
        unchanged_owner = candidate_page is owner_page and destination == source_url
        access_detector = getattr(agent, '_detect_access_barrier', None)
        access_barrier = await asyncio.wait_for(access_detector(candidate_page), 3) if access_detector else None
        if access_barrier and not (unchanged_owner and str(access_barrier).startswith('AUTH_REQUIRED')):
            return result('failed', 'access_blocked')
        registration_detector = getattr(agent, '_detect_registration_barrier', None)
        barrier = await asyncio.wait_for(registration_detector(candidate_page), 3) if registration_detector else None
        ordinary_consent_barrier = barrier and 'mandatory terms/privacy consent' in str(barrier)
        if barrier and not ordinary_consent_barrier:
            return result('failed', 'registration_blocked')

        targets = [item['surface'] for item in await flow_surfaces(candidate_page)
                   if item['visible'] and item['relevant']]
        host = (urlparse(destination).hostname or '').lower()
        webinar = host in {'app.webinar.net', 'webinar.net', 'join.webinar.net'}
        metameetings = host == 'metameetings.net' or host.endswith('.metameetings.net')
        consent_gate = False
        enter_gate = False
        if webinar or metameetings:
            for target in targets[:12]:
                try:
                    gates = await asyncio.wait_for(target.evaluate(r'''() => {
                        const visible = e => {
                            const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                            return r.width>0 && r.height>0 && s.display!=='none'
                                && s.visibility!=='hidden' && !e.closest('[hidden],[aria-hidden="true"]');
                        };
                        const label = e => [e.innerText,e.value,e.getAttribute('aria-label')]
                            .filter(Boolean).join(' ').replace(/\s+/g,' ').trim();
                        const controls = Array.from(document.querySelectorAll('button,input[type="submit"],input[type="button"],[role="button"]')).filter(visible);
                        const body = String(document.body?.innerText || '').slice(0,12000);
                        const radios = Array.from(document.querySelectorAll('input[type="radio"]')).filter(visible);
                        const hasChoice = radios.some(e => e.checked || /opt\s*-?\s*out/i.test([
                            e.value,e.name,e.id,e.getAttribute('aria-label'),
                            ...Array.from(e.labels || []).map(l=>l.textContent)
                        ].filter(Boolean).join(' ')));
                        const consent = /privacy\s+(?:and\s+data\s+)?policy|submit\s+your\s+consent/i.test(body)
                            && controls.some(e=>/\bsubmit\s+your\s+consent\b/i.test(label(e))) && hasChoice;
                        const dialogs = Array.from(document.querySelectorAll('#holdingScreen,#bigPlayButtonScreen,[role="dialog"],[aria-modal="true"]')).filter(visible);
                        const entry = dialogs.some(d => /(?:webinar|webcast)\s+has\s+started|click\s+(?:the\s+)?button\s+below\s+to\s+enter/i.test(d.innerText || '')
                            && controls.some(e=>d.contains(e) && /^enter$/i.test(label(e))));
                        return {consent,entry};
                    }'''), 1)
                except Exception:
                    continue
                consent_gate = consent_gate or (metameetings and gates['consent'])
                enter_gate = enter_gate or (webinar and gates['entry'])
        if consent_gate:
            # The existing playback dispatcher owns this provider's normal
            # opt-out consent step. While observing *that consent submission*,
            # its unchanged gate must stay pending rather than pass again.
            if not allow_consent_continuation:
                for target in targets[:12]:
                    validation = await collect_registration_validation(target)
                    if validation['invalid_field_count'] or validation['error_codes']:
                        return result('failed', 'validation_rejected', validation=validation)
            return result('passed' if allow_consent_continuation else 'pending',
                          'consent_ready' if allow_consent_continuation else 'consent_submission_pending')
        privacy_path = re.search(r'(?:^|[/_.-])(?:privacy|terms)(?:[/_.?-]|$)', path, re.I)
        if privacy_path and not metameetings:
            return result('failed', 'non_player_destination')
        if barrier and not unchanged_owner:
            return result('failed', 'registration_blocked')
        if await asyncio.wait_for(agent.has_registration_form(candidate_page, wait_seconds=0), 3):
            scope = remaining_form_root if candidate_page is owner_page and remaining_form_root is not None else candidate_page
            validation = await collect_registration_validation(scope)
            if validation['invalid_field_count'] or validation['error_codes']:
                return result('failed', 'validation_rejected', validation=validation)
            return result('pending', 'registration_form_remaining', validation=validation)
        for target in targets[:12]:
            validation = await collect_registration_validation(target)
            # Once the registration form is absent, an untouched native
            # required question/newsletter field beside the player is not a
            # registration rejection. Explicit app/ARIA errors still count.
            explicit_field_error = any(
                {'aria_invalid', 'custom_validation'} & set(field['codes'])
                for field in validation['fields']
            )
            if explicit_field_error or validation['error_codes']:
                return result('failed', 'validation_rejected', validation=validation)
        if enter_gate and re.fullmatch(r'/[A-Za-z0-9_-]+/live/?', path):
            return result('passed', 'entry_ready')
        if await asyncio.wait_for(agent.detect_active_playback(candidate_page, include_context_pages=False), 3):
            return result('passed', 'active_playback')
        media_detector = getattr(agent, '_has_visible_media_element', None)
        if media_detector and await asyncio.wait_for(media_detector(candidate_page, include_context_pages=False), 3):
            return result('passed', 'player_ready')
        if privacy_path:
            return result('pending' if unchanged_owner else 'failed', 'consent_transition_pending' if unchanged_owner else 'non_player_destination')
        # Registration can succeed before any media exists. Recognize the
        # provider's explicit waiting room rather than a generic IR heading.
        if urlparse(destination).hostname == urlparse(source_url).hostname:
            for target in targets[:12]:
                try:
                    body = await target.locator('body').inner_text(timeout=500)
                except Exception:
                    continue
                waiting_text = body[:10000]
                lobby_wait = re.search(
                    r'(?:webcast|webinar|broadcast|event|conference\s+call)\s+'
                    r'(?:has\s+not\s+(?:yet\s+)?started|hasn.t\s+started|'
                    r'will\s+(?:begin|start)\s+(?:shortly|soon))|'
                    r'waiting\s+for\s+(?:the\s+)?(?:webcast|webinar|broadcast|event)'
                    r'\s+to\s+(?:begin|start)', waiting_text, re.I)
                # Q4 confirms registration before its broadcast lobby opens.
                # Require both confirmation and the explicit timed-access
                # notice; a generic thank-you page is not a waiting room.
                q4_registered_wait = (
                    host == 'events.q4inc.com'
                    and re.fullmatch(r'/attendee/[^/]+/guest/?', path)
                    and re.search(r'\bthank\s+you\s+for\s+registering\b', waiting_text, re.I)
                    and re.search(
                        r'\bcan\s+access\s+the\s+webcast\s+up\s+to\s+'
                        r'\d{1,2}\s+minutes?\s+before\s+the\s+start\s+time\b',
                        waiting_text, re.I)
                )
                if lobby_wait or q4_registered_wait:
                    return result('passed', 'waiting_room')
    except Exception:
        return result('pending', 'transition_unavailable')
    return result('pending', 'no_positive_transition')
