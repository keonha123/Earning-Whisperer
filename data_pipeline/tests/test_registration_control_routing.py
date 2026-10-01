"""Local Chromium regressions for field typing versus committed choices.

The original generic registration function fills and submits actual DOM forms.
Every request is aborted; the post-submit observer is separately tested by the
registration outcome suite and is replaced here after one local submission.
"""
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser import registration
from data_pipeline.collectors.streams.browser.rules import InvestorProfile


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class RegistrationControlRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        options = {'headless': True, 'args': ['--no-sandbox', '--disable-background-networking']}
        if os.getenv('WEBCAST_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['WEBCAST_CHROMIUM_EXECUTABLE']
        self.browser = await self.pw.chromium.launch(**options)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()
        await self.page.route('**/*', lambda route: route.abort())
        self.events = []
        self.telemetry = mock.patch.object(registration, 'emit_live_event',
                                           side_effect=lambda **event: self.events.append(event))
        self.telemetry.start()
        self.addCleanup(self.telemetry.stop)
        self.outcome = mock.patch.object(registration, '_wait_registration_outcome',
                                         new=mock.AsyncMock(return_value=True))
        self.wait_outcome = self.outcome.start()
        self.addCleanup(self.outcome.stop)

    async def fixture(self, role_html, *, extra='', script='', company='', country='', job_title='Investor'):
        await self.page.set_content('''<form id="GuestRegistration"><h1>Webcast Registration</h1>
          <label for="first">First Name</label><input id="first" required>
          <label for="last">Last Name</label><input id="last" required>
          <label for="email">Email</label><input id="email" type="email" required>
          ''' + extra + '''
          <div><label for="GuestRegistrationRoleFieldInput">Company Role</label>'''
          + role_html + '''</div><button type="submit">Register</button></form>
          <script>window.submissions=0;window.choiceClicks=0;
          GuestRegistration.onsubmit=e=>{e.preventDefault();window.submissions++};
          ''' + script + '</script>')
        profile = InvestorProfile(email='fixture@example.test', password='',
            first_name='Fixture', last_name='Investor', company=company,
            industry_affiliation='', country=country, occupation='', job_title=job_title,
            city='', state='', attendee_type='', other_option='')
        return SimpleNamespace(ticker='EWTEST', profile=profile,
            _wait_for_dynamic_page=mock.AsyncMock(), registration_preview_only=False,
            _registration_failure_error=None, _registration_approval_error=mock.Mock(return_value=None))

    async def fill(self, agent):
        return await registration._fill_generic_registration_form(agent, self.page, TimeoutError)

    def validation(self):
        return next(event['details'] for event in reversed(self.events)
                    if event.get('event') == 'registration_validation')

    async def test_filled_plain_role_input_submits_without_dropdown_pass(self):
        agent = await self.fixture('<input id="GuestRegistrationRoleFieldInput" required>')
        self.assertTrue(await self.fill(agent))
        self.assertEqual(await self.page.locator('#GuestRegistrationRoleFieldInput').input_value(), 'Investor')
        self.assertEqual(await self.page.evaluate('submissions'), 1)
        self.assertEqual(self.validation()['invalid_field_count'], 0)
        self.assertEqual(self.validation()['unresolved_choice_count'], 0)
        self.assertFalse(any(event.get('event') == 'registration_field_choice' for event in self.events))
        self.wait_outcome.assert_awaited_once()

    async def test_plain_role_textarea_is_also_not_a_choice(self):
        agent = await self.fixture('<textarea id="GuestRegistrationRoleFieldInput" required></textarea>')
        self.assertTrue(await self.fill(agent))
        self.assertEqual(await self.page.evaluate('submissions'), 1)
        self.assertEqual(self.validation()['unresolved_choices'], [])

    async def test_native_role_select_keeps_native_selection(self):
        agent = await self.fixture('''<select id="GuestRegistrationRoleFieldInput" required>
          <option value="">Choose role</option><option value="investor">Investor</option></select>''')
        self.assertTrue(await self.fill(agent))
        self.assertEqual(await self.page.locator('#GuestRegistrationRoleFieldInput').input_value(), 'investor')
        self.assertEqual(await self.page.evaluate('submissions'), 1)
        self.assertEqual(self.validation()['unresolved_choices'], [])

    async def test_real_combobox_requires_and_commits_owned_option(self):
        agent = await self.fixture('''<input id="GuestRegistrationRoleFieldInput" role="combobox" aria-controls="choices">
          <input type="hidden" id="roleId">''', script='''
          GuestRegistrationRoleFieldInput.onkeydown=event=>{
            if(event.key!=='ArrowDown'||document.querySelector('#choices'))return;
            const menu=document.createElement('ul');menu.id='choices';menu.setAttribute('role','listbox');
            menu.innerHTML='<li role="option">Investor</li>';
            menu.firstChild.onclick=()=>{window.choiceClicks++;roleId.value='investor-7';GuestRegistrationRoleFieldInput.value='';menu.remove();};
            document.body.append(menu);
          };''')
        self.assertTrue(await self.fill(agent))
        self.assertEqual(await self.page.locator('#roleId').input_value(), 'investor-7')
        self.assertEqual(await self.page.evaluate('choiceClicks'), 1)
        self.assertEqual(await self.page.evaluate('submissions'), 1)
        self.assertEqual(self.validation()['unresolved_choices'], [])

    async def test_real_combobox_without_menu_blocks_with_choice_not_native_error(self):
        agent = await self.fixture('<input id="GuestRegistrationRoleFieldInput" role="combobox" aria-controls="choices">')
        self.assertFalse(await self.fill(agent))
        self.assertEqual(await self.page.evaluate('submissions'), 0)
        self.assertEqual(self.validation()['invalid_field_count'], 0)
        self.assertEqual(self.validation()['unresolved_choice_count'], 1)
        self.assertIn('invalid_fields=0 unresolved_choices=1', agent._registration_failure_error)
        self.assertEqual(self.validation()['unresolved_choices'][0]['field'], 'company_role')
        self.wait_outcome.assert_not_awaited()

    async def test_missing_required_text_still_blocks_as_native_validation(self):
        agent = await self.fixture('<input id="GuestRegistrationRoleFieldInput" required>', job_title='')
        self.assertFalse(await self.fill(agent))
        self.assertEqual(await self.page.evaluate('submissions'), 0)
        self.assertEqual(self.validation()['invalid_field_count'], 1)
        self.assertEqual(self.validation()['unresolved_choice_count'], 0)
        self.assertIn('invalid_fields=1 unresolved_choices=0', agent._registration_failure_error)
        self.wait_outcome.assert_not_awaited()

    async def test_mixed_company_object_plain_role_and_country_select(self):
        agent = await self.fixture('<input id="GuestRegistrationRoleFieldInput" required>',
            company='Example Corp', country='United States', extra='''
            <div><label for="company">Company Name</label>
              <input id="company" role="combobox" aria-controls="companies"><input id="institutionId" type="hidden"></div>
            <label for="country">Country</label><select id="country" required>
              <option value="">Choose country</option><option value="US">United States</option></select>''',
            script='''window.refills=0;
            company.oninput=()=>{if(institutionId.value){window.refills++;institutionId.value='';}};
            company.onkeydown=event=>{
              if(event.key!=='ArrowDown'||document.querySelector('#companies'))return;
              const menu=document.createElement('ul');menu.id='companies';menu.setAttribute('role','listbox');
              menu.innerHTML='<li role="option">Example Corp</li>';
              menu.firstChild.onclick=()=>{window.choiceClicks++;institutionId.value='company-9';company.value='';menu.remove();};
              document.body.append(menu);
            };''')
        self.assertTrue(await self.fill(agent))
        self.assertEqual(await self.page.locator('#institutionId').input_value(), 'company-9')
        self.assertEqual(await self.page.evaluate('refills'), 0)
        self.assertEqual(await self.page.evaluate('choiceClicks'), 1)
        self.assertEqual(await self.page.locator('#GuestRegistrationRoleFieldInput').input_value(), 'Investor')
        self.assertEqual(await self.page.locator('#country').input_value(), 'US')
        self.assertEqual(await self.page.evaluate('submissions'), 1)
        self.assertEqual(self.validation()['unresolved_choices'], [])


if __name__ == '__main__':
    unittest.main()
