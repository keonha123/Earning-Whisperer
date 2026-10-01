"""Actual failed candidate inventories plus offline browser stage transitions.

The inventories are verbatim captured data. Browser markup is a reconstruction
of their observed controls, not claimed to be a complete saved provider page.
"""
from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
import html
import base64
import io
import wave
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlparse

from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.learning import _candidate_rejection_reason
from data_pipeline.collectors.streams.browser.navigation import (
    make_target_proof, observe_redirect, proof_is_fresh, validate_target_page,
)
from data_pipeline.collectors.streams.webcast_learning import (
    LearningSnapshot, WebcastCandidate, choose_heuristic_candidate,
)

FIXTURES = Path(__file__).parent / 'fixtures/oct01_candidate_failures'
MKC = 'https://ir.mccormick.com/events/event-details/q3-2026-mccormick-company-inc-earnings-conference-call'
PROVIDER = 'https://edge.media-server.com/mmc/p/ov9s8qjn/'
ACN = 'https://investor.accenture.com/news-and-events/events-calendar'
REDIRECT = 'https://webcast.accenture.com/redirect/goto?event=AccentureFY26Q4Earnings'
ON24 = 'https://event.on24.com/wcc/r/5478668/1543609E64F602BBE1280C27D75334EC'


def inventory(prefix):
    return json.loads(next(FIXTURES.glob(prefix + '*.json')).read_text())


def reconstructed_candidates(document):
    # Recorded inventories omit selectors. Stable fixture IDs fill only that
    # missing browser detail; scoring inputs use the actual captured strings.
    return [WebcastCandidate.from_dict({
        'candidate_id': row['candidate_id'], 'selectors': ['#' + row['candidate_id']],
        'text': row['text'], 'context_text': row['context'], 'metadata_text': row['metadata'],
        'href': row['destination'] or None,
        'href_path': urlparse(row['destination']).path if row['destination'] else None,
        'tag_name': 'a' if row['destination'] else 'button', 'rect': {},
    }) for row in document['candidates']]


