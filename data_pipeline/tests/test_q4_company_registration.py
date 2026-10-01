"""Q4 lookup regressions: network-blocked DOM, no external submissions."""
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.registration import (
    _fill_generic_registration_form, _registration_approval_error,
    fill_registration_form,
)
from data_pipeline.collectors.streams.browser.rules import InvestorProfile


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires installed Chromium")
class Q4CompanyRegistrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        options = {"headless": True, "args": ["--disable-background-networking", "--no-sandbox"]}
        if os.getenv("WEBCAST_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["WEBCAST_CHROMIUM_EXECUTABLE"]
        self.browser = await self.pw.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.abort())
        self.env = mock.patch.dict(os.environ, {"WEBCAST_Q4_INDIVIDUAL_ATTENDEE_TICKERS": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def fixture(self, company, *, suggestion="", q4=True):
        lookup_id = "GuestRegistrationInstitutionLookupInput" if q4 else "company_name"
        heading = "Guest Registration" if q4 else "Webcast registration"
        await self.page.set_content(f'''<form id="GuestRegistration">
          <h1>{heading}</h1>
          <label for="GuestRegistrationFirstNameInput">First Name</label><input id="GuestRegistrationFirstNameInput">
          <label for="GuestRegistrationLastNameInput">Last Name</label><input id="GuestRegistrationLastNameInput">
          <label for="GuestRegistrationEmailInput">Email</label><input id="GuestRegistrationEmailInput" type="email">
          <label><input id="individual" type="checkbox">I am an individual attendee</label>
          <div class="event-registration-form_institution-section">
          <label for="{lookup_id}">Company Name</label><input id="{lookup_id}">
          <div class="nui-select__single-value"></div>
          <ul role="listbox">{('<li role="option">'+suggestion+'</li>') if suggestion else ''}</ul>
          </div>
          <label for="GuestRegistrationRoleFieldInput">Company Role</label><input id="GuestRegistrationRoleFieldInput">
          <button id="GuestRegistrationSubmitButton" type="submit">Register for this Event</button>
          </form><script>
          window.submissions = 0; window.companySelected = false; window.roleBeforeIndividual = '';
          GuestRegistration.addEventListener('submit', event => {{ event.preventDefault(); window.submissions++; }});
          document.querySelector('[role="option"]')?.addEventListener('click', event => {{
              window.companySelected = true;
              document.querySelector('.nui-select__single-value').textContent = event.target.textContent;
          }});
          individual.addEventListener('change', () => {{
              window.roleBeforeIndividual = GuestRegistrationRoleFieldInput.value;
              GuestRegistrationRoleFieldInput.readOnly = individual.checked;
          }});
          </script>''')
        profile = InvestorProfile(email="fixture@example.test", password="", first_name="Test", last_name="Investor", company=company,
            industry_affiliation="", country="", occupation="", job_title="Investor", city="", state="", attendee_type="", other_option="")
        return SimpleNamespace(ticker="GIS", profile=profile, _wait_for_dynamic_page=mock.AsyncMock(),
            registration_preview_only=True, _registration_failure_error=None)

    async def test_uncommitted_lookup_uses_personal_profile_after_role_filled(self):
        agent = await self.fixture("Private Investor")
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertTrue(await self.page.locator('#individual').is_checked())
        self.assertEqual(await self.page.evaluate('roleBeforeIndividual'), 'Investor')
        self.assertFalse(await self.page.evaluate('companySelected'))
        self.assertEqual(await self.page.evaluate('submissions'), 0)
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)

    async def test_unmatched_company_does_not_change_affiliation_or_submit(self):
        agent = await self.fixture("Example Corp", suggestion="Example Corporation Other")
        # Without a provider-offered personal path, do not invent a company.
        await self.page.locator('#individual').evaluate('element => element.closest("label").remove()')
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertEqual(agent.profile.company, 'Example Corp')
        self.assertFalse(await self.page.evaluate('companySelected'))
        self.assertEqual(await self.page.evaluate('submissions'), 0)
        self.assertIn('REGISTRATION_FIELD_UNRESOLVED', agent._registration_failure_error)

    async def test_exact_company_option_is_committed_without_individual_fallback(self):
        agent = await self.fixture("Example Corp", suggestion="Example Corp")
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertTrue(await self.page.evaluate('companySelected'))
        self.assertFalse(await self.page.locator('#individual').is_checked())
        self.assertEqual(await self.page.evaluate('submissions'), 0)
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)

    async def test_authorized_individual_fallback_does_not_mutate_company_profile(self):
        agent = await self.fixture("Example Corp")
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertTrue(await self.page.locator('#individual').is_checked())
        self.assertEqual(agent.profile.company, 'Example Corp')
        self.assertEqual(await self.page.evaluate('roleBeforeIndividual'), 'Investor')
        self.assertFalse(await self.page.evaluate('companySelected'))
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)
        self.assertEqual(await self.page.evaluate('submissions'), 0)

    async def test_personal_fallback_is_not_restricted_by_legacy_ticker_allowlist(self):
        agent = await self.fixture("Example Corp")
        with mock.patch.dict(os.environ, {"WEBCAST_Q4_INDIVIDUAL_ATTENDEE_TICKERS": "PAYX"}):
            self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertTrue(await self.page.locator('#individual').is_checked())
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)
        self.assertEqual(agent.profile.company, 'Example Corp')
        self.assertEqual(await self.page.evaluate('submissions'), 0)


    async def test_q4_div_custom_company_option_commits_supplied_company(self):
        agent = await self.fixture("Example Corp")
        await self.page.evaluate("""() => {
            const input = document.querySelector('#GuestRegistrationInstitutionLookupInput');
            input.addEventListener('input', () => setTimeout(() => {
                if (document.querySelector('.nui-select__option')) return;
                const option = document.createElement('div');
                option.className = 'nui-select__option';
                option.innerHTML = '<div class="institution-select__option institution-select__option--custom"><span class="institution-select__option-name">Enter &quot;Example Corp&quot; as Company Name</span></div>';
                option.addEventListener('click', () => {
                    companySelected = true;
                    document.querySelector('.nui-select__single-value').innerHTML = '<span class="institution-select__option-name">Example Corp</span>';
                    input.value = ''; option.remove();
                });
                input.parentElement.append(option);
            }, 850));
        }""")
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertTrue(await self.page.evaluate('companySelected'))
        self.assertFalse(await self.page.locator('#individual').is_checked())
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)
        self.assertEqual(await self.page.evaluate('submissions'), 0)

    async def test_option_click_without_committed_selected_value_is_not_success(self):
        agent = await self.fixture("Example Corp", suggestion="Example Corp")
        await self.page.locator('#individual').evaluate('element => element.closest("label").remove()')
        await self.page.locator('[role="option"]').evaluate("""element => {
            element.addEventListener('click', () => {
                document.querySelector('.nui-select__single-value').textContent = '';
            });
        }""")
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertIn('REGISTRATION_FIELD_UNRESOLVED', agent._registration_failure_error)
        self.assertEqual(agent.profile.company, 'Example Corp')
        self.assertEqual(await self.page.evaluate('submissions'), 0)

    async def test_body_portal_is_owned_by_focused_company_input(self):
        agent = await self.fixture("Example Corp")
        await self.page.evaluate("""() => {
            const input=document.querySelector('#GuestRegistrationInstitutionLookupInput');
            input.addEventListener('keydown', event => {
                if(event.key === 'Escape') document.querySelector('.nui-select__menu')?.remove();
                if(event.key !== 'ArrowDown' || document.querySelector('.nui-select__menu')) return;
                const menu=document.createElement('div'); menu.className='nui-select__menu';
                menu.innerHTML='<div class="nui-select__option"><span class="institution-select__option-name">Enter &quot;Example Corp&quot; as Company Name</span></div>';
                menu.firstChild.addEventListener('click', () => {
                    companySelected=true;
                    document.querySelector('.nui-select__single-value').innerHTML='<span class="institution-select__option-name">Example Corp</span>';
                    input.value='';menu.remove();
                });
                document.body.append(menu);
            });
        }""")
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertTrue(await self.page.evaluate('companySelected'))
        self.assertFalse(await self.page.locator('#individual').is_checked())
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)
        self.assertEqual(await self.page.evaluate('submissions'),0)

    async def test_existing_unrelated_menu_is_not_adopted(self):
        agent = await self.fixture("Example Corp")
        await self.page.locator('#individual').evaluate('element => element.closest("label").remove()')
        await self.page.evaluate("""() => {
            const menu=document.createElement('div');menu.className='nui-select__menu';
            menu.innerHTML='<div class="nui-select__option">Example Corp</div>';
            menu.firstChild.addEventListener('click', () => companySelected=true);
            document.body.append(menu);
        }""")
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertFalse(await self.page.evaluate('companySelected'))
        self.assertIn('REGISTRATION_FIELD_UNRESOLVED',agent._registration_failure_error)
        self.assertEqual(await self.page.evaluate('submissions'),0)

    async def test_failed_lookup_does_not_select_a_different_checkbox(self):
        agent = await self.fixture("Example Corp")
        await self.page.locator('#individual').evaluate('element => {element.closest("label").lastChild.textContent="Subscribe to optional promotional updates";}')
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertFalse(await self.page.locator('#individual').is_checked())
        self.assertIn('REGISTRATION_FIELD_UNRESOLVED', agent._registration_failure_error)
        self.assertEqual(await self.page.evaluate('submissions'), 0)

    async def test_compact_q4_preview_fills_without_submission(self):
        agent = await self.fixture("Example Corp", q4=False)
        await self.page.set_content('''<form id="EventRegistrationViewCustomRegistrationForm">
          <h1>One more thing</h1><label for="company_name">Company Name</label>
          <input id="company_name" required><button type="submit">Register for this Event</button>
          </form><script>window.submissions=0;
          EventRegistrationViewCustomRegistrationForm.addEventListener('submit', event => {event.preventDefault();window.submissions++;});</script>''')
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertEqual(await self.page.locator('#company_name').input_value(), 'Example Corp')
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)
        self.assertEqual(await self.page.evaluate('submissions'), 0)

    async def test_compact_webinar_preview_never_clicks_attend(self):
        agent = await self.fixture("Example Corp")
        await self.page.set_content('''<form><h1>Log In Now</h1>
          <input type="email" name="email"><button type="submit">Attend</button></form>
          <script>window.submissions=0;window.attendClicks=0;
          document.querySelector('button').onclick=()=>window.attendClicks++;
          document.querySelector('form').onsubmit=event=>{event.preventDefault();window.submissions++;};</script>''')
        class URLPage:
            url = 'https://app.webinar.net/local-preview-fixture'
            def __getattr__(self, name):
                return getattr(self._page, name)
        proxy = URLPage()
        proxy._page = self.page
        agent.allow_registration_submission = True
        agent.require_registration_approval = False
        agent._registration_approval_error = lambda url, fields, consent: _registration_approval_error(agent, url, fields, consent)
        with mock.patch('data_pipeline.collectors.streams.browser.diagnostics.capture_diagnostics', new=mock.AsyncMock()):
            self.assertFalse(await fill_registration_form(agent, proxy, TimeoutError))
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)
        self.assertEqual(await self.page.evaluate('attendClicks'), 0)
        self.assertEqual(await self.page.evaluate('submissions'), 0)

if __name__ == '__main__':
    unittest.main()
