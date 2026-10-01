"""Date identity and bounded navigation without external websites or services."""
import json
import os
import threading
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.navigation import (
    find_live_target, make_target_proof, proof_is_fresh, same_event_route,
    validate_target_page, observe_redirect,
)
from data_pipeline.collectors.streams.browser.rules import live_event_wait_reason
from data_pipeline.collectors.streams.webcast_learning import (
    live_event_identity_confirmation, candidate_identity_mismatch, WebcastCandidate,
)


def make_agent(url, **kwargs):
    environment = {
        "WEBCAST_LIFECYCLE": "live", "WEBCAST_TARGET_DATE": "2026-09-10",
        "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false",
        "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false",
        "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION": "true",
        "WEBCAST_TARGET_IDENTITY_READY_FILE": "",
        "WEBCAST_ARTIFACTS_DIR": "/tmp/ew-live-navigation-artifacts",
    }
    environment.update(kwargs.pop("environment", {}))
    with mock.patch.dict(os.environ, environment, clear=True):
        agent = BrowserWebcastAgent("TEST", url, **kwargs)
    agent._vision_selector.select = mock.AsyncMock(return_value=None)
    agent._load_verified_recipes = mock.Mock(return_value=[])
    agent._save_recipe = mock.Mock(return_value=None)
    return agent


