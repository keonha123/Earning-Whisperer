"""A same-day analyst follow-up must not replace the primary earnings call."""
from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.learning import (
    _candidate_rejection_reason, _live_element_candidate,
)
from data_pipeline.collectors.streams.browser.navigation import make_target_proof
from data_pipeline.collectors.streams.webcast_learning import (
    WebcastCandidate, LearningSnapshot, choose_heuristic_candidate,
    live_candidate_identity_confirmation, live_event_identity_confirmation, make_recipe,
)


ISSUER = "https://investors.micron.com/events-and-presentations/"
PRIMARY = "https://events.q4inc.com/attendee/563781180"
FOLLOWUP = "https://events.q4inc.com/attendee/236969088"
FIXTURE = Path(__file__).parent / "fixtures" / "mu_same_day_calls_20260929.html"


def candidate(label, *, day="September 30, 2026", context="", ticker=""):
    return WebcastCandidate.from_dict({
        "candidate_id": "test", "selectors": ['a[href="https://provider.test/webcast/main"]'],
        "text": f"{ticker} {label}, {day}", "context_text": context,
        "href": "https://provider.test/webcast/main", "href_path": "/webcast/main",
        "tag_name": "a", "rect": {},
    })


class PrimaryLiveIdentityTests(unittest.TestCase):
    def test_financial_call_is_a_primary_live_identity(self):
        self.assertIsNotNone(live_candidate_identity_confirmation(
            candidate("Fourth Quarter 2026 Financial Call"), target_ticker="MU",
            target_date=date(2026, 9, 30)))

    def test_post_earnings_analyst_call_is_not_primary_even_with_nearby_main_text(self):
        for label in ("Post Earnings Analyst Call", "Post-Earnings Analyst Call", "Investor Day"):
            with self.subTest(label=label):
                row = candidate(label, context="September 30, 2026 Q4 earnings call")
                self.assertIsNone(live_candidate_identity_confirmation(
                    row, target_ticker="MU", target_date=date(2026, 9, 30)))
                self.assertIsNone(choose_heuristic_candidate([row], lifecycle="live"))

    def test_financial_call_still_requires_matching_date_and_ticker(self):
        for row in (candidate("Financial Call", day="June 24, 2026"),
                    candidate("Financial Call", ticker="Ticker: OTHER")):
            self.assertIsNone(live_candidate_identity_confirmation(
                row, target_ticker="MU", target_date=date(2026, 9, 30)))

    def test_plain_evidence_path_rejects_followup(self):
        self.assertIsNone(live_event_identity_confirmation(
            "Post Earnings Analyst Call September 30, 2026", target_date=date(2026, 9, 30)))

    def test_replay_training_can_still_consider_historical_followup(self):
        row = candidate("Webcast Post Earnings Analyst Call", day="June 24, 2026")
        self.assertIs(choose_heuristic_candidate(
            [row], lifecycle="replay", reference_date=date(2026, 9, 30)), row)


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires Chromium")
class PrimaryLiveCardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = patch.dict(os.environ, {
            "WEBCAST_LIFECYCLE": "live", "WEBCAST_TARGET_DATE": "2026-09-30",
            "WEBCAST_DISCOVERY_ONLY": "true", "WEBCAST_LEARNING_ENABLED": "false",
            "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false", "WEBCAST_VISION_ENABLED": "false",
            "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION": "true",
            "WEBCAST_LIVE_DIAGNOSTICS": "false", "WEBCAST_ARTIFACTS_DIR": tmp.name,
        }, clear=True)
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True, args=["--no-sandbox"])
        self.addAsyncCleanup(self.browser.close)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.fulfill(
            body="<body></body>", content_type="text/html"))
        await self.page.goto(ISSUER)
        self.fixture = FIXTURE.read_text()
        await self.page.set_content(self.fixture)
        self.agent = BrowserWebcastAgent("MU", ISSUER, discovery_only=True)

    async def choose(self):
        candidates = await self.agent._collect_candidates(self.page)
        snapshot = LearningSnapshot(Path("/unused.jpg"), Path("/unused.json"), tuple(candidates))
        chosen, strategy, confidence, _ = await self.agent._choose_learning_candidate(self.page, snapshot)
        return candidates, chosen, strategy, confidence

    async def test_actual_mu_cards_choose_primary_and_explain_followup_rejection(self):
        candidates, chosen, strategy, confidence = await self.choose()
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.href, PRIMARY)
        followup = next(row for row in candidates if row.href == FOLLOWUP)
        self.assertIn("non-primary event", _candidate_rejection_reason(self.agent, followup, ISSUER))
        self.assertNotIn("Post Earnings", chosen.context_text)
        recipe = make_recipe(ISSUER, chosen, strategy=strategy, lifecycle="live", confidence=confidence)
        pinned = await self.agent._find_recipe_button(self.page, recipe)
        self.assertIsNotNone(pinned)
        proof = self.agent.live_target_proof
        self.assertEqual(proof["target_url"], PRIMARY)
        self.assertIn("Fourth Quarter 2026 Financial Call", proof["evidence"])
        self.assertIn("September 30, 2026", proof["evidence"])
        self.assertNotIn("Post Earnings", proof["evidence"])

    async def test_generic_webcast_labels_inherit_only_their_own_card(self):
        await self.page.locator(".evergreen-event-webcast-link").evaluate_all(
            "xs=>xs.forEach(x=>{x.textContent='Webcast'; x.removeAttribute('aria-label'); x.removeAttribute('title');})")
        candidates, chosen, _, _ = await self.choose()
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.href, PRIMARY)
        followup = next(row for row in candidates if row.href == FOLLOWUP)
        self.assertIn("non-primary event", _candidate_rejection_reason(self.agent, followup, ISSUER))
        current = await _live_element_candidate(self.page.locator(f'a[href="{PRIMARY}"]'))
        self.assertIn("Financial Call", current.context_text)
        self.assertNotIn("Post Earnings", current.context_text)

    async def test_verified_recipe_keeps_actual_card_evidence_after_dispatch(self):
        candidates = await self.agent._collect_candidates(self.page)
        chosen = next(row for row in candidates if row.href == PRIMARY)
        recipe = make_recipe(ISSUER, chosen, strategy="heuristic", lifecycle="live", confidence=.9)
        with patch.object(self.agent, "_load_verified_recipes", return_value=[recipe]):
            pinned = await self.agent.find_webcast_button(self.page)
        self.assertIsNotNone(pinned)
        self.assertEqual(await pinned.get_attribute("href"), PRIMARY)
        self.assertIn("Fourth Quarter 2026 Financial Call", self.agent.live_target_identity_evidence)
        self.assertIn("September 30, 2026", self.agent.live_target_identity_evidence)
        self.assertEqual(self.agent.live_target_proof["target_url"], PRIMARY)
        self.assertIn("Fourth Quarter 2026 Financial Call", self.agent.live_target_proof["evidence"])

    async def test_card_without_date_cannot_borrow_a_neighbour_date(self):
        await self.page.set_content('<section><article><h2>Other earnings call September 30, 2026</h2></article>'
                                    '<article><h2>Financial Call</h2><a href="https://provider.test/webcast/new">Webcast</a>'
                                    '</article></section>')
        candidates, chosen, _, _ = await self.choose()
        self.assertIsNone(chosen)
        row = next(row for row in candidates if row.href)
        self.assertNotIn("September", row.context_text)
        current = await _live_element_candidate(self.page.locator("a"))
        self.assertNotIn("September", current.context_text)

    async def test_already_verified_parent_cannot_promote_followup_recipe(self):
        candidates = await self.agent._collect_candidates(self.page)
        followup = next(row for row in candidates if row.href == FOLLOWUP)
        self.agent.live_target_identity_confirmed = True
        self.agent.live_target_proof = make_target_proof(self.agent, ISSUER, ISSUER, "verified parent")
        recipe = make_recipe(ISSUER, followup, strategy="heuristic", lifecycle="live", confidence=.9)
        self.assertIsNone(await self.agent._find_recipe_button(self.page, recipe))

    async def test_destination_heading_rejects_legacy_proof_for_followup(self):
        await self.page.goto(FOLLOWUP)
        self.agent.live_target_proof = make_target_proof(self.agent, ISSUER, FOLLOWUP, "target date matched")
        await self.page.set_content('<h1>Micron Post Earnings Analyst Call</h1>')
        self.assertFalse(await self.agent._validate_live_target_page(self.page))
        await self.page.set_content('<title>Micron Post Earnings Analyst Call</title><div>Register</div>')
        self.assertFalse(await self.agent._validate_live_target_page(self.page))
        await self.page.set_content('<h1>Micron Fourth Quarter 2026 Financial Call</h1>')
        self.assertTrue(await self.agent._validate_live_target_page(self.page))


if __name__ == "__main__":
    unittest.main()