class RecordedCandidateTests(unittest.TestCase):
    def test_actual_mkc_inventory_prefers_webcast_over_empty_event_self_link(self):
        document = inventory('MKC-20261001T120024')
        with patch.dict(os.environ, {'WEBCAST_LIFECYCLE':'live', 'WEBCAST_TARGET_DATE':'2026-10-01',
                                     'WEBCAST_LIVE_ENTRYPOINT_VERIFIED':'true'}, clear=True):
            agent = BrowserWebcastAgent('MKC', MKC)
        rows = reconstructed_candidates(document)
        self_link = next(row for row in rows if row.candidate_id == 'frame-0-element-1')
        self.assertEqual(_candidate_rejection_reason(agent, self_link, MKC), 'non_actionable_self_link')
        eligible = [row for row in rows if not _candidate_rejection_reason(agent, row, MKC)]
        selected = choose_heuristic_candidate(eligible, lifecycle='live', target_date=date(2026,10,1))
        self.assertEqual(selected.href, PROVIDER)
        self.assertEqual(selected.text, 'Webcast')

    def test_explicit_webcast_priority_cannot_override_other_event_identity(self):
        with patch.dict(os.environ, {'WEBCAST_LIFECYCLE':'live','WEBCAST_TARGET_DATE':'2026-10-01',
                                     'WEBCAST_LIVE_ENTRYPOINT_VERIFIED':'true'},clear=True):
            agent=BrowserWebcastAgent('MKC',MKC)
        recorded=reconstructed_candidates(inventory('MKC-20261001T120024'))
        webcast=next(row for row in recorded if row.text=='Webcast')
        for contradiction in ('Q3 earnings call July 1, 2026',
                              'October 1, 2026 Investor Day',
                              'October 1, 2026 Post Earnings Analyst Call',
                              'October 1, 2026 earnings call Ticker: OTHER'):
            with self.subTest(contradiction=contradiction):
                wrong=replace(webcast,context_text=contradiction,metadata_text='',href=PROVIDER+'wrong')
                self.assertTrue(_candidate_rejection_reason(agent,wrong,MKC).startswith('identity_mismatch'))
        play_self=replace(webcast,href=MKC,href_path=urlparse(MKC).path)
        self.assertNotEqual(_candidate_rejection_reason(agent,play_self,MKC),'non_actionable_self_link')

    def test_changed_candidate_drops_unrelated_clock_but_linked_child_keeps_it(self):
        with patch.dict(os.environ, {'WEBCAST_LIFECYCLE':'live','WEBCAST_TARGET_DATE':'2026-10-01'},clear=True):
            agent=BrowserWebcastAgent('MKC',MKC)
        evidence='October 1, 2026 Q3 earnings call at 8:00 AM EDT'
        agent._mark_live_target_identity_confirmed(evidence,source_url=MKC,target_url=MKC)
        original=agent.live_target_proof['observed_at']
        agent._mark_live_target_identity_confirmed('Webcast',source_url=MKC,target_url=PROVIDER)
        self.assertEqual(len(agent.schedule_clock_observations),1)
        self.assertEqual(agent.live_target_proof['source_observed_at'],original)
        # Re-selecting the same issuer link keeps its original issuer proof.
        agent._mark_live_target_identity_confirmed('Webcast',source_url=MKC,target_url=PROVIDER)
        self.assertEqual(agent.live_target_proof['source_observed_at'],original)
        agent._mark_live_target_identity_confirmed('Webcast',source_url=MKC,target_url=PROVIDER.replace('ov9s8qjn','another-call'))
        self.assertEqual(agent.schedule_clock_observations,[])
        agent.schedule_clock_observations=[{'sentinel':True}]
        agent._reset_live_target_identity_confirmation()
        self.assertEqual(agent.schedule_clock_observations,[])

    def test_original_source_age_survives_provider_promotion(self):
        with patch.dict(os.environ, {'WEBCAST_LIFECYCLE':'live','WEBCAST_TARGET_DATE':'2026-10-01'}, clear=True):
            agent = BrowserWebcastAgent('MKC', MKC)
        original = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        agent.live_target_proof = {'verified':True,'call_ticker':'MKC','target_date':'2026-10-01',
                                  'source_url':MKC,'target_url':MKC,'observed_at':original,
                                  'source_observed_at':original,'call_id':835,'schedule_revision':3}
        child = make_target_proof(agent, MKC, PROVIDER, 'Webcast on selected earnings page')
        self.assertEqual(child['source_url'], MKC)
        self.assertEqual(child['source_observed_at'], original)
        self.assertEqual(child['target_kind'], 'provider')
        self.assertEqual(child['route_lineage'][0]['parent_target_url'], MKC)
        self.assertEqual(child['route_lineage'][0]['target_url'], PROVIDER)
        self.assertEqual(child['schedule_revision'],3)
        child['source_observed_at']=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()
        self.assertFalse(proof_is_fresh(agent,child))


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires local Chromium')
class EventStageBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ, {
            'WEBCAST_LIFECYCLE':'live','WEBCAST_TARGET_DATE':'2026-10-01',
            'WEBCAST_LIVE_ENTRYPOINT_VERIFIED':'false','WEBCAST_LIVE_IDENTITY_PROOF':'',
            'WEBCAST_GENERALIZED_LEARNING_ENABLED':'false','WEBCAST_VISION_ENABLED':'false',
            'WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION':'true','WEBCAST_LIVE_DIAGNOSTICS':'false',
            'WEBCAST_ARTIFACTS_DIR':self.tmp.name,'WEBCAST_LIVE_RENDER_GRACE_SECONDS':'0',
            'WEBCAST_TARGET_IDENTITY_READY_FILE':'','WEBCAST_LIVE_NAVIGATION_STEPS':'4',
        },clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        if Path('/ms-playwright').is_dir():
            os.environ['PLAYWRIGHT_BROWSERS_PATH']='/ms-playwright'
        self.pw=await async_playwright().start();self.addAsyncCleanup(self.pw.stop)
        self.browser=await self.pw.chromium.launch(headless=True,args=['--no-sandbox'])
        self.addAsyncCleanup(self.browser.close)
        self.context=await self.browser.new_context()
        self.page=await self.context.new_page()
        self.documents={}
        self.requests=[]
        async def fulfill(route):
            self.requests.append((route.request.method,route.request.url))
            await route.fulfill(body=self.documents.get(route.request.url,'<body></body>'),content_type='text/html')
        await self.context.route('**/*',fulfill)

    def agent(self,ticker,url,*,verified=False):
        agent=BrowserWebcastAgent(ticker,url)
        agent._vision_selector.select=AsyncMock(return_value=None)
        agent._load_verified_recipes=Mock(return_value=[])
        agent._save_recipe=Mock(return_value=None)
        if verified:
            agent.live_target_proof=make_target_proof(agent,url,url,'Selected earnings event October 1, 2026')
            agent.live_target_identity_confirmed=True
        return agent

    async def test_recorded_mkc_controls_select_provider_and_preserve_parent_proof(self):
        rows=inventory('MKC-20261001T120024')['candidates']
        blank=next(r for r in rows if r['candidate_id']=='frame-0-element-1')
        webcast=next(r for r in rows if r['text']=='Webcast')
        self.documents[MKC]=f'''<div><h1>Q3 2026 McCormick &amp; Company, Inc. Earnings Conference Call</h1>
          <p>Oct 1, 2026 at 8:00 AM EDT</p><a href="{MKC}"><span style="display:inline-block;width:20px;height:20px"></span></a>
          <a href="{MKC}">EN</a><p>Supporting Materials</p><a href="{webcast['destination']}">{webcast['text']}</a>
          <a href="/release">Earnings Press Release</a></div>'''
        self.documents[PROVIDER]='<h1>Q3 2026 McCormick Earnings Conference Call</h1><form><input name="email"><input name="first_name"><button>Register</button></form>'
        agent=self.agent('MKC',MKC,verified=True)
        await self.page.goto(MKC)
        element,page=await agent.find_webcast_button_with_archive_fallback(self.page)
        self.assertIsNotNone(element)
        self.assertEqual(await element.get_attribute('href'),PROVIDER)
        await element.click()
        self.assertEqual(page.url,PROVIDER)
        self.assertTrue(await validate_target_page(agent,page))
        self.assertTrue(await agent.has_registration_form(page,wait_seconds=.1))
        self.assertEqual(agent.live_target_proof['source_url'],MKC)
        self.assertEqual(agent.live_target_proof['route_lineage'][-1]['target_url'],PROVIDER)
        self.assertFalse(any(method=='POST' for method,_ in self.requests))

    async def test_acn_accordion_link_inherits_only_its_explicit_heading(self):
        rows=inventory('ACN-20261001T120132')['candidates']
        heading=next(r['text'] for r in rows if r['candidate_id']=='frame-0-element-16')
        self.documents[ACN]=f'''<section><button aria-controls="current-panel" aria-expanded="false"
          onclick="document.getElementById('current-panel').hidden=false;this.setAttribute('aria-expanded','true')">{html.escape(heading)}</button>
          <div id="current-panel" hidden><p>Add to calendar</p><a href="{REDIRECT}">Webcast</a></div></section>
          <section><button aria-controls="other-panel">14 October, 2026 Accenture Investor Day</button>
          <div id="other-panel"><a href="https://events.q4inc.com/attendee/999999999">Webcast</a></div></section>'''
        agent=self.agent('ACN',ACN)
        await self.page.goto(ACN)
        element,_=await agent.find_webcast_button_with_archive_fallback(self.page)
        self.assertIsNotNone(element)
        self.assertEqual(await element.get_attribute('href'),REDIRECT)
        self.assertEqual(agent.live_target_proof['target_url'],REDIRECT)
        self.assertIn('01 October',agent.live_target_proof['evidence'])

    async def test_acn_known_js_redirect_reaches_registration_without_discovery_button(self):
        document=inventory('ACN-20261001T120115')
        context=document['candidates'][0]['context']
        self.documents[REDIRECT]='<script>location.replace('+json.dumps(ON24)+')</script>'
        self.documents[ON24]=f'<h1>{html.escape(context)}</h1><form><input name="email" type="email"><input name="first_name"><button>REGISTER</button></form>'
        agent=self.agent('ACN',ACN)
        agent.live_target_proof=make_target_proof(agent,ACN,REDIRECT,'Q4 earnings call October 1, 2026')
        agent.live_target_identity_confirmed=True
        self.context.on('request',lambda request:observe_redirect(agent,request))
        await self.page.goto(REDIRECT)
        await self.page.wait_for_url(ON24)
        self.assertTrue(await validate_target_page(agent,self.page))
        self.assertEqual(agent.live_target_proof['target_url'],ON24)
        self.assertEqual(agent.live_target_proof['source_url'],ACN)
        self.assertEqual(agent.live_target_proof['route_lineage'][-1]['kind'],'observed_redirect')
        self.assertTrue(await agent.has_registration_form(self.page,wait_seconds=.1))
        self.assertFalse(any(method=='POST' for method,_ in self.requests))

    async def test_full_flow_submits_only_intercepted_provider_form_and_starts_real_media(self):
        # All requests are intercepted inside --network none. This runs the
        # production flow and form handler; only external transport is replaced.
        context_text=inventory('ACN-20261001T120115')['candidates'][0]['context']
        audio=io.BytesIO()
        with wave.open(audio,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000)
            wav.writeframes(b'\0\0'*8000*20)
        audio_url='data:audio/wav;base64,'+base64.b64encode(audio.getvalue()).decode()
        registration=(f'<h1>{html.escape(context_text)}</h1><form method="post" action="{ON24}">'
            '<label>Email<input type="email" name="email" required></label>'
            '<label>First Name<input name="first_name" required></label>'
            '<button type="submit">REGISTER</button></form>')
        player=f'<h1>Accenture Fourth Quarter Fiscal 2026 Earnings</h1><audio controls autoplay src="{audio_url}"></audio>'
        agent=self.agent('ACN',ACN)
        agent.direct_target_url=REDIRECT
        agent.target_year=2026
        agent.target_quarter='Q4'
        agent.profile=replace(agent.profile,email='offline-fixture@example.invalid')
        agent._load_verified_human_workflows=Mock(return_value=[])
        agent._save_storage_state=AsyncMock()
        agent.live_target_proof=make_target_proof(agent,ACN,REDIRECT,'Q4 earnings call October 1, 2026')
        agent.live_target_identity_confirmed=True
        from data_pipeline.collectors.schedules.browser_observation import observe_browser_time
        observe_browser_time(agent,'Q4 2026 earnings call October 1, 2026 8:00 AM Eastern Daylight Time',evidence_url=ACN)
        original_source_at=agent.live_target_proof['observed_at']
        original_open=agent._open_direct_target_page
        async def open_intercepted(context,url):
            async def respond(route):
                method,request_url=route.request.method,route.request.url
                self.requests.append((method,request_url))
                if request_url==REDIRECT:
                    body='<script>location.replace('+json.dumps(ON24)+')</script>'
                elif request_url==ON24:
                    body=player if method=='POST' else registration
                else:
                    self.fail('Unexpected request '+request_url)
                await route.fulfill(body=body,content_type='text/html')
            await context.route('**/*',respond)
            return await original_open(context,url)
        agent._open_direct_target_page=open_intercepted
        agent.find_webcast_button_with_archive_fallback=AsyncMock(side_effect=AssertionError('Registration page must not rank event candidates'))
        result=await agent.run()
        self.assertTrue(result.success,result.error)
        self.assertTrue(result.playback_triggered)
        self.assertEqual(result.clicked_text,'registration form')
        self.assertEqual([(method,url) for method,url in self.requests if method=='POST'],[('POST',ON24)])
        self.assertEqual(agent.live_target_proof['target_url'],ON24)
        self.assertEqual(agent.live_target_proof['source_url'],ACN)
        self.assertEqual(agent.schedule_observation['evidence_url'],ON24)
        self.assertEqual(agent.schedule_observation['identity_proof']['source_observed_at'],original_source_at)
        readings=agent.schedule_observation['clock_observations']
        self.assertEqual({row['evidence_url'] for row in readings},{ACN,ON24})
        self.assertEqual(next(row for row in readings if row['evidence_url']==ACN)['identity_proof']['target_url'],REDIRECT)
        agent.find_webcast_button_with_archive_fallback.assert_not_awaited()

    async def test_unrelated_navigation_or_wrong_provider_event_cannot_inherit(self):
        agent=self.agent('MKC',MKC,verified=True)
        self.context.on('request',lambda request:observe_redirect(agent,request))
        self.documents[MKC]='<script>location.replace('+json.dumps(PROVIDER)+')</script>'
        await self.page.goto(MKC);await self.page.wait_for_url(PROVIDER)
        self.assertFalse(await validate_target_page(agent,self.page))
        agent.live_target_proof=make_target_proof(agent,MKC,PROVIDER,'dated selected link')
        wrong=PROVIDER.replace('ov9s8qjn','othercall')
        agent._live_redirect_edges.add((PROVIDER,wrong))
        await self.page.goto(wrong)
        self.assertFalse(await validate_target_page(agent,self.page))


if __name__=='__main__':
    unittest.main()
