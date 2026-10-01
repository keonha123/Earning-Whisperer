"""Registration submission regressions using local, network-blocked DOM fixtures."""

import os
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.registration import (
    _click_registration_control_once, _try_provider_registration,
)


class ProviderRegistrationIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_completed_common_recipe_bypasses_generic_form_handling(self):
        agent = SimpleNamespace(lifecycle="live", registration_preview_only=False)
        page = SimpleNamespace(url="https://provider.example/current")
        with (
            mock.patch("data_pipeline.collectors.streams.browser.learning._load_verified_provider_steps", return_value=[object()]),
            mock.patch("data_pipeline.collectors.streams.browser.provider_steps.apply_provider_steps", new=mock.AsyncMock(return_value=(page, True))) as apply,
        ):
            self.assertTrue(await _try_provider_registration(agent, page))
        self.assertIs(agent._registration_target_page, page)
        apply.assert_awaited_once()

    async def test_pending_submission_stops_before_generic_or_another_recipe(self):
        agent = SimpleNamespace(lifecycle="live", registration_preview_only=False)
        page = SimpleNamespace(url="https://provider.example/current")

        async def pending(*args, **kwargs):
            agent._provider_registration_pending = True
            return page, False

        with (
            mock.patch("data_pipeline.collectors.streams.browser.learning._load_verified_provider_steps", return_value=[object(), object()]),
            mock.patch("data_pipeline.collectors.streams.browser.provider_steps.apply_provider_steps", new=mock.AsyncMock(side_effect=pending)) as apply,
        ):
            self.assertFalse(await _try_provider_registration(agent, page))
        apply.assert_awaited_once()
        self.assertIn("REGISTRATION_PENDING", agent._registration_failure_error)

    async def test_late_completed_pending_form_is_not_submitted_again(self):
        agent = SimpleNamespace(
            lifecycle="live", registration_preview_only=False,
            _provider_registration_pending=True,
            has_registration_form=mock.AsyncMock(return_value=False),
        )
        page = SimpleNamespace(url="https://provider.example/current")
        with mock.patch("data_pipeline.collectors.streams.browser.registration.registration_transition_state",
                        new=mock.AsyncMock(return_value={"state": "passed", "reason": "player_ready"})):
            self.assertTrue(await _try_provider_registration(agent, page))
        self.assertFalse(agent._provider_registration_pending)

    async def test_nonlive_and_preview_keep_the_original_form_path(self):
        for lifecycle, preview in (("replay", False), ("live", True)):
            agent = SimpleNamespace(lifecycle=lifecycle, registration_preview_only=preview)
            self.assertIsNone(await _try_provider_registration(agent, object()))


class TimeoutControl:
    def __init__(self, handle, *, after_click=False):
        self.handle = handle
        self.after_click = after_click

    async def element_handle(self):
        return self

    async def evaluate(self, *args):
        return await self.handle.evaluate(*args)

    async def click(self, **kwargs):
        if self.after_click:
            await self.handle.click(**kwargs)
        raise TimeoutError("synthetic click acknowledgement timeout")


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class RegistrationSubmissionBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        options = {"headless": True, "args": ["--disable-background-networking", "--no-sandbox"]}
        if os.getenv("WEBCAST_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["WEBCAST_CHROMIUM_EXECUTABLE"]
        self.browser = await self.playwright.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.abort())

    async def fixture(self, button='<button id="submit" type="submit">Register</button>', field=""):
        await self.page.set_content(f"<form id='registration'>{field}{button}</form>" + """
            <script>
            window.submissions = 0;
            window.clicks = 0;
            registration.addEventListener('submit', event => {
                event.preventDefault();
                window.submissions += 1;
            });
            document.querySelector('#submit').addEventListener('click', () => window.clicks += 1);
            </script>
        """)
        return self.page.locator("#submit")

    async def test_native_submit_controls_dispatch_once(self):
        for markup in (
            '<button id="submit" type="submit">Register</button>',
            '<button id="submit">Register</button>',
            '<input id="submit" type="submit" value="Register">',
        ):
            with self.subTest(markup=markup):
                control = await self.fixture(markup)
                self.assertTrue(await _click_registration_control_once(self.page, control))
                self.assertEqual(await self.page.evaluate("submissions"), 1)

    async def test_delayed_javascript_button_is_not_resubmitted(self):
        control = await self.fixture('<button id="submit" type="button">Register</button>')
        await control.evaluate("element => element.addEventListener('click', () => setTimeout(() => window.accepted = true, 80))")
        self.assertTrue(await _click_registration_control_once(self.page, control))
        await self.page.wait_for_function("window.accepted === true")
        self.assertEqual(await self.page.evaluate("clicks"), 1)
        self.assertEqual(await self.page.evaluate("submissions"), 0)

    async def test_timeout_before_dispatch_can_submit_native_control_once(self):
        control = await self.fixture()
        timeout = TimeoutControl(await control.element_handle())
        self.assertTrue(await _click_registration_control_once(self.page, timeout))
        self.assertEqual(await self.page.evaluate("submissions"), 1)
        self.assertEqual(await self.page.evaluate("clicks"), 0)

    async def test_timeout_after_native_submission_does_not_submit_twice(self):
        control = await self.fixture()
        timeout = TimeoutControl(await control.element_handle(), after_click=True)
        self.assertTrue(await _click_registration_control_once(self.page, timeout))
        self.assertEqual(await self.page.evaluate("submissions"), 1)

    async def test_timeout_after_javascript_click_does_not_submit_form(self):
        control = await self.fixture('<input id="submit" type="button" value="Register">')
        timeout = TimeoutControl(await control.element_handle(), after_click=True)
        self.assertTrue(await _click_registration_control_once(self.page, timeout))
        self.assertEqual(await self.page.evaluate("submissions"), 0)
        self.assertEqual(await self.page.evaluate("clicks"), 1)

    async def test_non_submit_button_cannot_be_passed_to_request_submit(self):
        control = await self.fixture('<button id="submit" type="button">Register</button>')
        timeout = TimeoutControl(await control.element_handle())
        self.assertFalse(await _click_registration_control_once(self.page, timeout))
        self.assertEqual(await self.page.evaluate("submissions"), 0)

    async def test_native_fallback_preserves_required_field_validation(self):
        control = await self.fixture(field='<input type="email" required>')
        timeout = TimeoutControl(await control.element_handle())
        self.assertFalse(await _click_registration_control_once(self.page, timeout))
        self.assertEqual(await self.page.evaluate("submissions"), 0)

    async def test_detached_control_does_not_submit_replacement_form(self):
        control = await self.fixture()
        handle = await control.element_handle()
        await handle.evaluate("element => element.remove()")
        timeout = TimeoutControl(handle)
        self.assertFalse(await _click_registration_control_once(self.page, timeout))
        self.assertEqual(await self.page.evaluate("submissions"), 0)


if __name__ == "__main__":
    unittest.main()
