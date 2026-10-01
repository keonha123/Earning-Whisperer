"""Final review regressions kept separate from the already integrated fixtures."""

import os
from types import SimpleNamespace
import unittest
from unittest import mock

try:
    from data_pipeline.tests import test_registration_outcome as fixtures
except ImportError:
    import test_registration_outcome as fixtures
from data_pipeline.collectors.streams.browser.registration import (
    _try_provider_registration, _wait_registration_outcome,
)


class PendingProviderEvidenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_disappeared_form_without_positive_checkpoint_stays_pending(self):
        agent = SimpleNamespace(
            lifecycle='live', registration_preview_only=False,
            _provider_registration_pending=True,
            _registration_target_page=None,
            has_registration_form=mock.AsyncMock(return_value=False),
        )
        page = SimpleNamespace(url='https://fixture.test/event/redirect')
        with mock.patch(
            'data_pipeline.collectors.streams.browser.registration.registration_transition_state',
            new=mock.AsyncMock(return_value={'state': 'pending', 'reason': 'no_positive_transition'}),
        ) as transition:
            self.assertFalse(await _try_provider_registration(agent, page))
        transition.assert_awaited_once_with(agent, page, page, page.url)
        self.assertTrue(agent._provider_registration_pending)
        self.assertIsNone(agent._registration_target_page)
        self.assertIn('REGISTRATION_PENDING', agent._registration_failure_error)
        self.assertIn('no_positive_transition', agent._registration_failure_error)


class _FrameWithUnavailableBody:
    def __init__(self, frame):
        self.frame = frame

    def __getattr__(self, name):
        return getattr(self.frame, name)

    def locator(self, selector):
        if selector == 'body':
            return SimpleNamespace(inner_text=mock.AsyncMock(side_effect=RuntimeError('frame detached')))
        return self.frame.locator(selector)


class _PageWithFrames:
    def __init__(self, page, frames):
        self.page = page
        self.frames = frames

    def __getattr__(self, name):
        return getattr(self.page, name)


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class RegistrationOutcomeReviewBrowserTest(unittest.IsolatedAsyncioTestCase):
    # Reuse fixture setup only, without inheriting its six unrelated tests.
    asyncSetUp = fixtures.RegistrationOutcomeBrowserTest.asyncSetUp
    make_agent = fixtures.RegistrationOutcomeBrowserTest.make_agent

    async def test_unavailable_unrelated_frame_does_not_hide_ready_main_player(self):
        await self.page.set_content('<h1>Current call</h1><audio controls></audio><iframe></iframe>')
        broken_frame = _FrameWithUnavailableBody(self.page.frames[1])
        owner = _PageWithFrames(self.page, [broken_frame, self.page.main_frame])
        result = await _wait_registration_outcome(
            self.agent, owner, self.page,
            source_url=self.page.url, pages_before=tuple(self.context.pages),
            source_body='Current call registration', timeout_error_type=Exception,
        )
        self.assertTrue(result)
        self.assertIs(self.agent._registration_target_page, owner)
        self.agent._fill_generic_registration_form.assert_not_awaited()

    async def test_unchanged_q4_compact_iframe_is_not_submitted_again(self):
        await self.page.set_content('<h1>Current call</h1><iframe></iframe>')
        frame = self.page.frames[1]
        await frame.set_content('''<form><h2>One more thing</h2>
            <label>Company name<input name="company" value="Fixture"></label>
            <button type="button">Register for this event</button></form>''')
        frame_body = await frame.locator('body').inner_text()
        result = await _wait_registration_outcome(
            self.agent, self.page, frame.locator('form'),
            source_url=self.page.url, pages_before=tuple(self.context.pages),
            source_body=frame_body, timeout_error_type=Exception,
        )
        self.assertFalse(result)
        self.agent._fill_generic_registration_form.assert_not_awaited()
        self.assertIn('registration_form_remaining', self.agent._registration_failure_error)


if __name__ == '__main__':
    unittest.main()
