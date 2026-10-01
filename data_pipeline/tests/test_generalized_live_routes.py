"""Common route recovery and navigation identity regressions, without public sites."""
import asyncio
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from data_pipeline.collectors.streams.browser.learning import _candidate_rejection_reason
from data_pipeline.collectors.streams.browser.navigation import (
    find_live_target, is_event_navigation, official_listing_recovery_urls,
    make_target_proof, proof_is_fresh,
)
from data_pipeline.collectors.streams.webcast_learning import WebcastCandidate, WebcastRecipe
from data_pipeline.tests.test_live_navigation import make_agent


class GeneralizedRouteRulesTest(unittest.TestCase):
    def test_navigation_does_not_borrow_neighbor_earnings_identity(self):
        agent = make_agent("https://issuer.test/events/")
        for label, href in (
            ("Past Events", "https://issuer.test/events//list/?eventDisplay=past"),
            ("Today", "https://issuer.test/events/list/"),
            ("Events & Presentations", "https://issuer.test/events-and-presentations/"),
            ("Next Events", "https://issuer.test/events/list/?page=2"),
        ):
            with self.subTest(label=label):
                candidate = WebcastCandidate(
                    "nav", (), None, label, "", "", href, "a", {},
                    context_text="September 10, 2026 Q3 earnings call Watch Webcast",
                    href=href,
                )
                self.assertIsNone(agent._live_candidate_identity_confirmation(candidate))
                self.assertEqual(_candidate_rejection_reason(agent, candidate, agent.ir_url),
                                 "event_list_navigation")

    def test_navigation_rejection_survives_existing_target_confirmation(self):
        agent = make_agent("https://issuer.test/events/")
        agent._mark_live_target_identity_confirmed("September 10, 2026 Q3 earnings call")
        candidate = WebcastCandidate("nav", (), None, "Today", "", "",
                                     "/events/list/", "a", {})
        self.assertEqual(_candidate_rejection_reason(agent, candidate, agent.ir_url),
                         "event_list_navigation")

    def test_single_webcast_is_a_real_action_not_a_list(self):
        self.assertFalse(is_event_navigation("https://provider.test/player?ei=123", "Webcast"))
        self.assertFalse(is_event_navigation("/event/q3-2026", "Q3 2026 Earnings Call"))

    def test_saved_calendar_proof_cannot_authorize_live_entrypoint(self):
        url = "https://issuer.test/events/list/?eventDisplay=past"
        source_agent = make_agent("https://issuer.test")
        proof = make_target_proof(source_agent, source_agent.ir_url, url,
                                  "September 10, 2026 Q3 earnings call")
        self.assertFalse(proof_is_fresh(source_agent, proof))
        for supplied_proof in ("", json.dumps(proof)):
            with self.subTest(supplied_proof=bool(supplied_proof)):
                agent = make_agent(url, environment={
                    "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true",
                    "WEBCAST_LIVE_IDENTITY_PROOF": supplied_proof,
                })
                self.assertFalse(agent.live_target_identity_confirmed)
                self.assertFalse(agent.live_entrypoint_identity_verified)
                self.assertIsNone(agent.live_target_proof)

    def test_recovery_uses_existing_parent_path_without_search(self):
        for path, expected in (
            ("/investors/events-and-presentations/event-details/", "/investors/events-and-presentations/"),
            ("/events/event-details/2026/old/default.aspx", "/events/"),
            ("/news-and-events/event-detail/?tracking=x", "/news-and-events/"),
        ):
            with self.subTest(path=path):
                url = "https://issuer.test" + path
                self.assertEqual(official_listing_recovery_urls(url, url),
                                 ("https://issuer.test" + expected,))

    def test_recovery_does_not_guess_roots_or_cross_origins(self):
        start = "https://issuer.test/events/event-details/"
        for current in (
            "https://other.test/events/event-details/",
            "https://issuer.test:444/events/event-details/",
            "http://issuer.test/events/event-details/",
            "https://user:secret@issuer.test/events/event-details/",
            "https://issuer.test/event-details/",
            "https://issuer.test/events/",
            "https://issuer.test/player",
            "https://issuer.test/events/../event-details/",
            "https://issuer.test/events/%2e%2e/event-details/",
        ):
            with self.subTest(current=current):
                self.assertEqual(official_listing_recovery_urls(start, current), ())


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires local Chromium")
class GeneralizedRouteBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.documents = {}
        self.statuses = {}
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(("GET", self.path))
                document = outer.documents.get(self.path)
                self.send_response(outer.statuses.get(self.path, 200 if document is not None else 404))
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write((document or "<h1>Page not found</h1>").encode())
            def do_POST(self):
                outer.requests.append(("POST", self.path))
                self.send_response(500)
                self.end_headers()
            def log_message(self, *_):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()
        self.environment = mock.patch.dict(os.environ, {"WEBCAST_LIVE_RENDER_GRACE_SECONDS": "0"})
        self.environment.start()

    async def asyncTearDown(self):
        self.environment.stop()
        await self.browser.close()
        await self.playwright.stop()
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=2)

    async def test_empty_event_detail_recovers_official_list_and_current_target(self):
        self.documents["/investors/events-and-presentations/"] = """
            <article><h2>Q3 earnings call</h2><p>September 10, 2026</p>
            <a href='/provider?ei=current'>Webcast</a></article>
            <article><h2>Q2 earnings call</h2><p>June 10, 2026</p>
            <a href='/provider?ei=old'>Webcast</a></article>"""
        agent = make_agent(self.base + "/investors/events-and-presentations/event-details/",
                           discovery_only=True)
        result = await agent.run()
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.discovered_url, self.base + "/provider?ei=current")
        self.assertIn(("GET", "/investors/events-and-presentations/"), self.requests)
        self.assertFalse(any("/provider" in path for _, path in self.requests))
        self.assertFalse(any(method == "POST" for method, _ in self.requests))
        self.assertLessEqual(len(self.requests), 5)
        self.assertEqual(agent._page_http_status, 200)

    async def test_wrong_event_after_listing_recovery_stays_unconfirmed(self):
        self.documents["/events/"] = """<article>June 10, 2026 Q2 earnings call
            <a href='/provider?ei=old'>Watch webcast</a></article>"""
        agent = make_agent(self.base + "/events/event-details/obsolete", discovery_only=True)
        result = await agent.run()
        self.assertFalse(result.success)
        self.assertFalse(result.target_identity_verified)
        self.assertEqual(result.retry_state, "target_not_found")
        self.assertEqual(self.requests.count(("GET", "/events/")), 1)
        self.assertFalse(any("/provider" in path for _, path in self.requests))

    async def test_nav_with_neighbor_date_cannot_become_a_discovered_target(self):
        self.documents["/calendar"] = """<div><h2>Q3 Earnings call</h2>
            <p>September 10, 2026</p>
            <a href='/events/list/?eventDisplay=past'>Past Events</a></div>"""
        self.documents["/events/list/?eventDisplay=past"] = "<h1>Events</h1>"
        agent = make_agent(self.base + "/calendar", discovery_only=True)
        result = await agent.run()
        self.assertFalse(result.success)
        self.assertFalse(agent.live_target_identity_confirmed)
        self.assertIsNone(agent.live_target_proof)

    async def test_valid_detail_wins_over_calendar_controls(self):
        self.documents["/calendar"] = """<div><h2>Q3 Earnings call</h2>
            <p>September 10, 2026</p>
            <a href='/events/list/?eventDisplay=past'>Past Events</a>
            <a href='/event/q3-current'>Q3 Earnings Webcast</a></div>"""
        agent = make_agent(self.base + "/calendar", discovery_only=True)
        result = await agent.run()
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.discovered_url, self.base + "/event/q3-current")
        self.assertFalse(any("eventDisplay" in path for _, path in self.requests))

    async def test_active_challenge_stops_fallback_and_preserves_access_failure(self):
        self.documents["/events/event-details/"] = "<h1>Verify you are human</h1>"
        agent = make_agent(self.base + "/events/event-details/", discovery_only=True)
        await self.page.goto(agent.ir_url)
        element, _ = await find_live_target(agent, self.page)
        self.assertIsNone(element)
        self.assertIn("manual verification", agent._live_navigation_barrier)
        self.assertNotIn(("GET", "/events/"), self.requests)
        self.assertFalse(agent.live_target_identity_confirmed)

    async def test_navigation_into_challenge_stops_before_recovery(self):
        self.documents["/"] = "<a href='/events/event-details/'>Events</a>"
        self.documents["/events/event-details/"] = "<h1>Verify you are human</h1>"
        agent = make_agent(self.base + "/", discovery_only=True)
        result = await agent.run()
        self.assertFalse(result.success)
        self.assertEqual(result.retry_state, "access_denied")
        self.assertNotIn(("GET", "/events/"), self.requests)

    async def test_empty_http_denial_stops_parent_listing_recovery(self):
        self.documents["/"] = "<a href='/events/event-details/'>Events</a>"
        self.documents["/events/event-details/"] = "<html></html>"
        self.statuses["/events/event-details/"] = 403
        agent = make_agent(self.base + "/", discovery_only=True)
        result = await agent.run()
        self.assertFalse(result.success)
        self.assertEqual(result.retry_state, "access_denied")
        self.assertIn("HTTP 403", result.error)
        self.assertNotIn(("GET", "/events/"), self.requests)

    async def test_old_recipe_cannot_reauthorize_a_calendar_control(self):
        self.documents["/calendar"] = """<article><p>September 10, 2026 Q3 earnings call</p>
            <a href='/events/list/'>Past Events</a></article>"""
        agent = make_agent(self.base + "/calendar", discovery_only=True)
        await self.page.goto(agent.ir_url)
        recipe = WebcastRecipe("", ('a[href="/events/list/"]',), None,
                               "Past Events", "/events/list/", "verified", "live", .9, {})
        agent._mark_live_target_identity_confirmed("September 10, 2026 Q3 earnings call")
        self.assertIsNone(await agent._find_recipe_button(self.page, recipe))


if __name__ == "__main__":
    unittest.main()
