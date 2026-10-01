"""A verified, dated waiting room is pending, not a broken player."""
from datetime import date
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.navigation import make_target_proof,same_event_route

ROOM='''<div role="dialog"><p>Welcome to the webinar</p>
<h2>Lennar Corporation - 3rd Qtr 2026 Financial Results</h2>
<p>The webinar has not quite started.</p>
<p>It is scheduled for Thursday, September 17, 2026 11:00 AM.</p>
<p>(GMT-04:00) Eastern Time - New York</p></div>'''

@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE')=='1','requires Chromium')
class WaitingRoomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw=await async_playwright().start();self.addAsyncCleanup(self.pw.stop)
        self.browser=await self.pw.chromium.launch(headless=True,args=['--no-sandbox'])
        self.addAsyncCleanup(self.browser.close)
        self.context=await self.browser.new_context()
        await self.context.route('**/*',lambda route:route.fulfill(body='<body></body>',content_type='text/html'))
        self.page=await self.context.new_page()
        self.url='https://app.webinar.net/currentEvent'
        await self.page.goto(self.url+'/live')
        await self.page.set_content(ROOM)
        with patch.dict(os.environ,{'WEBCAST_LIFECYCLE':'live','WEBCAST_TARGET_DATE':'2026-09-17',
             'WEBCAST_LIVE_ENTRYPOINT_VERIFIED':'false','WEBCAST_LIVE_DIAGNOSTICS':'false'},clear=True):
            self.agent=BrowserWebcastAgent('LEN',self.url)
        self.agent.live_target_proof=make_target_proof(self.agent,'https://investors.lennar.com/earnings',self.url,'dated official event')
        self.agent._live_redirect_edges.add((self.url,self.url+'/live'))

    async def test_actual_len_waiting_room_after_registration_is_pending(self):
        self.assertIsNotNone(await self.agent._detect_not_live_event(self.page))

    async def test_unproven_route_and_issuer_index_cannot_delay_event(self):
        self.agent.live_target_proof=None
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))
        await self.page.goto('https://investors.lennar.com/events')
        await self.page.set_content(ROOM)
        self.agent.live_target_proof=make_target_proof(self.agent,self.page.url,self.page.url,'dated event list')
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_known_provider_event_id_survives_live_route_but_not_another_event(self):
        self.agent._live_redirect_edges.clear()
        self.assertIsNotNone(await self.agent._detect_not_live_event(self.page))
        self.assertTrue(same_event_route(self.url,self.url+'/live'))
        await self.page.goto('https://app.webinar.net/otherEvent/live')
        await self.page.set_content(ROOM)
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_different_date_and_mixed_event_container_are_not_waiting_proof(self):
        await self.page.set_content(ROOM.replace('September 17','September 18'))
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))
        await self.page.set_content('<div>LEN financial results September 17, 2026. Another webinar has not quite started; scheduled September 18, 2026.</div>')
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_hidden_waiting_room_is_ignored(self):
        await self.page.set_content('<div style="display:none">'+ROOM+'</div><p>Broadcast is live.</p>')
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_wait_skips_controls_and_preserves_registration_then_allows_started_player(self):
        a=self.agent;a._registration_target_page=self.page;a.post_registration_playback_wait_seconds=1
        a._wait_for_dynamic_page=AsyncMock();a.accept_cookie_banners=AsyncMock()
        a._submit_metameetings_privacy_consent=AsyncMock(return_value=False)
        a._detect_access_barrier=AsyncMock(return_value=None)
        a._save_storage_state=AsyncMock()
        a.trigger_media_playback=AsyncMock(return_value=True)
        a.detect_active_playback=AsyncMock(return_value='audio clock progressing')
        a._apply_human_workflow=AsyncMock(return_value=(self.page,False))
        ready,page=await a._activate_registered_playback(self.context,self.page)
        self.assertFalse(ready);self.assertIs(page,self.page)
        a.trigger_media_playback.assert_not_awaited();a.detect_active_playback.assert_not_awaited()
        a._save_storage_state.assert_awaited_once_with(self.context)
        await self.page.set_content('<h1>Lennar financial results</h1><button>Pause</button>')
        ready,_=await a._activate_registered_playback(self.context,self.page)
        self.assertTrue(ready);self.assertIsNone(a._not_live_reason)

    async def test_wait_does_not_reenter_form_or_human_handoff(self):
        a=self.agent
        async def waiting(*args):
            a._not_live_reason='webinar has not quite started'
            return False,self.page
        a._activate_registered_playback=waiting
        a.has_registration_form=AsyncMock()
        a._human_handoff=AsyncMock()
        ready,_=await a._activate_playback_with_human(self.context,self.page,timeout_error_type=TimeoutError,reason='test')
        self.assertFalse(ready)
        a.has_registration_form.assert_not_awaited();a._human_handoff.assert_not_awaited()
