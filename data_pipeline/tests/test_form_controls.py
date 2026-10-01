"""Network-blocked real Chromium regression tests for reusable form controls."""
import os
import time
import unittest

from data_pipeline.collectors.streams.browser.form_controls import (
    is_structured_choice, select_custom_option,
)


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class FormControlsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-background-networking"])
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.abort())

    async def fixture(self, *, relation='aria-controls="choices"', delay=0,
                      label="Example Corp", commit="selected", existing_menu=False):
        extra = '<ul id="unrelated" role="listbox"><li role="option" onclick="window.unrelatedClicked=true">Example Corp</li></ul>' if existing_menu else ''
        await self.page.set_content(f'''<form><div>
          <input id="company" role="combobox" {relation} aria-expanded="false">
          <input name="institutionId" type="hidden" id="selectedId">
          </div></form>{extra}
          <script>
          window.unrelatedClicked=false; window.choiceClicks=0;
          company.addEventListener('keydown', event => {{
            if(event.key !== 'ArrowDown' || document.querySelector('#choices')) return;
            setTimeout(() => {{
              const menu=document.createElement('ul'); menu.id='choices';menu.setAttribute('role','listbox');
              const option=document.createElement('li'); option.setAttribute('role','option');option.textContent={label!r};
              option.addEventListener('click', () => {{
                window.choiceClicks++;
                if({commit!r} === 'selected') {{ option.setAttribute('aria-selected','true'); company.setAttribute('aria-expanded','false'); }}
                if({commit!r} === 'hidden') {{ selectedId.value='exact-institution-123'; company.value='';menu.remove(); }}
                if({commit!r} === 'close') {{company.setAttribute('aria-expanded','false');menu.remove();}}
              }});
              menu.append(option);document.body.append(menu);company.setAttribute('aria-expanded','true');
            }}, {delay});
          }});
          </script>''')
        return self.page.locator('#company')

    async def test_portal_outside_form_delayed_and_explicit_open(self):
        control = await self.fixture(delay=250)
        result = await select_custom_option(control, "Example Corp", fill=True)
        self.assertTrue(result.success, result)
        self.assertEqual(await self.page.evaluate('choiceClicks'), 1)

    async def test_aria_owns_and_hidden_committed_value(self):
        control = await self.fixture(relation='aria-owns="choices"', commit="hidden")
        result = await select_custom_option(control, "Example Corp", fill=True)
        self.assertTrue(result.success, result)

    async def test_semantic_causal_menu_without_aria_reference(self):
        control = await self.fixture(relation='')
        result = await select_custom_option(control, "Example Corp", fill=True)
        self.assertTrue(result.success, result)

    async def test_existing_unrelated_menu_never_used(self):
        control = await self.fixture(relation='', existing_menu=True)
        result = await select_custom_option(control, "Example Corp", fill=True, timeout_ms=350)
        self.assertFalse(result.success, result)
        self.assertFalse(await self.page.evaluate('unrelatedClicked'))
        self.assertEqual(await self.page.evaluate('choiceClicks'), 0)

    async def test_explicit_owned_menu_still_works_with_unrelated_menu(self):
        control = await self.fixture(existing_menu=True)
        result = await select_custom_option(control, "Example Corp", fill=True)
        self.assertTrue(result.success, result)
        self.assertFalse(await self.page.evaluate('unrelatedClicked'))

    async def test_click_without_commit_is_failure(self):
        control = await self.fixture(commit='none')
        result = await select_custom_option(control, "Example Corp", fill=True, timeout_ms=400)
        self.assertFalse(result.success, result)
        self.assertEqual(result.reason, 'option_clicked_commit_unverified')
        self.assertEqual(await self.page.evaluate('choiceClicks'), 1)

    async def test_closed_menu_and_typed_text_do_not_prove_commit(self):
        control = await self.fixture(commit='close')
        result = await select_custom_option(control, "Example Corp", fill=True, timeout_ms=400)
        self.assertFalse(result.success, result)
        self.assertEqual(result.reason, 'option_clicked_commit_unverified')

    async def test_prefix_suggestion_is_not_an_exact_match(self):
        control = await self.fixture(label='Example Corp Other')
        result = await select_custom_option(control, "Example Corp", fill=True, timeout_ms=350)
        self.assertFalse(result.success, result)
        self.assertEqual(await self.page.evaluate('choiceClicks'), 0)

    async def test_native_select_remains_native_and_unchanged(self):
        await self.page.set_content('<select id="country"><option>Canada</option><option>United States</option></select>')
        result = await select_custom_option(self.page.locator('#country'), 'United States')
        self.assertFalse(result.success)
        self.assertEqual(result.kind, 'native_select')
        self.assertEqual(await self.page.locator('#country').input_value(), 'Canada')

    async def test_plain_company_text_verified(self):
        await self.page.set_content('<form><input name="company" required></form>')
        control = self.page.locator('input')
        self.assertFalse(await is_structured_choice(control))
        result = await select_custom_option(control, 'Example Corp', fill=True)
        self.assertTrue(result.success, result)
        self.assertEqual(result.kind, 'text')

    async def test_custom_button_committed_display(self):
        await self.page.set_content('''<button id="country" type="button" role="combobox" aria-controls="countries"
          onclick="countries.hidden=false">Choose a country</button>
          <ul role="listbox" id="countries" hidden><li role="option"
          onclick="country.textContent=this.textContent;countries.hidden=true">United States</li></ul>''')
        result = await select_custom_option(self.page.locator('#country'), 'United States')
        self.assertTrue(result.success, result)

    async def test_iframe_menu_uses_owner_document(self):
        await self.page.set_content('''<ul id="choices" role="listbox"><li role="option" onclick="window.wrong=true">Example Corp</li></ul><iframe></iframe>''')
        frame = self.page.frames[1]
        await frame.set_content('''<form><input id="company" role="combobox" aria-controls="choices"></form>
          <ul id="choices" role="listbox" hidden><li role="option" onclick="this.setAttribute('aria-selected','true')">Example Corp</li></ul>
          <script>company.addEventListener('keydown', event => {if(event.key==='ArrowDown') choices.hidden=false;});</script>''')
        result = await select_custom_option(frame.locator('#company'), 'Example Corp', fill=True)
        self.assertTrue(result.success, result)
        self.assertIsNone(await self.page.evaluate('window.wrong'))

    async def test_missing_option_finishes_within_shared_deadline(self):
        control = await self.fixture(label='Wrong Company')
        started = time.monotonic()
        result = await select_custom_option(control, 'Example Corp', fill=True, timeout_ms=300)
        self.assertFalse(result.success)
        self.assertLess(time.monotonic() - started, 0.8)

    async def test_missing_control_metadata_is_bounded(self):
        started = time.monotonic()
        self.assertFalse(await is_structured_choice(self.page.locator('#missing')))
        self.assertLess(time.monotonic() - started, 0.7)

    async def test_disabled_exact_option_is_not_clicked(self):
        await self.page.set_content('''<button type="button" role="combobox" aria-controls="countries">Choose</button>
          <ul id="countries" role="listbox"><li role="option" aria-disabled="true"
          onclick="window.clicked=true">United States</li></ul>''')
        result = await select_custom_option(self.page.locator('button'), 'United States', timeout_ms=300)
        self.assertFalse(result.success)
        self.assertIsNone(await self.page.evaluate('window.clicked'))

    async def test_explicit_alias_still_requires_exact_option_and_commit(self):
        await self.page.set_content('''<button id="country" type="button" role="combobox" aria-controls="countries"
          onclick="countries.hidden=false">Choose a country</button>
          <ul role="listbox" id="countries" hidden><li role="option"
          onclick="country.textContent=this.textContent;countries.hidden=true">United States of America</li></ul>''')
        result = await select_custom_option(self.page.locator('#country'), 'United States', aliases=('United States of America',))
        self.assertTrue(result.success, result)


if __name__ == '__main__':
    unittest.main()
