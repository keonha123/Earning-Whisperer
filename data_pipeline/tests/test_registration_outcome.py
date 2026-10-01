"""Actual Chromium regression fixtures for post-submit transition acceptance.

All browser requests are locally fulfilled. No external registration is sent.
"""

import os
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.registration import (
    _click_registration_control_once,
    _wait_registration_outcome,
)


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class RegistrationOutcomeBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        options = {'headless': True, 'args': ['--disable-background-networking', '--no-sandbox']}
        if os.getenv('WEBCAST_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['WEBCAST_CHROMIUM_EXECUTABLE']
        self.browser = await self.pw.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.context = await self.browser.new_context()
        await self.context.route('**/*', lambda route: route.fulfill(
            status=200, content_type='text/html', body='<body></body>'))
        self.page = await self.context.new_page()
        await self.page.goto('https://fixture.test/event/register')
        self.env = mock.patch.dict(os.environ, {'WEBCAST_REGISTRATION_POST_SUBMIT_WAIT_SECONDS': '0.5'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.agent = self.make_agent()
        self.telemetry = mock.patch('data_pipeline.collectors.streams.browser.registration.emit_live_event')
        self.events = self.telemetry.start()
        self.addCleanup(self.telemetry.stop)

    def make_agent(self):
        async def has_form(page, **kwargs):
            for frame in page.frames:
                if await frame.locator('form:visible').count():
                    return True
            return False

        async def has_media(page, **kwargs):
            for frame in page.frames:
                if await frame.locator('audio:visible,video:visible').count():
                    return True
            return False

        return SimpleNamespace(
            ticker='EWTEST', lifecycle='live',
            registration_preview_only=False, allow_registration_submission=True,
            _registration_target_page=None, _registration_failure_error=None,
            _detect_access_barrier=mock.AsyncMock(return_value=None),
            _detect_registration_barrier=mock.AsyncMock(return_value=None),
            has_registration_form=has_form,
            detect_active_playback=mock.AsyncMock(return_value=False),
            _has_visible_media_element=has_media,
            _validate_live_target_page=mock.AsyncMock(return_value=False),
            _playback_pages=lambda page: list(page.context.pages),
            _registration_targets=lambda page: list(page.frames),
            _attach_media_watchers=mock.Mock(),
            _fill_generic_registration_form=mock.AsyncMock(return_value=False),
            accept_cookie_banners=mock.AsyncMock(),
        )

    async def fixture(self, action=''):
        await self.page.set_content('''<h1>Conference call guest registration</h1>
          <form id="registration"><input name="email" type="email" value="fixture@example.test">
          <button id="submit" type="submit">Register</button></form>
          <script>window.submissions=0; window.clicks=0;
          document.querySelector('#submit').addEventListener('click',()=>window.clicks++);
          document.querySelector('#registration').addEventListener('submit',event=>{
            event.preventDefault();window.submissions++;
        ''' + action + '''});</script>''')

    async def wait(self, *, root=None, source_url=None, pages_before=None):
        return await _wait_registration_outcome(
            self.agent, self.page, root if root is not None else self.page,
            source_url=source_url or 'https://fixture.test/event/register',
            pages_before=pages_before if pages_before is not None else (self.page,),
            source_body='Conference call guest registration',
            timeout_error_type=Exception, submission_depth=0,
        )

    async def submit(self):
        self.assertTrue(await _click_registration_control_once(
            self.page, self.page.locator('#submit')))

    async def test_unrelated_playing_popup_cannot_complete_registration(self):
        await self.fixture()
        before = tuple(self.context.pages)
        await self.submit()
        unrelated = await self.context.new_page()
        await unrelated.goto('https://fixture.test/event/player')
        await unrelated.set_content('<video controls></video>')
        self.assertIsNone(await unrelated.opener())
        self.assertFalse(await self.wait(pages_before=before))
        self.assertIsNot(self.agent._registration_target_page, unrelated)
        self.assertEqual(await self.page.evaluate('submissions'), 1)

    async def test_related_survey_popup_cannot_complete_registration(self):
        await self.fixture("window.open('/survey', '_blank');")
        before = tuple(self.context.pages)
        async with self.page.expect_popup() as popup_event:
            await self.submit()
        popup = await popup_event.value
        await popup.wait_for_load_state('domcontentloaded')
        await popup.set_content('<video controls></video><h1>Survey</h1>')
        self.assertFalse(await self.wait(pages_before=before))
        self.assertIsNot(self.agent._registration_target_page, popup)
        self.agent._attach_media_watchers.assert_called_once_with(popup)
        self.assertTrue(any(call.kwargs.get('details', {}).get('reason') == 'non_player_destination'
                            for call in self.events.call_args_list))

    async def test_url_change_to_error_is_not_success(self):
        await self.fixture("history.pushState({}, '', '/error'); document.querySelector('form').remove(); document.body.insertAdjacentHTML('beforeend','<h2>Unable to register</h2>');")
        await self.submit()
        self.assertTrue(self.page.url.endswith('/error'))
        self.assertFalse(await self.wait())
        self.assertIsNotNone(self.agent._registration_failure_error)

    async def test_same_page_player_is_positive_transition(self):
        await self.fixture("document.querySelector('form').remove(); document.body.insertAdjacentHTML('beforeend','<audio controls></audio>');")
        await self.submit()
        self.assertTrue(await self.wait())
        self.assertIs(self.agent._registration_target_page, self.page)
        self.assertEqual(await self.page.evaluate('submissions'), 1)

    async def test_iframe_application_validation_is_not_hidden_by_owner_page(self):
        await self.page.set_content('<h1>Conference call</h1><iframe></iframe>')
        frame = self.page.frames[1]
        await frame.set_content('''<form><input name="company" value="Fixture Corporation">
          <div class="nui-form-field__error">Company name required</div></form>''')
        self.assertEqual(await frame.locator('input:invalid').count(), 0)
        self.assertFalse(await self.wait(root=frame.locator('form')))
        self.assertIn('validation', self.agent._registration_failure_error.lower())
        self.assertNotIn('Fixture Corporation', self.agent._registration_failure_error)

    async def test_delivered_click_ajax_pending_does_not_resubmit(self):
        await self.fixture("setTimeout(()=>{window.ajaxPending=true},50);")
        await self.submit()
        self.assertFalse(await self.wait())
        self.assertTrue(await self.page.evaluate('ajaxPending'))
        self.assertEqual(await self.page.evaluate('submissions'), 1)
        self.assertEqual(await self.page.evaluate('clicks'), 1)


if __name__ == '__main__':
    unittest.main()
