"""Offline Chromium regressions for provider waiting notices and event guards."""

from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.navigation import make_target_proof
from data_pipeline.collectors.streams.browser import rules


FIXTURE = Path(__file__).parent / "fixtures" / "ccl_upcoming_20260929.html"
PROVIDER = "https://event.choruscall.com/mediaframe/webcast.html?webcastid=lE7HpeUW"
ISSUER = "https://www.carnivalcorp.com/event/third-quarter-2026-earnings/"


class EarlyEntryClock(datetime):
    @classmethod
    def now(cls, tz=None):
        # Test the entry boundary: the schedule alone no longer requests wait.
        instant = datetime(2026, 9, 29, 13, 55, tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires Chromium")
class ProviderWaitingClassifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright

        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True, args=["--no-sandbox"])
        self.addAsyncCleanup(self.browser.close)
        self.context = await self.browser.new_context()
        # Every request is a local fixture response; no provider API is called.
        await self.context.route("**/*", lambda route: route.fulfill(
            body="<body></body>", content_type="text/html"))
        self.page = await self.context.new_page()
        await self.page.goto(PROVIDER)
        self.fixture = FIXTURE.read_text()
        await self.page.set_content(self.fixture)
        with patch.dict(os.environ, {
            "WEBCAST_LIFECYCLE": "live", "WEBCAST_TARGET_DATE": "2026-09-29",
            "WEBCAST_TARGET_TIME_UTC": "2026-09-29T14:00:00Z",
            "WEBCAST_TARGET_YEAR": "2026", "WEBCAST_TARGET_QUARTER": "Q3",
            "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false",
            "WEBCAST_LIVE_DIAGNOSTICS": "false", "WEBCAST_LEARNING_ENABLED": "false",
        }, clear=True):
            self.agent = BrowserWebcastAgent("CCL", ISSUER)
        self.agent.live_target_proof = make_target_proof(
            self.agent, ISSUER, PROVIDER, "September 29, 2026 Q3 earnings call")
        clock = patch.object(rules, "datetime", EarlyEntryClock)
        clock.start()
        self.addCleanup(clock.stop)

    async def test_actual_ccl_notice_is_waiting_at_early_entry(self):
        self.assertTrue(await self.agent._validate_live_target_page(self.page))
        self.assertEqual(await self.agent._detect_not_live_event(self.page),
                         "return to this page a few minutes before the start")

    async def test_other_common_notices_reach_the_same_classifier(self):
        # These already belong to the common rule; a private DOM vocabulary
        # must not silently drop one of them before event identity is checked.
        for notice in (
            "Entry to the live presentation is not yet available.",
            "Registration: come back closer to the event.",
            "Thank you for registering. You can access the webcast up to 15 minutes before.",
            "The webcast has not quite started.",
        ):
            with self.subTest(notice=notice):
                await self.page.set_content(
                    "<div><h1>CCL Q3 2026 earnings call</h1>"
                    "<p>September 29, 2026 10:00 AM EDT</p>"
                    f"<p>{notice}</p></div>")
                self.assertIsNotNone(await self.agent._detect_not_live_event(self.page))

    async def test_different_date_cannot_delay_current_call(self):
        await self.page.set_content(self.fixture.replace("September 29", "September 30"))
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_different_quarter_cannot_delay_current_call(self):
        await self.page.set_content(self.fixture.replace("Q3 2026", "Q2 2026"))
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_same_day_other_event_is_not_waiting_proof(self):
        await self.page.set_content(self.fixture.replace(
            "Carnival Corporation Q3 2026 Earnings Results", "Carnival Corporation Investor Day"))
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_mixed_event_dates_are_not_waiting_proof(self):
        await self.page.set_content(
            "<div>CCL Q3 2026 earnings call September 29, 2026. "
            "Another event September 30, 2026. "
            "Please return to this page a few minutes before the start.</div>")
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_hidden_notice_cannot_delay_active_call(self):
        await self.page.set_content("<div style='display:none'>" + self.fixture +
                                    "</div><h1>CCL Q3 2026 earnings call</h1><p>Broadcast is live.</p>")
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_notice_needs_verified_provider_route(self):
        self.agent.live_target_proof = None
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))
        await self.page.goto(ISSUER)
        await self.page.set_content(self.fixture)
        self.agent.live_target_proof = make_target_proof(self.agent, ISSUER, ISSUER, "dated event")
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_notice_on_different_provider_event_cannot_reuse_proof(self):
        await self.page.goto(PROVIDER.replace("lE7HpeUW", "different-event"))
        await self.page.set_content(self.fixture)
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_existing_undated_webinar_modal_still_works(self):
        url = "https://app.webinar.net/currentEvent/live"
        await self.page.goto(url)
        await self.page.set_content('<div role="dialog">The webinar has not quite started.</div>')
        self.agent.live_target_proof = make_target_proof(self.agent, ISSUER, url, "dated event")
        self.assertIsNotNone(await self.agent._detect_not_live_event(self.page))
        await self.page.set_content('<div role="dialog">Investor day webinar has not quite started.</div>')
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_waiting_skips_controls_then_allows_started_player(self):
        agent = self.agent
        agent._registration_target_page = self.page
        agent.post_registration_playback_wait_seconds = 1
        agent._wait_for_dynamic_page = AsyncMock()
        agent.accept_cookie_banners = AsyncMock()
        agent._submit_metameetings_privacy_consent = AsyncMock(return_value=False)
        agent._detect_access_barrier = AsyncMock(return_value=None)
        agent._save_storage_state = AsyncMock()
        agent.trigger_media_playback = AsyncMock(return_value=True)
        agent.detect_active_playback = AsyncMock(return_value="audio clock progressing")
        agent._apply_human_workflow = AsyncMock(return_value=(self.page, False))

        ready, _ = await agent._activate_registered_playback(self.context, self.page)
        self.assertFalse(ready)
        agent.trigger_media_playback.assert_not_awaited()
        agent.detect_active_playback.assert_not_awaited()
        agent._save_storage_state.assert_awaited_once_with(self.context)

        await self.page.set_content('<h1>Carnival Corporation Q3 2026 Earnings Results</h1>')
        ready, _ = await agent._activate_registered_playback(self.context, self.page)
        self.assertTrue(ready)
        self.assertIsNone(agent._not_live_reason)


if __name__ == "__main__":
    unittest.main()
