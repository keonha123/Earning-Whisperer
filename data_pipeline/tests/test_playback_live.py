"""Bounded media-clock observations in local Chromium, with no network."""

import base64
import io
import math
import os
import struct
from types import SimpleNamespace
import unittest
import wave

from data_pipeline.collectors.streams.browser.playback import detect_active_playback


def tone_url():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 16000)))
            for i in range(64000)
        ))
    return "data:audio/wav;base64," + base64.b64encode(output.getvalue()).decode()


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class PlaybackObservationBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        options = {"headless": True, "args": [
            "--disable-background-networking", "--no-sandbox",
            "--autoplay-policy=no-user-gesture-required",
        ]}
        if os.getenv("WEBCAST_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["WEBCAST_CHROMIUM_EXECUTABLE"]
        self.browser = await self.playwright.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.context = await self.browser.new_context()
        await self.context.route("**/*", lambda route: route.abort())
        self.page = await self.context.new_page()
        self.agent = SimpleNamespace(lifecycle="live", replay_seek_seconds=30)
        self.agent._playback_pages = lambda page: list(page.context.pages)

    async def real_audio(self, *, shadow=False):
        await self.page.set_content("<div id='host'></div>")
        await self.page.evaluate("""async ({url, shadow}) => {
            const root = shadow ? document.querySelector('#host').attachShadow({mode: 'open'}) : document.body;
            const media = document.createElement('audio');
            media.controls = true;
            media.src = url;
            media.muted = true;
            media.volume = 0;
            root.append(media);
            await media.play();
        }""", {"url": tone_url(), "shadow": shadow})

    async def stationary_media(self, *, pause_button=False):
        await self.page.set_content("<video></video>" + ("<button>Pause</button>" if pause_button else ""))
        await self.page.evaluate("""() => {
            const video = document.querySelector('video');
            Object.defineProperties(video, {
                currentTime: {get: () => 34},
                readyState: {get: () => 4},
                paused: {get: () => false},
                ended: {get: () => false},
            });
        }""")

    async def test_real_audio_clock_advances_and_is_unmuted(self):
        await self.real_audio()
        reason = await detect_active_playback(self.agent, self.page)
        self.assertIn("audio element is playing", reason)
        evidence = self.agent._playback_observations[-1]
        self.assertEqual(evidence["stage"], "clock_progressing")
        self.assertGreater(evidence["after"], evidence["before"])
        self.assertFalse(evidence["muted"])
        self.assertEqual(evidence["volume"], 1)
        self.assertNotIn("seeked", reason)

    async def test_nonzero_but_stationary_clock_is_not_progress(self):
        await self.stationary_media()
        self.assertIsNone(await detect_active_playback(self.agent, self.page))
        self.assertEqual(self.agent._playback_observations[-1]["stage"], "clock_stalled")

    async def test_pause_control_is_only_an_audio_pending_hint(self):
        await self.page.set_content("<button>Pause</button>")
        self.assertEqual(await detect_active_playback(self.agent, self.page), "visible pause control")
        self.assertEqual(self.agent._playback_observations, [
            {"stage": "control_seen", "reason": "visible pause control"},
        ])

    async def test_pause_button_cannot_promote_a_stalled_clock(self):
        await self.stationary_media(pause_button=True)
        await detect_active_playback(self.agent, self.page)
        self.assertNotIn("clock_progressing", [item["stage"] for item in self.agent._playback_observations])

    async def test_real_audio_inside_shadow_root_is_observed(self):
        await self.real_audio(shadow=True)
        self.assertIn("audio element is playing", await detect_active_playback(self.agent, self.page))
        self.assertEqual(self.agent._playback_observations[-1]["stage"], "clock_progressing")

    async def test_low_ready_state_with_growing_clock_still_works(self):
        await self.stationary_media()
        await self.page.evaluate("""() => {
            const video = document.createElement('video');
            document.body.replaceChildren(video);
            const start = performance.now();
            Object.defineProperties(video, {
                currentTime: {get: () => 34 + (performance.now() - start) / 1000},
                readyState: {get: () => 0},
                paused: {get: () => false},
                ended: {get: () => false},
            });
        }""")
        self.assertIn("video element is playing", await detect_active_playback(self.agent, self.page))
        self.assertEqual(self.agent._playback_observations[-1]["ready_state"], 0)

    async def test_page_scoped_probe_does_not_use_another_tabs_audio(self):
        await self.real_audio()
        target = await self.page.context.new_page()
        await target.set_content("<p>Waiting for webcast</p>")
        self.assertIsNone(await detect_active_playback(self.agent, target, include_context_pages=False))
        self.assertEqual(self.agent._playback_observations, [])


if __name__ == "__main__":
    unittest.main()