class EventProofTest(unittest.IsolatedAsyncioTestCase):
    def test_expiry_and_publication_dates_do_not_replace_event_date(self):
        for suffix in (
            "Replay available until December 9, 2026",
            "Last updated December 9, 2026",
            "Registration closes December 9, 2026",
        ):
            evidence = f"September 10, 2026 Q3 earnings call. {suffix}"
            self.assertIsNotNone(live_event_identity_confirmation(
                evidence, target_date=date(2026, 9, 10),
            ))
            self.assertIsNone(live_event_wait_reason(
                evidence, target_date=date(2026, 9, 10),
                reference_time_utc=datetime(2026, 9, 10, 21, tzinfo=timezone.utc),
            ))
            candidate = WebcastCandidate("x", (), None, evidence, "", "", None, "a", {})
            self.assertIsNone(candidate_identity_mismatch(
                candidate, target_date=date(2026, 9, 10),
                target_time_utc=datetime(2026, 9, 10, 21, tzinfo=timezone.utc),
            ))

    def test_different_actual_event_date_is_still_rejected(self):
        self.assertIsNone(live_event_identity_confirmation(
            "December 9, 2026 Q4 earnings call", target_date=date(2026, 9, 10),
        ))

    def test_known_provider_id_and_unknown_signed_routes(self):
        self.assertTrue(same_event_route(
            "https://event.webcasts.com/starthere.jsp?ei=1&session=old",
            "https://event.webcasts.com/player.jsp?ei=1&session=new",
        ))
        self.assertFalse(same_event_route(
            "https://event.webcasts.com/starthere.jsp?ei=1",
            "https://event.webcasts.com/starthere.jsp?ei=2",
        ))
        self.assertFalse(same_event_route(
            "https://unknown.test/player?sig=one",
            "https://unknown.test/player?sig=two",
        ))

    async def test_undated_provider_requires_matching_fresh_proof(self):
        url = "https://event.webcasts.com/starthere.jsp?ei=1"
        agent = make_agent("https://issuer.test")
        page = SimpleNamespace(
            url=url, locator=lambda _: SimpleNamespace(first=SimpleNamespace(
                inner_text=mock.AsyncMock(return_value="Webcast registration"),
            )),
        )
        self.assertFalse(await validate_target_page(agent, page))
        agent.live_target_proof = make_target_proof(agent, agent.ir_url, url, "dated official IR")
        self.assertTrue(await validate_target_page(agent, page))
        page.url = "https://event.webcasts.com/starthere.jsp?ei=2"
        agent._live_redirect_edges.add((url, page.url))
        self.assertFalse(await validate_target_page(agent, page))
        page.url = url
        agent.live_target_proof["observed_at"] = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        self.assertFalse(await validate_target_page(agent, page))

    async def test_explicit_redirect_chain_preserves_undated_destination(self):
        agent = make_agent("https://issuer.test")
        start, final = "https://provider.test/event/current", "https://player.test/current"
        agent.live_target_proof = make_target_proof(agent, agent.ir_url, start, "dated IR")
        page = SimpleNamespace(
            url=final, locator=lambda _: SimpleNamespace(first=SimpleNamespace(
                inner_text=mock.AsyncMock(return_value="Registration"),
            )),
        )
        self.assertFalse(await validate_target_page(agent, page))
        agent._live_redirect_edges.add((start, final))
        self.assertTrue(await validate_target_page(agent, page))

    def test_supplied_proof_cannot_authenticate_another_target(self):
        agent = make_agent("https://issuer.test")
        proof = make_target_proof(agent, agent.ir_url, "https://provider.test/current", "dated")
        wrong = make_agent("https://provider.test/old", environment={
            "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true",
            "WEBCAST_LIVE_IDENTITY_PROOF": json.dumps(proof),
        })
        self.assertFalse(wrong.live_target_identity_confirmed)
        self.assertIsNone(wrong.live_target_proof)


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires local Chromium")
class NavigationBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(("GET", self.path))
                if self.path == "/":
                    document = '<a href="/events?view=upcoming">Events &amp; Presentations</a>'
                elif self.path.startswith("/events"):
                    document = """<div role="tab" onclick="document.querySelector('main').append(document.querySelector('template').content.cloneNode(true))">Upcoming Events</div>
                    <main></main><template><article><p>September 10, 2026 Q3 earnings call</p>
                    <a href="/provider?ei=current">Watch webcast</a></article>
                    <article><p>December 9, 2026 Q4 earnings call</p>
                    <a href="/provider?ei=wrong">Watch webcast</a></article></template>"""
                elif self.path == "/cycle":
                    document = '<a href="/cycle">Events</a>'
                elif self.path == "/delayed":
                    document = """<main></main><script>
                    setTimeout(() => document.querySelector('main').innerHTML =
                    '<article>September 10, 2026 Q3 earnings call <a href="/provider?ei=current">Watch webcast</a></article>', 350);
                    </script>"""
                elif self.path.startswith("/player"):
                    document = '<h1>Webcast player</h1><video controls></video>'
                else:
                    document = '<h1>Webcast registration</h1><form method="post" action="/submit"><input name="email"><button>Register</button></form>'
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(document.encode())
            def do_POST(self):
                outer.requests.append(("POST", self.path))
                self.send_response(302)
                self.send_header("Location", "/player")
                self.end_headers()
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()
        await __import__("asyncio").to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=2)

    async def test_dated_target_behind_undated_menu_and_tab(self):
        agent = make_agent(self.base, discovery_only=True)
        await self.page.goto(self.base)
        element, page = await find_live_target(agent, self.page)
        self.assertIsNotNone(element)
        self.assertEqual(await element.get_attribute("href"), "/provider?ei=current")
        self.assertIn(("GET", "/events?view=upcoming"), self.requests)
        self.assertTrue(proof_is_fresh(agent, agent.live_target_proof))
        self.assertEqual(agent.live_target_proof["target_url"], self.base + "/provider?ei=current")

    async def test_discovery_only_does_not_enter_registration_or_playback(self):
        agent = make_agent(self.base, discovery_only=True)
        agent.handle_registration_form = mock.AsyncMock(side_effect=AssertionError("registration"))
        agent.trigger_media_playback = mock.AsyncMock(side_effect=AssertionError("playback"))
        result = await agent.run()
        self.assertTrue(result.success, result.error)
        self.assertTrue(result.target_identity_verified)
        self.assertEqual(result.discovered_url, self.base + "/provider?ei=current")
        self.assertTrue(result.event_identity["verified"])
        self.assertFalse(result.playback_triggered)
        self.assertFalse(any(path.startswith("/provider") for _, path in self.requests))
        self.assertFalse(any(method == "POST" for method, _ in self.requests))
        agent.handle_registration_form.assert_not_awaited()
        agent.trigger_media_playback.assert_not_awaited()

    async def test_cyclic_navigation_is_bounded_and_does_not_confirm(self):
        agent = make_agent(self.base + "/cycle", discovery_only=True)
        await self.page.goto(self.base + "/cycle")
        element, _ = await find_live_target(agent, self.page)
        self.assertIsNone(element)
        self.assertFalse(agent.live_target_identity_confirmed)
        self.assertLessEqual(self.requests.count(("GET", "/cycle")), 2)

    async def test_client_rendered_link_gets_one_bounded_rescan(self):
        agent = make_agent(self.base + "/delayed", discovery_only=True)
        await self.page.goto(self.base + "/delayed")
        element, _ = await find_live_target(agent, self.page)
        self.assertIsNotNone(element)
        self.assertEqual(await element.get_attribute("href"), "/provider?ei=current")

    async def test_verified_ir_to_form_post_redirect_preserves_event_proof(self):
        agent = make_agent(self.base, discovery_only=True)
        await self.page.goto(self.base)
        element, _ = await find_live_target(agent, self.page)
        await element.click()
        self.page.context.on("request", lambda request: observe_redirect(agent, request))
        async def submit(actual_agent, page, timeout_type):
            await page.locator("input").fill("synthetic@example.test")
            await page.locator("button").click()
            await page.wait_for_url("**/player")
            return True
        agent.stages = replace(agent.stages, registration=SimpleNamespace(handle_registration_form=submit))
        self.assertTrue(await agent.handle_registration_form(self.page, TimeoutError))
        self.assertTrue(await validate_target_page(agent, self.page))
        self.assertIn(("POST", "/submit"), self.requests)
        self.assertEqual(self.page.url, self.base + "/player")

    async def test_verified_form_js_popup_keeps_causal_opener_only(self):
        agent = make_agent(self.base, discovery_only=True)
        await self.page.goto(self.base)
        element, _ = await find_live_target(agent, self.page)
        await element.click()
        await self.page.locator("form").evaluate(
            "form => form.onsubmit = event => {event.preventDefault(); window.open('/player');}"
        )
        async def submit(actual_agent, page, timeout_type):
            async with page.expect_popup() as popup:
                await page.locator("button").click()
            actual_agent._registration_target_page = await popup.value
            await actual_agent._registration_target_page.wait_for_load_state()
            return True
        agent.stages = replace(agent.stages, registration=SimpleNamespace(handle_registration_form=submit))
        self.assertTrue(await agent.handle_registration_form(self.page, TimeoutError))
        self.assertTrue(await validate_target_page(agent, agent._registration_target_page))


if __name__ == "__main__":
    unittest.main()
