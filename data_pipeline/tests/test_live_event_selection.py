"""Regressions for mixed event dates and candidate-to-click identity.

The fixture mirrors the saved ADBE event-card texts with synthetic URLs.
Opt-in Chromium tests use set_content only, with all HTTP requests aborted.
"""

import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser import learning
from data_pipeline.collectors.streams.browser.flow import _selected_event_evidence
from data_pipeline.collectors.streams.browser.rules import live_event_wait_reason
from data_pipeline.collectors.streams.webcast_learning import (
    LearningSnapshot, WebcastRecipe, make_recipe,
)
from data_pipeline.storage.policies import stream_probe_retry_policy


def live_agent():
    with mock.patch.dict(os.environ, {
        "WEBCAST_LIFECYCLE": "live",
        "WEBCAST_TARGET_DATE": "2026-09-10",
        "WEBCAST_TARGET_TIME_UTC": "",
        "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false",
        "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false",
        "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION": "true",
        "WEBCAST_TARGET_IDENTITY_READY_FILE": "",
    }, clear=True):
        agent = BrowserWebcastAgent("ADBE", "https://issuer.example.test/events")
    agent._vision_selector.select = mock.AsyncMock(return_value=None)
    return agent


class LiveEventDateTest(unittest.IsolatedAsyncioTestCase):
    async def test_index_body_cannot_stop_live_discovery(self):
        agent = live_agent()
        # Reading this body used to reject the current call because the index
        # also announces the next quarter. No event has been selected yet.
        body = mock.AsyncMock(return_value="December 9, 2026 earnings webcast has not started")
        page = SimpleNamespace(frames=[SimpleNamespace(locator=lambda _: SimpleNamespace(inner_text=body))])
        self.assertIsNone(await agent._detect_not_live_event(page))
        body.assert_not_awaited()

    def test_current_event_is_not_delayed_by_next_quarter(self):
        now = datetime(2026, 9, 10, 21, 10, tzinfo=timezone.utc)
        for text in (
            "September 10, 2026 Q3 FY2026 earnings call Watch webcast",
            "September 10, 2026 earnings call. December 9, 2026 earnings webcast has not started",
        ):
            with self.subTest(text=text):
                self.assertIsNone(live_event_wait_reason(text, target_date=date(2026, 9, 10), reference_time_utc=now))

    def test_selected_future_event_still_waits(self):
        reason = live_event_wait_reason(
            "September 11, 2026 Q3 earnings call Watch webcast",
            target_date=date(2026, 9, 11),
            reference_time_utc=datetime(2026, 9, 10, 20, tzinfo=timezone.utc),
        )
        self.assertIn("scheduled event date is in the future", reason)

    def test_selected_event_preserves_early_entry_window(self):
        evidence = "September 10, 2026 Q3 earnings call 5:00 PM ET"
        with mock.patch.dict(os.environ, {"DATE_STREAM_EARLY_ENTRY_MINUTES": "5"}):
            reason = live_event_wait_reason(evidence, target_date=date(2026, 9, 10), reference_time_utc=datetime(2026, 9, 10, 20, 50, tzinfo=timezone.utc))
            self.assertIn("2026-09-10T21:00:00", reason)
            self.assertIsNone(live_event_wait_reason(evidence, target_date=date(2026, 9, 10), reference_time_utc=datetime(2026, 9, 10, 20, 56, tzinfo=timezone.utc)))

    def test_adbe_failure_is_retryable_without_schedule_change(self):
        error = (
            "NOT_LIVE_YET scheduled event date is in the future: December 9, 2026 "
            "| WEBCAST_EXITED_BEFORE_PLAYBACK_READY "
            "| MEDIA_FALLBACK_BLOCKED target_identity_unconfirmed"
        )
        with mock.patch.dict(os.environ, {"DATE_STREAM_DATE_ONLY_RETRY_MINUTES": "1"}):
            policy = stream_probe_retry_policy(error, watch_state="date_only", expected_date=date(2026, 9, 10))
        self.assertEqual(policy, {"reason": "candidate_unavailable", "retry_delay_minutes": 1, "requires_schedule_refresh": False})

    def test_excluding_old_event_does_not_exclude_current_query_or_fragment(self):
        agent = live_agent()
        agent.live_excluded_urls = ("https://provider.example.test/starthere.jsp?eventid=old&token=redacted",)
        self.assertTrue(agent._is_live_excluded_url("https://provider.example.test/starthere.jsp?session=new&eventid=old"))
        self.assertFalse(agent._is_live_excluded_url("https://provider.example.test/starthere.jsp?eventid=current"))
        self.assertFalse(agent._is_live_excluded_url("/starthere.jsp", "https://provider.example.test"))
        agent.live_excluded_urls = ("https://provider.example.test/player#/old",)
        self.assertFalse(agent._is_live_excluded_url("https://provider.example.test/player#/current"))


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class LiveEventBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        launch = {"headless": True, "args": ["--disable-background-networking"]}
        executable = os.getenv("WEBCAST_CHROMIUM_EXECUTABLE")
        if executable:
            launch["executable_path"] = executable
        self.browser = await self.playwright.chromium.launch(**launch)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.abort())
        await self.page.set_content((Path(__file__).parent / "fixtures/adbe_event_transitions.html").read_text())
        self.agent = live_agent()

    async def choose(self):
        candidates = tuple(await self.agent._collect_candidates(self.page))
        snapshot = LearningSnapshot(Path("/unused.jpg"), Path("/unused.json"), candidates)
        candidate, strategy, confidence, reason = await self.agent._choose_learning_candidate(self.page, snapshot)
        if candidate is None:
            return None
        return make_recipe(self.page.url, candidate, strategy=strategy, lifecycle="live", confidence=confidence, snapshot=snapshot)

    async def test_scheduled_live_and_archived_transitions(self):
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))
        self.assertIsNone(await self.choose())  # title/date present, link absent
        for state in ("live", "archived"):
            await self.page.evaluate("state => setEventState(state)", state)
            self.agent._reset_live_target_identity_confirmation()
            recipe = await self.choose()
            self.assertIsNotNone(recipe)
            self.assertFalse(self.agent.live_target_identity_confirmed)
            element = await self.agent._find_recipe_button(self.page, recipe)
            self.assertIsNotNone(element)
            self.assertTrue(self.agent.live_target_identity_confirmed)
            evidence = await _selected_event_evidence(self.agent, element)
            self.assertIn("September 10, 2026", evidence)
            self.assertNotIn("December 9, 2026", evidence)
            await element.click()
            self.assertEqual(await self.page.evaluate("clickedEvent"), "current")

    async def test_exact_href_beats_stale_positional_selector(self):
        await self.page.evaluate("setEventState('live')")
        recipe = await self.choose()
        # A positional selector now points to the older event; exact href wins.
        recipe.selectors = ('main > section:nth-of-type(1) > a', *recipe.selectors)
        element = await self.agent._find_recipe_button(self.page, recipe)
        await element.click()
        self.assertEqual(await self.page.evaluate("clickedEvent"), "current")

    async def test_element_stays_bound_when_the_dom_is_reordered(self):
        await self.page.evaluate("setEventState('live')")
        recipe = await self.choose()
        element = await self.agent._find_recipe_button(self.page, recipe)
        await self.page.evaluate("document.querySelector('main').prepend(document.querySelector('#current'))")
        await element.click()
        self.assertEqual(await self.page.evaluate("clickedEvent"), "current")

    async def test_stale_target_does_not_fall_back_to_another_event(self):
        await self.page.evaluate("setEventState('live')")
        recipe = await self.choose()
        await self.page.evaluate("setEventState('scheduled')")
        self.assertIsNone(await self.agent._find_recipe_button(self.page, recipe))
        self.assertFalse(self.agent.live_target_identity_confirmed)

    async def test_ambiguous_legacy_path_is_not_treated_as_first_match(self):
        await self.page.evaluate("setEventState('live')")
        recipe = WebcastRecipe("", (), None, "Watch webcast", "/starthere.jsp", "legacy", "live", .5, {})
        # Without target evidence there is no basis to choose one of three links.
        self.agent.lifecycle = "unknown"
        self.assertIsNone(await self.agent._find_recipe_button(self.page, recipe))
        self.agent.lifecycle = "live"
        element = await self.agent._find_recipe_button(self.page, recipe)
        await element.click()
        self.assertEqual(await self.page.evaluate("clickedEvent"), "current")

    async def test_exact_href_is_revalidated_against_current_event_text(self):
        await self.page.evaluate("setEventState('live')")
        recipe = await self.choose()
        await self.page.locator('#current p').evaluate("element => element.textContent = 'December 9, 2026 Q4 earnings call'")
        self.assertIsNone(await self.agent._find_recipe_button(self.page, recipe))
        self.assertFalse(self.agent.live_target_identity_confirmed)

    async def test_fiscal_year_label_does_not_hide_the_parent_event_date(self):
        await self.page.evaluate("setEventState('live')")
        await self.page.locator('#current-link').evaluate(
            "element => element.prepend(document.createTextNode('Q3 2026 earnings call '))"
        )
        recipe = await self.choose()
        element = await self.agent._find_recipe_button(self.page, recipe)
        self.assertIsNotNone(element)
        await element.click()
        self.assertEqual(await self.page.evaluate("clickedEvent"), "current")

    async def test_embedded_link_remains_bound_after_reorder(self):
        await self.page.evaluate("setEventState('live')")
        element = await self.agent._find_embedded_playback_link(self.page)
        self.assertIsNotNone(element)
        await self.page.evaluate("document.querySelector('main').prepend(document.querySelector('#current'))")
        await element.click()
        self.assertEqual(await self.page.evaluate("clickedEvent"), "current")
