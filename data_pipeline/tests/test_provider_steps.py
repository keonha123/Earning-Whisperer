"""Provider-common actions: strict schema plus actual local Chromium DOM tests."""

import base64
from copy import deepcopy
from datetime import date
import io
import math
import os
import struct
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

from data_pipeline.collectors.streams.browser.provider_steps import apply_provider_steps, valid_provider_recipe


HOST = "event.webcasts.com"
URL = f"https://{HOST}/starthere.jsp?ei=current"


def registration_recipe():
    return SimpleNamespace(
        recipe_id=1, domain=HOST, stage="registration", lifecycle="replay",
        target_href_path=None, selectors=(),
        evidence={
            "scope": "provider_common", "domain": HOST, "stage": "registration",
            "preconditions": [{"kind": "visible", "target": {"label": "Email"}}],
            "steps": [
                {"action": "fill", "target": {"label": "Email"}, "profile_field": "email"},
                {"action": "select", "target": {"label": "Country"}, "profile_field": "country"},
                {"action": "click", "target": {"role": "button", "name": "Register"}},
            ],
            "postconditions": [{"kind": "registration_complete", "target": {"role": "button", "name": "Play"}}],
        },
    )


def playback_recipe():
    recipe = registration_recipe()
    recipe.recipe_id = 2
    recipe.stage = recipe.evidence["stage"] = "playback"
    recipe.evidence["preconditions"] = [{"kind": "visible", "target": {"role": "button", "name": "Play"}}]
    recipe.evidence["steps"] = [
        {"action": "click", "target": {"role": "button", "name": "Play"}},
        {"action": "unmute", "target": {"media": "audio"}},
    ]
    recipe.evidence["postconditions"] = [{"kind": "media_progress", "target": {"media": "audio"}}]
    return recipe


