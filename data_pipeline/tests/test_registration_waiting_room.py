import html
from pathlib import Path
from unittest import mock
from data_pipeline.tests.test_registration_outcome import RegistrationOutcomeBrowserTest
from data_pipeline.collectors.streams.browser.form_validation import registration_transition_state

class MUWaiting(RegistrationOutcomeBrowserTest):
    async def check(self,body,host='events.q4inc.com',remaining_form=False,barrier=None):
        await self.page.goto('https://'+host+'/attendee/563781180/guest')
        await self.page.set_content('<h1>Micron Fourth Quarter 2026 Financial Call</h1>'+body)
        self.agent._detect_access_barrier=mock.AsyncMock(return_value=barrier)
        if remaining_form:self.agent.has_registration_form=mock.AsyncMock(return_value=True)
        return await registration_transition_state(self.agent,self.page,self.page,'https://events.q4inc.com/attendee/563781180')
    def fixture_text(self,name):
        return html.escape((Path(__file__).parent/'fixtures'/name).read_text())
    async def test_actual_mu_broadcast_lobby(self):
        r=await self.check(self.fixture_text('mu_q4_broadcast_lobby.txt'))
        self.assertEqual(r,{'state':'passed','reason':'waiting_room'})
    async def test_actual_mu_registration_confirmation(self):
        r=await self.check(self.fixture_text('mu_q4_registration_waiting.txt'))
        self.assertEqual(r,{'state':'passed','reason':'waiting_room'})
    async def test_generic_thanks_stays_pending(self):
        r=await self.check('Thank you for registering!')
        self.assertEqual(r['state'],'pending')
    async def test_access_notice_without_confirmation_stays_pending(self):
        r=await self.check('You can access the webcast up to 15 minutes before the start time.')
        self.assertEqual(r['state'],'pending')
    async def test_existing_form_not_accepted(self):
        r=await self.check(self.fixture_text('mu_q4_broadcast_lobby.txt'),remaining_form=True)
        self.assertEqual(r['reason'],'registration_form_remaining')
    async def test_access_barrier_not_accepted(self):
        r=await self.check(self.fixture_text('mu_q4_broadcast_lobby.txt'),barrier='HUMAN_VERIFICATION_REQUIRED')
        self.assertEqual(r['state'],'failed')
    async def test_other_origin_not_accepted(self):
        r=await self.check(self.fixture_text('mu_q4_broadcast_lobby.txt'),host='unrelated.example')
        self.assertEqual(r['reason'],'unverified_destination')
    async def test_nonq4_confirmation_not_accepted(self):
        await self.page.goto('https://fixture.test/event/guest')
        await self.page.set_content(self.fixture_text('mu_q4_registration_waiting.txt'))
        r=await registration_transition_state(self.agent,self.page,self.page,'https://fixture.test/event/register')
        self.assertEqual(r['state'],'pending')
