"""Live failure evidence is bounded, opt-in, and cannot submit or mutate forms."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from data_pipeline.collectors.streams.browser.diagnostics import capture_diagnostics


class LiveDiagnosticsPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_and_other_ticker_do_not_touch_page(self):
        agent = SimpleNamespace(ticker="LEN")
        with patch.dict(os.environ, {"WEBCAST_LIVE_DIAGNOSTICS": "false"}):
            self.assertIsNone(await capture_diagnostics(agent, object(), "failure"))
        with patch.dict(os.environ, {"WEBCAST_LIVE_DIAGNOSTICS": "true", "WEBCAST_LIVE_DIAGNOSTICS_TICKERS": "MSFT"}):
            self.assertIsNone(await capture_diagnostics(agent, object(), "failure"))

    async def test_observation_failure_is_nonfatal(self):
        with patch.dict(os.environ, {"WEBCAST_LIVE_DIAGNOSTICS": "true", "WEBCAST_LIVE_DIAGNOSTICS_TICKERS": "LEN"}), patch(
            "data_pipeline.collectors.streams.browser.diagnostics._capture", new=AsyncMock(side_effect=TimeoutError)
        ):
            self.assertIsNone(await capture_diagnostics(SimpleNamespace(ticker="LEN"), object(), "failure"))


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class LiveDiagnosticsBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        options = {"headless": True, "args": ["--no-sandbox", "--disable-background-networking"]}
        if os.getenv("WEBCAST_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["WEBCAST_CHROMIUM_EXECUTABLE"]
        self.browser = await self.playwright.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.context = await self.browser.new_context()
        await self.context.route("**/*", lambda route: route.fulfill(body="<body></body>", content_type="text/html"))
        self.page = await self.context.new_page()
        await self.page.goto("https://example.invalid/event?token=never-keep-me")
        await self.page.set_content('''<form><label>Email<input type="email" name="email" required value="private@example.invalid"></label>
          <label>Required<input name="required" required></label><textarea>never-retain-this</textarea>
          <button>Register</button></form><a href="https://example.invalid/join?secret=never-keep-me">Webcast September 17 2026</a>
          <video muted controls></video>''')
        await self.page.evaluate("window.submits=0;document.querySelector('form').addEventListener('submit', e=>{e.preventDefault();window.submits++});document.querySelector('video').volume=0.3")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {
            "WEBCAST_LIVE_DIAGNOSTICS": "true", "WEBCAST_LIVE_DIAGNOSTICS_TICKERS": "LEN",
            "WEBCAST_LIVE_DIAGNOSTICS_DIR": self.directory.name,
            "WEBCAST_LIVE_DIAGNOSTICS_SCREENSHOT": "false",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.agent = SimpleNamespace(ticker="LEN", profile=SimpleNamespace(email="private@example.invalid"))

    async def test_redacts_values_and_urls_and_observes_required_media_state(self):
        path = Path(await capture_diagnostics(self.agent, self.context, "registration_failed"))
        raw = path.read_text()
        self.assertNotIn("private@example.invalid", raw)
        self.assertNotIn("never-retain-this", raw)
        self.assertNotIn("never-keep-me", raw)
        data = json.loads(raw)
        frame = data["pages"][0]["frames"][0]
        self.assertTrue(next(x for x in frame["fields"] if x["name"] == "required")["value_missing"])
        self.assertEqual(frame["media"][0]["volume"], 0.3)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    async def test_screenshot_masks_without_changing_filled_form_or_media(self):
        with patch.dict(os.environ, {"WEBCAST_LIVE_DIAGNOSTICS_SCREENSHOT": "true"}):
            path = Path(await capture_diagnostics(self.agent, self.page, "playback_pending"))
        self.assertTrue(path.with_suffix(".jpg").is_file())
        self.assertEqual(path.with_suffix(".jpg").stat().st_mode & 0o777, 0o600)
        self.assertEqual(await self.page.locator('[name="email"]').input_value(), "private@example.invalid")
        self.assertEqual(await self.page.locator('textarea').input_value(), "never-retain-this")
        self.assertEqual(await self.page.evaluate("window.submits"), 0)
        self.assertTrue(await self.page.locator('video').evaluate("e=>e.muted"))
        self.assertEqual(await self.page.locator('video').evaluate("e=>e.volume"), 0.3)
