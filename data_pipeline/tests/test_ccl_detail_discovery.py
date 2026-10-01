"""Structured event dates must reach ranking and the pinned click target."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.learning import (
    _candidate_rejection_reason, _live_element_candidate,
)
from data_pipeline.collectors.streams.webcast_learning import LearningSnapshot, make_recipe


ISSUER = 'https://www.carnivalcorp.com/event/third-quarter-2026-earnings/'
PROVIDER = 'https://event.choruscall.com/mediaframe/webcast.html?webcastid=lE7HpeUW'
FIXTURE = Path(__file__).parent / 'fixtures' / 'ccl_q3_2026_official_detail.html'


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires Chromium')
class CclDetailDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {
            'WEBCAST_LIFECYCLE': 'live', 'WEBCAST_TARGET_DATE': '2026-09-29',
            'WEBCAST_DISCOVERY_ONLY': 'true', 'WEBCAST_LEARNING_ENABLED': 'false',
            'WEBCAST_GENERALIZED_LEARNING_ENABLED': 'false', 'WEBCAST_VISION_ENABLED': 'false',
            'WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION': 'true',
            'WEBCAST_LIVE_DIAGNOSTICS': 'false', 'WEBCAST_ARTIFACTS_DIR': tmp.name,
        }, clear=True)
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True, args=['--no-sandbox'])
        self.addAsyncCleanup(self.browser.close)
        env.start()
        self.addCleanup(env.stop)
        self.page = await self.browser.new_page()
        # Offline browser tests. Every URL, including an actual target click,
        # is fulfilled locally; no provider login or media is accessed.
        await self.page.route('**/*', lambda route: route.fulfill(
            body='<h1>Carnival Corporation Third Quarter 2026 Earnings</h1>', content_type='text/html'))
        await self.page.goto(ISSUER)
        self.agent = BrowserWebcastAgent('CCL', ISSUER, discovery_only=True)

    async def choose(self, html):
        await self.page.set_content(html)
        candidates = await self.agent._collect_candidates(self.page)
        snapshot = LearningSnapshot(Path('/unused.jpg'), Path('/unused.json'), tuple(candidates))
        chosen, strategy, confidence, _ = await self.agent._choose_learning_candidate(self.page, snapshot)
        return candidates, chosen, strategy, confidence

    async def test_actual_ccl_detail_selects_clicks_and_preserves_issuer_proof(self):
        candidates, chosen, strategy, confidence = await self.choose(FIXTURE.read_text())
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.href, PROVIDER)
        self.assertIn('Third Quarter 2026 Earnings', chosen.context_text)
        self.assertIn('event-date=2026-09-29', chosen.context_text)
        self.assertIsNone(_candidate_rejection_reason(self.agent, chosen, ISSUER))
        recipe = make_recipe(ISSUER, chosen, strategy=strategy, lifecycle='live', confidence=confidence)
        pinned = await self.agent._find_recipe_button(self.page, recipe)
        self.assertIsNotNone(pinned)
        self.assertEqual(await pinned.get_attribute('href'), PROVIDER)
        current = await _live_element_candidate(pinned)
        self.assertEqual(current.context_text, chosen.context_text)
        proof = self.agent.live_target_proof
        self.assertEqual(proof['target_url'], PROVIDER)
        self.assertIn('Third Quarter 2026 Earnings', proof['evidence'])
        self.assertIn('2026-09-29', proof['evidence'])
        await pinned.click()
        await self.page.wait_for_url(PROVIDER)
        self.assertTrue(await self.agent._validate_live_target_page(self.page))

    async def test_actual_ccl_wrong_structured_date_is_rejected(self):
        html = FIXTURE.read_text().replace('2026-09-29', '2026-06-24')
        candidates, _, _, _ = await self.choose(html)
        target = next(row for row in candidates if row.href == PROVIDER)
        self.assertIn('candidate date 2026-06-24', _candidate_rejection_reason(self.agent, target, ISSUER))

    async def test_pinned_node_rechecks_changed_date(self):
        _, chosen, strategy, confidence = await self.choose(FIXTURE.read_text())
        recipe = make_recipe(ISSUER, chosen, strategy=strategy, lifecycle='live', confidence=confidence)
        await self.page.locator('[title="2026-09-29"]').evaluate_all(
            "nodes=>nodes.forEach(node=>node.setAttribute('title','2026-06-24'))")
        self.assertIsNone(await self.agent._find_recipe_button(self.page, recipe))
        self.assertIsNone(self.agent.live_target_proof)

    async def test_semantic_event_time_works_without_visible_year(self):
        _, chosen, _, _ = await self.choose('<article itemscope itemtype="https://schema.org/Event">'
            '<h2>Third Quarter Earnings Call</h2><time datetime="2026-09-29T10:00:00-04:00">September 29</time>'
            f'<a href="{PROVIDER}">Webcast</a></article>')
        self.assertEqual(chosen.href, PROVIDER)
        self.assertIn('2026-09-29', chosen.context_text)

    async def test_missing_date_cannot_borrow_from_neighbour_or_global_script(self):
        candidates, chosen, _, _ = await self.choose('<h1>Other Earnings September 29, 2026</h1>'
            '<article><h2>Other Earnings</h2><time datetime="2026-09-29">September 29</time></article>'
            '<article><h2>Third Quarter Earnings</h2>'
            '<script type="application/ld+json">{"startDate":"2026-09-29"}</script>'
            f'<a href="{PROVIDER}">Webcast</a></article>')
        self.assertIsNone(chosen)
        target = next(row for row in candidates if row.href == PROVIDER)
        self.assertNotIn('2026-09-29', target.context_text)
        self.assertIsNone(self.agent._live_candidate_identity_confirmation(target))

    async def test_missing_heading_cannot_borrow_global_or_nested_card_title(self):
        _, chosen, _, _ = await self.choose('<h1>Other Earnings September 29, 2026</h1>'
            '<article><time datetime="2026-09-29">September 29</time>'
            '<article><h2>Other Earnings Call</h2><time datetime="2026-09-29">September 29</time></article>'
            f'<a href="{PROVIDER}">Webcast</a></article>')
        self.assertIsNone(chosen)

    async def test_detail_scope_does_not_lend_date_to_nested_undated_event(self):
        _, chosen, _, _ = await self.choose('<div class="event-detail"><h1>Main Earnings Call</h1>'
            '<time datetime="2026-09-29">September 29</time>'
            f'<article><h2>Other Earnings Call</h2><a href="{PROVIDER}">Webcast</a></article></div>')
        self.assertIsNone(chosen)

    async def test_conflicting_structured_dates_are_not_cherry_picked(self):
        _, chosen, _, _ = await self.choose('<article><h2>Third Quarter Earnings Call</h2>'
            '<time datetime="2026-09-29">September 29</time><time datetime="2026-06-24">June 24</time>'
            f'<a href="{PROVIDER}">Webcast</a></article>')
        self.assertIsNone(chosen)

    async def test_publication_and_accounting_dates_are_not_event_proof(self):
        for stamp in (
            '<time itemprop="datePublished" datetime="2026-09-29">September 29</time>',
            '<div itemprop="dateModified"><time datetime="2026-09-29">September 29</time></div>',
            '<p>Quarter ended <abbr title="2026-09-29">September 29</abbr></p>',
        ):
            with self.subTest(stamp=stamp):
                _, chosen, _, _ = await self.choose('<article><h2>Third Quarter Earnings Call</h2>'
                    + stamp + f'<a href="{PROVIDER}">Webcast</a></article>')
                self.assertIsNone(chosen)

    async def test_call_date_in_same_paragraph_as_fiscal_end_is_retained(self):
        _, chosen, _, _ = await self.choose('<article><h2>Third Quarter Earnings Call</h2>'
            '<p>Quarter ended <abbr title="2026-08-31">August 31, 2026</abbr>; '
            'call on <time datetime="2026-09-29">September 29</time></p>'
            f'<a href="{PROVIDER}">Webcast</a></article>')
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.href, PROVIDER)
        self.assertIn('event-date=2026-09-29', chosen.context_text)


if __name__ == '__main__':
    unittest.main()
