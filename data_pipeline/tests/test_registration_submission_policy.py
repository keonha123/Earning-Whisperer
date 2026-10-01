"""Registration automation stays enabled except for explicit read-only runs."""

import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent


class RegistrationSubmissionPolicyTest(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, environment=None, **kwargs):
        with mock.patch.dict('os.environ', environment or {}, clear=True):
            return BrowserWebcastAgent('EWTEST', 'https://issuer.example/events', **kwargs)

    def test_normal_captures_default_to_submission_without_ticker_approval(self):
        for lifecycle in ('live', 'pre_live', 'replay', 'unknown'):
            with self.subTest(lifecycle=lifecycle):
                agent = self.make_agent({'WEBCAST_LIFECYCLE': lifecycle})
                self.assertTrue(agent.allow_registration_submission)
                self.assertTrue(agent.allow_privacy_consent_submission)
                self.assertIsNone(agent._registration_approval_error(
                    'https://webcast.example/register', ['email', 'company'], True))

    def test_explicit_disable_cannot_be_overridden_by_privacy_flag(self):
        agent = self.make_agent({
            'WEBCAST_ALLOW_REGISTRATION_SUBMISSION': 'false',
            'WEBCAST_ALLOW_PRIVACY_CONSENT_SUBMISSION': 'true',
        })
        self.assertFalse(agent.allow_registration_submission)
        self.assertFalse(agent.allow_privacy_consent_submission)
        self.assertIn('disabled', agent._registration_approval_error(
            'https://webcast.example/register', ['email'], False))

    def test_blank_privacy_setting_inherits_normal_submission(self):
        agent = self.make_agent({'WEBCAST_ALLOW_PRIVACY_CONSENT_SUBMISSION': ''})
        self.assertTrue(agent.allow_privacy_consent_submission)

    def test_explicit_privacy_disable_preserves_ordinary_registration(self):
        agent = self.make_agent({'WEBCAST_ALLOW_PRIVACY_CONSENT_SUBMISSION': 'false'})
        self.assertTrue(agent.allow_registration_submission)
        self.assertFalse(agent.allow_privacy_consent_submission)

    def test_existing_strict_manifest_mode_remains_opt_in(self):
        agent = self.make_agent({'WEBCAST_REGISTRATION_REQUIRE_APPROVAL': 'true'})
        self.assertIn('approval manifest is missing', agent._registration_approval_error(
            'https://webcast.example/register', ['email'], False))

    def test_boolean_flags_accept_common_values_consistently(self):
        for value in ('true', '1', ' YES ', 'on'):
            with self.subTest(value=value):
                agent = self.make_agent({'WEBCAST_ALLOW_REGISTRATION_SUBMISSION': value})
                self.assertTrue(agent.allow_registration_submission)
                preview = self.make_agent({'WEBCAST_REGISTRATION_PREVIEW_ONLY': value})
                self.assertTrue(preview.registration_preview_only)
                self.assertFalse(preview.allow_registration_submission)

    async def test_read_only_modes_block_meta_privacy_submission_before_dom_access(self):
        # Previously an inherited privacy=true bypassed both the registration
        # disable and preview/discovery, and could click a real submit button.
        modes = [({'WEBCAST_REGISTRATION_PREVIEW_ONLY': 'true'}, {}),
                 ({'WEBCAST_DISCOVERY_ONLY': 'true'}, {}), ({}, {'discovery_only': True})]
        for environment, kwargs in modes:
            with self.subTest(environment=environment, kwargs=kwargs):
                agent = self.make_agent({
                    'WEBCAST_ALLOW_REGISTRATION_SUBMISSION': 'true',
                    'WEBCAST_ALLOW_PRIVACY_CONSENT_SUBMISSION': 'true',
                    **environment,
                }, **kwargs)
                self.assertFalse(agent.allow_registration_submission)
                self.assertFalse(agent.allow_privacy_consent_submission)
                page = mock.Mock()
                page.url = 'https://metameetings.net/privacy'
                type(page).frames = mock.PropertyMock(side_effect=AssertionError('Read-only mode must not touch privacy form'))
                self.assertFalse(await agent._submit_metameetings_privacy_consent(page))


if __name__ == '__main__':
    unittest.main()
