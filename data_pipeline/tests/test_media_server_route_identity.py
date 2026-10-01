"""CTAS incident regression: a client-side slash must retain exact event proof."""
import os
import unittest
from datetime import date
from types import SimpleNamespace

from data_pipeline.collectors.streams.browser.navigation import (
    make_target_proof, provider_event_id, same_event_route, validate_target_page,
)
from data_pipeline.collectors.streams.webcast_learning import WebcastCandidate, candidate_identity_mismatch


START = 'https://edge.media-server.com/mmc/p/6agfne3p'


class MediaServerRouteIdentityTest(unittest.TestCase):
    def test_only_known_player_trailing_slash_is_equivalent(self):
        self.assertEqual(provider_event_id(START), 'media-server:6agfne3p')
        self.assertTrue(same_event_route(START, START + '/'))
        self.assertTrue(same_event_route(START + '/', START))
        self.assertTrue(same_event_route(START + '?sig=one', START + '/?sig=one'))

    def test_different_events_and_authorities_remain_rejected(self):
        for other in (
            START.replace('6agfne3p', 'fknnzy2d'),
            START.replace('edge.media-server.com', 'other.media-server.com'),
            START.replace('edge.media-server.com', 'edge.media-server.com.attacker.test'),
            START.replace('edge.media-server.com', 'edge.media-server.com:8443'),
            START.replace('https:', 'ftp:'),
            START + '/replay', START + '//',
        ):
            with self.subTest(other=other):
                self.assertFalse(same_event_route(START, other))

    def test_unknown_signed_query_and_fragment_semantics_are_preserved(self):
        for left, right in (
            (START + '?sig=one', START + '/?sig=two'),
            (START + '?event=one', START + '/?event=two'),
            (START + '?x=1&x=2', START + '/?x=2&x=1'),
            (START + '?sig=one', START + '/'),
            (START + '#registration', START + '/#replay'),
            ('https://unknown.test/event', 'https://unknown.test/event/'),
        ):
            with self.subTest(left=left, right=right):
                self.assertFalse(same_event_route(left, right))

    def test_existing_explicit_fiscal_period_mismatch_check_is_unchanged(self):
        candidate = WebcastCandidate('heading', (), None, 'Q2 2027 Cintas Earnings Conference Call', '', '', None, 'h1', {})
        self.assertIsNotNone(candidate_identity_mismatch(candidate, target_year=2027, target_quarter='Q1'))


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class MediaServerHistoryCanonicalizationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-background-networking'])
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        self.agent = SimpleNamespace(lifecycle='live', ticker='CTAS', target_date=date(2026, 9, 23), _live_redirect_edges=set())
        self.agent.live_target_proof = make_target_proof(self.agent,
            'https://www.cintas.com/investors/earnings-webcast/event-details', START,
            'Q1 2027 Cintas Corporation Earnings Conference Call Sep. 23 2026 10:00 AM ET')

    async def render(self, path='/mmc/p/6agfne3p/', heading='Q1 2027 Cintas Corporation Earnings Conference Call'):
        html = f'''<h1>{heading}</h1><time>9/23/2026 2:00 PM</time>
          <form><label>First name<input></label><button type="submit">Submit</button></form>
          <script>history.replaceState(null, '', {path!r});</script>'''
        await self.page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html)
                              if route.request.url == START else route.abort())
        await self.page.goto(START, wait_until='domcontentloaded')

    async def test_ctas_history_slash_retains_fresh_proof_without_redirect(self):
        await self.render()
        self.assertEqual(self.page.url, START + '/')
        self.assertEqual(self.agent._live_redirect_edges, set())
        self.assertTrue(await validate_target_page(self.agent, self.page))

    async def test_changed_event_hash_still_rejected_even_with_redirect_edge(self):
        await self.render(path='/mmc/p/fknnzy2d/')
        self.agent._live_redirect_edges.add((START, self.page.url))
        self.assertFalse(await validate_target_page(self.agent, self.page))

    async def test_explicit_wrong_event_date_still_rejected(self):
        await self.render(heading='Cintas Earnings Conference Call September 24, 2026')
        self.assertFalse(await validate_target_page(self.agent, self.page))

    async def test_canonical_player_does_not_bypass_missing_proof(self):
        await self.render()
        self.agent.live_target_proof = None
        self.assertFalse(await validate_target_page(self.agent, self.page))
