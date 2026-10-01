"""Regression evidence for pre-live candidate feedback and player supervision."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.lifetime import PlaybackProgress, observe_player, recover_verified_player
from data_pipeline.collectors.streams.browser.navigation import make_target_proof


class PlaybackProgressTests(unittest.TestCase):
    def sample(self, current=10, **extra):
        return {"key": "event:audio", "current_time": current, "paused": False,
                "ended": False, "muted": False, "volume": 1, **extra}

    def test_frozen_nonzero_clock_warns_but_never_means_event_end(self):
        monitor = PlaybackProgress(0, 45)
        self.assertEqual(monitor.observe([self.sample()], 0)["status"], "observing_player")
        observed = monitor.observe([self.sample()], 46)
        self.assertEqual(observed["status"], "clock_stalled")
        self.assertTrue(observed["warning"])
        self.assertFalse(observed["progress"])
        self.assertNotIn("ended", observed["status"])

    def test_verified_waiting_music_or_silence_is_not_stall_failure(self):
        monitor = PlaybackProgress(0, 45)
        monitor.observe([self.sample()], 0)
        observed = monitor.observe([self.sample()], 3600, waiting=True)
        self.assertEqual(observed["status"], "waiting_for_start")
        self.assertFalse(observed["warning"])
        # Once the clock advances, music and speech are both valid playback.
        observed = monitor.observe([self.sample(15)], 3601)
        self.assertTrue(observed["progress"])
        self.assertEqual(observed["status"], "clock_progressing")

    def test_muted_progress_is_distinct_from_a_healthy_audio_path(self):
        monitor = PlaybackProgress(0, 45)
        monitor.observe([self.sample()], 0)
        observed = monitor.observe([self.sample(20, muted=True)], 10)
        self.assertEqual(observed["status"], "audio_muted")
        self.assertTrue(observed["warning"])
        self.assertTrue(observed["progress"])

    def test_missing_media_is_unobservable_not_ended(self):
        monitor = PlaybackProgress(0, 45)
        observed = monitor.observe([], 46)
        self.assertEqual(observed["status"], "player_unobservable")
        self.assertTrue(observed["warning"])


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires local Chromium")
class BrowserCandidateRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {
            "WEBCAST_LIFECYCLE": "live", "WEBCAST_TARGET_DATE": "2026-09-22",
            "WEBCAST_TARGET_TIME_UTC": "", "WEBCAST_TARGET_YEAR": "", "WEBCAST_TARGET_QUARTER": "",
            "WEBCAST_DISCOVERY_ONLY": "true", "WEBCAST_LEARNING_ENABLED": "false",
            "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false", "WEBCAST_VISION_ENABLED": "false",
            "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false", "WEBCAST_LIVE_IDENTITY_PROOF": "",
            "WEBCAST_DIRECT_TARGET_URL": "", "WEBCAST_CAPTURE_MANIFEST_FILE": "",
            "WEBCAST_TARGET_IDENTITY_READY_FILE": "", "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION": "true",
            "WEBCAST_LIVE_EXCLUDED_URLS": "", "WEBCAST_ARTIFACTS_DIR": self.directory.name,
            "WEBCAST_PROGRESS_DIR": self.directory.name + "/progress", "WEBCAST_ATTEMPT_ID": "browser-test",
            "WEBCAST_LIVE_DIAGNOSTICS": "false",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True, args=["--no-sandbox"])
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="<body></body>"))
        await self.page.goto("https://issuer.example.test/events")
        self.agent = BrowserWebcastAgent("TEST", self.page.url, discovery_only=True)

    async def candidates(self, bad, good):
        await self.page.set_content("<main>" + "".join(
            f'<section><h2>September 22, 2026 Q4 earnings call</h2>'
            f'<a id="{identifier}" href="{url}">Earnings conference call</a></section>'
            for identifier, url in (("bad", bad), ("good", good))
        ) + "</main>")

    async def test_full_query_event_id_exclusion_selects_next_valid_candidate(self):
        bad = "https://provider.example.test/starthere.jsp?eventid=bad&token=secret-canary"
        good = "https://provider.example.test/starthere.jsp?eventid=good"
        await self.candidates(bad, good)
        self.agent.live_excluded_urls = (bad,)
        button = await self.agent.find_webcast_button(self.page)
        self.assertIsNotNone(button)
        self.assertEqual(await button.get_attribute("href"), good)
        inventories = list(Path(self.directory.name).glob("TEST-*.json"))
        self.assertTrue(inventories, "Discovery-only probes must persist candidate inventory")
        payload = json.loads(inventories[-1].read_text())
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["eligible_count"], 1)
        self.assertEqual(payload["rejection_counts"], {"excluded_event": 1})
        self.assertNotIn("secret-canary", inventories[-1].read_text())

    async def test_provider_host_exclusion_keeps_other_host_candidate(self):
        bad = "https://provider-a.example.test/starthere.jsp?eventid=current"
        good = "https://provider-b.example.test/starthere.jsp?eventid=current"
        await self.candidates(bad, good)
        self.agent.live_excluded_urls = (bad,)
        button = await self.agent.find_webcast_button(self.page)
        self.assertEqual(await button.get_attribute("href"), good)

    async def test_stale_selected_node_reranks_remaining_snapshot_candidate(self):
        bad = "https://provider.example.test/starthere.jsp?eventid=bad"
        good = "https://provider.example.test/starthere.jsp?eventid=good"
        await self.candidates(bad, good)
        original_snapshot = self.agent._capture_learning_snapshot
        async def remove_after_snapshot(page):
            snapshot = await original_snapshot(page)
            await page.locator("#bad").evaluate("element => element.remove()")
            return snapshot
        self.agent._capture_learning_snapshot = remove_after_snapshot
        button = await self.agent.find_webcast_button(self.page)
        self.assertIsNotNone(button)
        self.assertEqual(await button.get_attribute("href"), good)
        self.assertFalse(self.agent._selection_retry)

    async def test_malformed_href_does_not_erase_other_page_candidates(self):
        good = "https://provider.example.test/good"
        await self.candidates("http://[malformed", good)
        candidates = await self.agent._collect_candidates(self.page)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[1].href, good)

    async def test_discovery_rescans_keep_distinct_artifacts(self):
        await self.candidates("https://provider.example.test/a", "https://provider.example.test/b")
        first = await self.agent._capture_learning_snapshot(self.page)
        second = await self.agent._capture_learning_snapshot(self.page)
        self.assertNotEqual(first.candidates_path, second.candidates_path)
        self.assertTrue(first.candidates_path.is_file())
        self.assertTrue(second.candidates_path.is_file())

    async def make_player(self):
        await self.page.goto("https://app.webinar.net/testCurrent/live")
        await self.page.set_content("<h1>September 22, 2026 Q4 earnings call</h1><audio></audio>")
        await self.page.evaluate("""() => {
            const audio=document.querySelector('audio');
            for(const [key,value] of Object.entries({currentTime:10, paused:true, ended:false, readyState:4})) {
                Object.defineProperty(audio,key,{value,writable:true,configurable:true});
            }
            audio.muted=true; audio.volume=0;
            audio.play=async()=>{audio.paused=false;window.recoveryCount=(window.recoveryCount || 0)+1;};
        }""")
        self.agent.live_target_proof = make_target_proof(self.agent, self.agent.ir_url,
                                                        self.page.url, "dated official event")

    async def test_real_dom_observation_and_verified_recovery_are_bounded(self):
        await self.make_player()
        samples = await observe_player(self.page)
        self.assertEqual(len(samples), 1)
        self.assertTrue(samples[0]["paused"])
        self.assertTrue(samples[0]["muted"])
        self.assertEqual(samples[0]["current_time"], 10)
        self.assertEqual(await recover_verified_player(self.agent, self.page), 1)
        samples = await observe_player(self.page)
        self.assertFalse(samples[0]["paused"])
        self.assertFalse(samples[0]["muted"])
        self.assertEqual(samples[0]["volume"], 1)
        self.assertEqual(await self.page.evaluate("window.recoveryCount"), 1)
        self.assertEqual(await recover_verified_player(self.agent, self.page), 0)

    async def test_unverified_event_cannot_be_activated_by_stall_recovery(self):
        await self.make_player()
        self.agent.live_target_proof = None
        self.assertEqual(await recover_verified_player(self.agent, self.page), 0)
        self.assertIsNone(await self.page.evaluate("window.recoveryCount"))

    async def test_other_event_iframe_cannot_be_activated_by_parent_proof(self):
        await self.make_player()
        await self.page.evaluate("document.querySelector('audio').ended=true")
        await self.page.evaluate("""() => {
            const frame=document.createElement('iframe');
            frame.src='https://app.webinar.net/otherEvent/live';document.body.appendChild(frame);
        }""")
        iframe_element = await self.page.locator("iframe").element_handle()
        iframe = await iframe_element.content_frame()
        await iframe.wait_for_url("https://app.webinar.net/otherEvent/live", timeout=3000)
        await iframe.set_content("<audio></audio>")
        await iframe.evaluate("""() => {
            const audio=document.querySelector('audio');
            Object.defineProperty(audio,'readyState',{value:4});
            audio.play=async()=>{window.wasActivated=true;};
        }""")
        self.assertEqual(await recover_verified_player(self.agent, self.page), 0)
        self.assertIsNone(await iframe.evaluate("window.wasActivated"))

    async def test_an_ended_media_element_is_never_restarted(self):
        await self.make_player()
        await self.page.evaluate("document.querySelector('audio').ended=true")
        self.assertEqual(await recover_verified_player(self.agent, self.page), 0)
        self.assertIsNone(await self.page.evaluate("window.recoveryCount"))


if __name__ == "__main__":
    unittest.main()