class ProviderRecipeSchemaTest(unittest.TestCase):
    def test_only_explicit_common_scope_can_cross_replay_boundary(self):
        recipe = registration_recipe()
        self.assertTrue(valid_provider_recipe(recipe, stage="registration", hostname=HOST))
        recipe.evidence.pop("scope")
        self.assertFalse(valid_provider_recipe(recipe, stage="registration", hostname=HOST))

    def test_historical_urls_saved_values_and_nonsemantic_selectors_are_rejected(self):
        examples = [
            {"action": "goto", "url": "https://old.example.test/2025"},
            {"action": "fill", "target": {"label": "Email"}, "value": "saved@example.test"},
            {"action": "fill", "target": {"selector": "#email"}, "profile_field": "email"},
            {"action": "click", "target": {"role": "button", "name": "Q3 2025 Webcast"}},
            {"action": "fill", "target": {"label": "Email"}, "profile_field": "password"},
            {"action": [], "target": {"label": "Email"}},
            {"action": "fill", "target": {"role": [], "name": "Email"}, "profile_field": "email"},
        ]
        for step in examples:
            with self.subTest(step=step):
                recipe = registration_recipe()
                recipe.evidence["steps"][0] = step
                self.assertFalse(valid_provider_recipe(recipe, stage="registration", hostname=HOST))

    def test_old_recipe_href_and_missing_stage_checkpoints_are_rejected(self):
        recipe = registration_recipe()
        recipe.target_href_path = "/old-earnings"
        self.assertFalse(valid_provider_recipe(recipe, stage="registration", hostname=HOST))
        recipe = playback_recipe()
        recipe.evidence["postconditions"] = [{"kind": "visible", "target": {"role": "button", "name": "Pause"}}]
        self.assertFalse(valid_provider_recipe(recipe, stage="playback", hostname=HOST))


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class ProviderStepsBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
        from data_pipeline.collectors.streams.browser.navigation import make_target_proof
        from data_pipeline.collectors.streams.browser.rules import InvestorProfile

        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        options = {"headless": True, "args": ["--disable-background-networking", "--mute-audio"]}
        if os.getenv("WEBCAST_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["WEBCAST_CHROMIUM_EXECUTABLE"]
        self.browser = await self.playwright.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="<body></body>"))
        await self.page.goto(URL)
        profile = InvestorProfile("current@example.test", "", "Current", "Investor", "Current Company")
        with mock.patch.dict(os.environ, {
            "WEBCAST_LIFECYCLE": "live", "WEBCAST_TARGET_DATE": "2026-09-17",
            "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "true", "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false",
            "WEBCAST_REGISTRATION_REQUIRE_APPROVAL": "false",
        }, clear=True):
            self.agent = BrowserWebcastAgent("TEST", "https://issuer.example.test", profile=profile)
        self.agent.target_date = date(2026, 9, 17)
        self.agent.live_target_proof = make_target_proof(self.agent, "https://issuer.example.test", URL,
                                                        "September 17, 2026 earnings call")
        self.agent.provider_steps_wait_seconds = 1

    async def form(self, *, pending=False):
        action = "" if pending else "this.remove(); document.getElementById('play').hidden=false;"
        await self.page.set_content('''<h1>September 17, 2026 Earnings Call</h1>
          <form onsubmit="event.preventDefault();window.submits=(window.submits||0)+1;
          window.submittedEmail=document.getElementById('email').value;''' + action + '''">
          <label>Email<input id="email" type="email" required></label>
          <label for="country">Country</label><select id="country"><option>United States</option><option>Canada</option></select>
          <button type="submit">Register</button></form><button id="play" hidden>Play</button>''')

    async def test_current_profile_fills_selects_and_submits_once(self):
        await self.form()
        _, applied = await apply_provider_steps(self.agent, self.page, registration_recipe(), stage="registration")
        self.assertTrue(applied)
        self.assertEqual(await self.page.evaluate("window.submittedEmail"), "current@example.test")
        self.assertEqual(await self.page.evaluate("window.submits"), 1)

    async def test_wrong_provider_or_wrong_event_cannot_fill(self):
        await self.form()
        recipe = registration_recipe()
        recipe.domain = recipe.evidence["domain"] = "another.example.test"
        self.assertFalse((await apply_provider_steps(self.agent, self.page, recipe, stage="registration"))[1])
        self.agent.live_target_proof["target_url"] = URL.replace("current", "old")
        self.assertFalse((await apply_provider_steps(self.agent, self.page, registration_recipe(), stage="registration"))[1])
        self.assertEqual(await self.page.get_by_label("Email", exact=True).input_value(), "")

    async def test_missing_or_ambiguous_precondition_has_no_partial_fill(self):
        await self.form()
        await self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<label>Email<input></label>')")
        self.assertFalse((await apply_provider_steps(self.agent, self.page, registration_recipe(), stage="registration"))[1])
        self.assertEqual(await self.page.locator("#email").input_value(), "")

    async def test_pending_submission_is_not_repeated(self):
        await self.form(pending=True)
        for _ in range(2):
            self.assertFalse((await apply_provider_steps(self.agent, self.page, registration_recipe(), stage="registration"))[1])
        self.assertTrue(self.agent._provider_registration_pending)
        self.assertEqual(await self.page.evaluate("window.submits"), 1)

    async def test_submission_permission_and_approval_still_apply(self):
        await self.form()
        self.agent.allow_registration_submission = False
        self.assertFalse((await apply_provider_steps(self.agent, self.page, registration_recipe(), stage="registration"))[1])
        self.agent.allow_registration_submission = True
        self.agent.require_registration_approval = True
        self.assertFalse((await apply_provider_steps(self.agent, self.page, registration_recipe(), stage="registration"))[1])
        self.assertEqual(await self.page.locator("#email").input_value(), "")

    async def player(self, *, starts=True):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"".join(struct.pack("<h", int(2000 * math.sin(i * 2 * math.pi * 440 / 16000))) for i in range(48000)))
        audio = base64.b64encode(buffer.getvalue()).decode()
        click = "document.getElementById('audio').play()" if starts else "window.clicked=true"
        await self.page.set_content(f'<h1>September 17, 2026 Earnings Call</h1><audio id="audio" controls muted src="data:audio/wav;base64,{audio}"></audio><button onclick="{click}">Play</button>')

    async def test_playback_requires_progress_and_unmutes_current_media(self):
        await self.player()
        self.assertTrue((await apply_provider_steps(self.agent, self.page, playback_recipe(), stage="playback"))[1])
        self.assertFalse(await self.page.locator("audio").evaluate("el => el.muted"))

    async def test_click_without_media_progress_is_not_success(self):
        await self.player(starts=False)
        self.assertFalse((await apply_provider_steps(self.agent, self.page, playback_recipe(), stage="playback"))[1])


if __name__ == "__main__":
    unittest.main()
