"""Registration diagnostic tests use local DOM only; every request is aborted."""

import json
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.form_validation import collect_registration_validation, registration_transition_state


class LocalTarget:
    """An in-memory origin around real DOM; never navigate to external sites."""
    def __init__(self, page, url='https://fixture.test/event/player', opener=None):
        self.page, self.url, self.source = page, url, opener

    def __getattr__(self, key):
        return getattr(self.page, key)

    async def opener(self):
        return self.source


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class FormValidationBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        options = {'headless': True, 'args': ['--disable-background-networking', '--no-sandbox']}
        if os.getenv('WEBCAST_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['WEBCAST_CHROMIUM_EXECUTABLE']
        self.browser = await self.pw.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route('**/*', lambda route: route.abort())

    async def test_native_and_aria_invalid_detected_without_validation_events_or_values(self):
        await self.page.set_content('''<form><input name="email" type="email" value="secret-invalid-email">
            <input name="company" value="Secret Corporation" aria-invalid="true" aria-describedby="company-error">
            <span id="company-error">Company name is required. Secret Corporation is invalid.</span>
            </form><script>window.invalidEvents=0;
            document.addEventListener('invalid',()=>invalidEvents++,true);</script>''')
        result = await collect_registration_validation(self.page.locator('form'))
        self.assertEqual(result['invalid_field_count'], 2)
        self.assertEqual(result['fields'][0], {'field': 'email', 'codes': ['type_mismatch']})
        self.assertIn('aria_invalid', result['fields'][1]['codes'])
        self.assertIn('required', result['fields'][1]['codes'])
        self.assertNotIn('Secret', json.dumps(result))
        self.assertNotIn('secret-invalid-email', json.dumps(result))
        self.assertEqual(await self.page.evaluate('invalidEvents'), 0)

    async def test_application_error_detected_even_with_zero_native_invalid_fields(self):
        await self.page.set_content('''<form><input name="company" value="Fixture">
            <div class="nui-form-field__error">Company name required</div></form>''')
        result = await collect_registration_validation(self.page.locator('form'))
        self.assertEqual(result['invalid_field_count'], 0)
        self.assertEqual(result['error_codes'], ['required'])
        self.assertEqual(result['visible_error_count'], 1)

    async def test_hidden_disabled_other_form_and_ordinary_help_are_not_errors(self):
        await self.page.set_content('''<form id="target"><input name="email" value="ok@example.test" type="email">
            <input name="secret" required style="display:none"><input required disabled>
            <fieldset disabled><input required></fieldset>
            <span class="error" hidden>Required</span>
            <span class="error">Email helps you join this event</span></form>
            <form><input name="other" required><div role="alert">Required</div></form>''')
        result = await collect_registration_validation(self.page.locator('#target'))
        self.assertTrue(result['available'])
        self.assertEqual(result['invalid_field_count'], 0)
        self.assertEqual(result['error_codes'], [])

    async def test_frame_diagnostics_observe_own_document(self):
        await self.page.set_content('<iframe></iframe>')
        frame = self.page.frames[1]
        await frame.set_content('<form><input name="email" aria-invalid="true"></form>')
        result = await collect_registration_validation(frame)
        self.assertEqual(result['fields'], [{'field': 'email', 'codes': ['aria_invalid']}])
        self.assertEqual((await collect_registration_validation(self.page))['invalid_field_count'], 0)

    async def test_detached_root_is_unavailable_not_clean(self):
        await self.page.set_content('<form id="target"><input required></form>')
        handle = await self.page.locator('#target').element_handle()
        await handle.dispose()
        result = await collect_registration_validation(handle)
        self.assertFalse(result['available'])

    async def test_unknown_field_names_and_echoed_values_are_redacted(self):
        await self.page.set_content('''<form><input id="user-secret@example.test" aria-invalid="true">
            <div role="alert">user-secret@example.test is already registered</div></form>''')
        result = await collect_registration_validation(self.page.locator('form'))
        self.assertEqual(result['fields'][0]['field'], 'field_1')
        self.assertEqual(result['error_codes'], ['already_registered'])
        self.assertNotIn('user-secret', json.dumps(result))

    async def test_aria_required_and_native_checkbox(self):
        await self.page.set_content('''<form><input name="first_name" aria-required="true">
            <input name="privacy_consent" type="checkbox" required></form>''')
        result = await collect_registration_validation(self.page.locator('form'))
        self.assertEqual(result['fields'], [
            {'field': 'first_name', 'codes': ['required']},
            {'field': 'consent', 'codes': ['required']},
        ])

    async def test_committed_custom_select_empty_input_is_not_assumed_missing(self):
        await self.page.set_content('''<form><div>Fixture Corporation</div>
            <input role="combobox" name="company" aria-required="true"></form>''')
        result = await collect_registration_validation(self.page.locator('form'))
        self.assertEqual(result['invalid_field_count'], 0)

    async def test_filled_field_required_help_text_is_not_a_validation_error(self):
        await self.page.set_content('''<form><input name="email" value="fixture@example.test" aria-describedby="help">
            <span id="help">An email address is required to join</span></form>''')
        result = await collect_registration_validation(self.page.locator('form'))
        self.assertEqual(result['invalid_field_count'], 0)

    def transition_agent(self):
        async def has_form(page, **kwargs):
            for frame in page.frames:
                if await frame.locator('form:visible').count():
                    return True
            return False
        async def has_media(page, **kwargs):
            for frame in page.frames:
                if await frame.locator('video:visible, audio:visible').count():
                    return True
            return False
        return SimpleNamespace(
            _detect_access_barrier=mock.AsyncMock(return_value=None),
            _detect_registration_barrier=mock.AsyncMock(return_value=None),
            has_registration_form=has_form,
            detect_active_playback=mock.AsyncMock(return_value=False),
            _has_visible_media_element=has_media,
            _validate_live_target_page=mock.AsyncMock(return_value=False),
        )

    async def transition(self, html, *, url='https://fixture.test/event/player'):
        await self.page.set_content(html)
        target = LocalTarget(self.page, url=url)
        return await registration_transition_state(self.transition_agent(), target, target, 'https://fixture.test/event/register')

    async def test_empty_url_changed_document_is_pending(self):
        self.assertEqual((await self.transition('Loading...'))['state'], 'pending')
        self.assertEqual((await self.transition('<h1>Earnings Webcast</h1>'))['state'], 'pending')

    async def test_url_error_is_not_registration_success(self):
        self.assertEqual((await self.transition('<h1>Unable to continue</h1>', url='https://fixture.test/error'))['state'], 'failed')

    async def test_player_and_explicit_waiting_room_are_positive_checkpoints(self):
        self.assertEqual((await self.transition('<video controls></video>'))['reason'], 'player_ready')
        self.assertEqual((await self.transition('<p>The webcast has not yet started.</p>'))['reason'], 'waiting_room')

    async def test_same_page_remaining_form_is_pending_not_success(self):
        result = await self.transition('<form><input name="email" value="ok@example.test"></form><video controls></video>')
        self.assertEqual(result['reason'], 'registration_form_remaining')

    async def test_same_page_rejection_is_failed_with_redacted_evidence(self):
        result = await self.transition('<form><input name="company" aria-invalid="true" value="Secret"></form>')
        self.assertEqual(result['reason'], 'validation_rejected')
        self.assertNotIn('Secret', json.dumps(result))

    async def test_unrelated_popup_is_not_accepted(self):
        await self.page.set_content('<video controls></video>')
        owner = LocalTarget(self.page)
        candidate = LocalTarget(self.page, opener=None)
        result = await registration_transition_state(self.transition_agent(), owner, candidate, owner.url)
        self.assertEqual(result['reason'], 'unrelated_popup')

    async def test_related_popup_player_is_accepted(self):
        await self.page.set_content('<video controls></video>')
        owner = LocalTarget(self.page)
        candidate = LocalTarget(self.page, opener=owner)
        result = await registration_transition_state(self.transition_agent(), owner, candidate, owner.url)
        self.assertEqual(result['reason'], 'player_ready')

    async def test_cross_host_popup_needs_target_proof(self):
        await self.page.set_content('<video controls></video>')
        owner = LocalTarget(self.page)
        candidate = LocalTarget(self.page, url='https://other.test/player', opener=owner)
        result = await registration_transition_state(self.transition_agent(), owner, candidate, owner.url)
        self.assertEqual(result['reason'], 'unverified_destination')

    async def test_iframe_validation_cannot_be_hidden_by_owner_player(self):
        await self.page.set_content('<video controls></video><iframe></iframe>')
        await self.page.frames[1].set_content('<input name="company" aria-invalid="true">')
        owner = LocalTarget(self.page)
        result = await registration_transition_state(self.transition_agent(), owner, owner, owner.url)
        self.assertEqual(result['reason'], 'validation_rejected')

    async def test_webinar_live_welcome_enter_is_positive_without_media(self):
        await self.page.set_content('''<div id="holdingScreen" role="dialog">
            <p>The webinar has started. Click the button below to enter.</p><button>Enter</button></div>''')
        owner = LocalTarget(self.page, url='https://app.webinar.net/current-event/live')
        result = await registration_transition_state(self.transition_agent(), owner, owner, 'https://app.webinar.net/current-event')
        self.assertEqual(result['reason'], 'entry_ready')
        other = LocalTarget(self.page, url='https://other.test/current-event/live')
        result = await registration_transition_state(self.transition_agent(), other, other, 'https://other.test/current-event')
        self.assertEqual(result['state'], 'pending')

    async def consent_fixture(self):
        await self.page.set_content('''<h1>MAP Digital Privacy and Data Policy</h1>
            <p>Submit your consent to hear the audio stream of this session.</p>
            <label><input type="radio" name="privacy" value="opt-out">Opt out</label>
            <button>Submit Your Consent</button>''')
        return LocalTarget(self.page, url='https://www.metameetings.net/privacy')

    async def test_known_consent_continues_to_existing_handler_even_with_mandatory_terms(self):
        owner = await self.consent_fixture()
        agent = self.transition_agent()
        agent._detect_registration_barrier.return_value = 'mandatory terms/privacy consent is required'
        result = await registration_transition_state(agent, owner, owner, 'https://www.metameetings.net/login')
        self.assertEqual(result['reason'], 'consent_ready')
        self.assertEqual(result['state'], 'passed')

    async def test_consent_submission_does_not_reaccept_unchanged_gate(self):
        owner = await self.consent_fixture()
        result = await registration_transition_state(self.transition_agent(), owner, owner, owner.url,
                                                     allow_consent_continuation=False)
        self.assertEqual(result['reason'], 'consent_submission_pending')
        self.assertEqual(result['state'], 'pending')
        await self.page.set_content('<video controls></video>')
        result = await registration_transition_state(self.transition_agent(), owner, owner, owner.url,
                                                     allow_consent_continuation=False)
        self.assertEqual(result['reason'], 'player_ready')

    async def test_submitted_consent_validation_error_is_reported_before_timeout(self):
        owner = await self.consent_fixture()
        await self.page.evaluate("() => { const e=document.createElement('p');e.setAttribute('role','alert');e.textContent='Unable to submit your consent';document.body.append(e); }")
        result = await registration_transition_state(self.transition_agent(), owner, owner, owner.url,
                                                     allow_consent_continuation=False)
        self.assertEqual(result['reason'], 'validation_rejected')
        self.assertEqual(result['state'], 'failed')

    async def test_generic_privacy_and_survey_do_not_advance(self):
        result = await self.transition('<p>Privacy policy</p>', url='https://fixture.test/privacy')
        self.assertEqual(result['state'], 'failed')
        result = await self.transition('<video controls></video>', url='https://fixture.test/survey')
        self.assertEqual(result['state'], 'failed')

    async def test_consent_controls_on_other_domain_are_not_accepted(self):
        await self.consent_fixture()
        owner = LocalTarget(self.page, url='https://other.test/privacy')
        result = await registration_transition_state(self.transition_agent(), owner, owner, owner.url)
        self.assertEqual(result['state'], 'failed')

    async def test_captcha_not_bypassed_by_ordinary_consent_gate(self):
        owner = await self.consent_fixture()
        agent = self.transition_agent()
        agent._detect_registration_barrier.return_value = 'anti-bot captcha requires manual verification'
        result = await registration_transition_state(agent, owner, owner, owner.url)
        self.assertEqual(result['reason'], 'registration_blocked')

    async def test_unchanged_login_after_dispatch_stays_pending(self):
        await self.page.set_content('<form><input name="email" value="fixture@example.test"></form>')
        owner = LocalTarget(self.page, url='https://fixture.test/login')
        agent = self.transition_agent()
        agent._detect_access_barrier.return_value = 'AUTH_REQUIRED authentication/login surface'
        result = await registration_transition_state(agent, owner, owner, owner.url)
        self.assertEqual(result['reason'], 'registration_form_remaining')
        self.assertEqual(result['state'], 'pending')
        result = await registration_transition_state(agent, owner, owner, 'https://fixture.test/register')
        self.assertEqual(result['reason'], 'access_blocked')

    async def test_captcha_on_unchanged_owner_fails_immediately(self):
        await self.page.set_content('<p>Verify you are human</p>')
        owner = LocalTarget(self.page)
        agent = self.transition_agent()
        agent._detect_access_barrier.return_value = 'captcha'
        result = await registration_transition_state(agent, owner, owner, owner.url)
        self.assertEqual(result['reason'], 'access_blocked')

    async def test_player_question_required_field_does_not_reject_completed_registration(self):
        await self.page.set_content('<video controls></video><form id="questions"><input name="question" required></form>')
        target = LocalTarget(self.page)
        agent = self.transition_agent()
        # Production registration detection excludes auxiliary questions and
        # newsletters; native required alone must not reverse that decision.
        agent.has_registration_form = mock.AsyncMock(return_value=False)
        result = await registration_transition_state(agent, target, target, target.url)
        self.assertEqual(result['state'], 'passed')
        self.assertEqual(result['reason'], 'player_ready')


if __name__ == '__main__':
    unittest.main()
