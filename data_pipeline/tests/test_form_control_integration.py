"""Registration integration regression fixtures, without external navigation."""
import unittest

from data_pipeline.tests import test_q4_company_registration as q4
from data_pipeline.collectors.streams.browser.registration import _fill_generic_registration_form


@unittest.skipUnless(q4.os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class FormControlIntegrationTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = q4.Q4CompanyRegistrationTest.asyncSetUp
    fixture = q4.Q4CompanyRegistrationTest.fixture

    async def test_q4_company_handling_does_not_overwrite_sibling_profile_fields(self):
        agent = await self.fixture('Example Corp', suggestion='Example Corp')
        await _fill_generic_registration_form(agent, self.page, TimeoutError)
        self.assertEqual(await self.page.locator('#GuestRegistrationFirstNameInput').input_value(), 'Test')
        self.assertEqual(await self.page.locator('#GuestRegistrationLastNameInput').input_value(), 'Investor')
        self.assertEqual(await self.page.locator('#GuestRegistrationEmailInput').input_value(), 'fixture@example.test')

    async def test_only_unresolved_structured_field_is_not_registration_success(self):
        agent = await self.fixture('Example Corp', q4=False)
        await self.page.set_content('''<form id="register"><label for="company">Company Name</label>
          <input id="company" role="combobox" aria-controls="choices">
          <button type="submit">Register</button></form>
          <ul id="choices" role="listbox" hidden><li role="option">Wrong Company</li></ul>
          <script>window.opens=0;company.onkeydown=event=>{if(event.key==='ArrowDown'){choices.hidden=false;window.opens++;}};</script>''')
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertLessEqual(await self.page.evaluate('opens'), 1)

    async def test_committed_company_object_is_not_refilled_by_alias_pass(self):
        agent = await self.fixture('Example Corp', q4=False)
        await self.page.set_content('''<form id="register"><div><label for="company">Company Name</label>
          <input id="company" role="combobox" aria-controls="choices"><input id="institutionId" type="hidden"></div>
          <button type="submit">Register</button></form>
          <script>window.opens=0;window.refills=0;
          company.oninput=()=>{if(institutionId.value){window.refills++;institutionId.value='';}};
          company.onkeydown=event=>{
            if(event.key!=='ArrowDown'||document.querySelector('#choices')) return;
            window.opens++;
            const menu=document.createElement('ul');menu.id='choices';menu.setAttribute('role','listbox');
            menu.innerHTML='<li role="option">Example Corp</li>';
            menu.firstChild.onclick=()=>{institutionId.value='committed-123';company.value='';menu.remove();};
            document.body.append(menu);
          };</script>''')
        self.assertFalse(await _fill_generic_registration_form(agent, self.page, TimeoutError))
        self.assertEqual(await self.page.locator('#institutionId').input_value(), 'committed-123')
        self.assertEqual(await self.page.evaluate('refills'), 0)
        self.assertEqual(await self.page.evaluate('opens'), 1)
        self.assertIn('REGISTRATION_PREVIEW', agent._registration_failure_error)
