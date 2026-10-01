"""Verified player/source joins and guarded replay decisions, all local."""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import os
import unittest

from data_pipeline.collectors.streams.browser.navigation import same_event_route, provider_event_id
from data_pipeline.collectors.streams.browser.source_observation import (
    SourceObservations, media_source_descriptor, playlist_summary, summarize_live_verification,
)
from data_pipeline.tests.test_capture_source_observation import playlist

MU = 'https://events.q4inc.com/attendee/563781180'
CCL = 'https://event.choruscall.com/mediaframe/webcast.html?webcastid=lE7HpeUW'
JBL = 'https://event.webcasts.com/starthere.jsp?ei=1775816'
HLS = 'https://cdn.example/earnings/live.m3u8?token=DO_NOT_LOG'
MP4 = 'https://cdn.example/earnings/recording.mp4?signature=DO_NOT_LOG'
NOW = 1800000000.0


def make_agent(url=MU):
    return SimpleNamespace(ticker='MU', target_date=date(2026,9,30),
        lifecycle='live', live_target_identity_confirmed=True,
        live_target_proof={'verified': True, 'call_ticker':'MU', 'target_date':'2026-09-30',
                          'target_url':url, 'observed_at':datetime.fromtimestamp(NOW,timezone.utc).isoformat()})


def sample(source=HLS, frame=MU+'/guest', **changes):
    return dict(dict(key='player0',frame_url=frame, paused=False,ended=False,
                     ready_state=4,current_time=91,duration_seconds=100,seekable_end=100,
                     muted=False,volume=1,recording_status=None,
                     **media_source_descriptor(source)), **changes)


class SourceBindingTest(unittest.TestCase):
    def setUp(self):
        self.observer=SourceObservations()
        self.agent=make_agent()

    def remember(self, sequence, stamp=NOW, frame=MU+'/guest', url=HLS, **kwargs):
        self.observer.remember(url=url,frame_url=frame,
            summary=playlist_summary(playlist(sequence,program_time=stamp-8,**kwargs)),observed_at=stamp)

    def assess(self, row=None, **kwargs):
        return self.observer.assessment(self.agent,MU+'/guest',[row or sample()],
                                       waiting=kwargs.pop('waiting',False),now=kwargs.pop('now',NOW),**kwargs)

    def test_actual_mu_registration_to_guest_keeps_same_event(self):
        self.assertEqual(provider_event_id(MU+'/guest'),'q4:563781180')
        self.assertTrue(same_event_route(MU,MU+'/guest'))
        self.assertTrue(self.assess()['target_identity_verified'])
        for url in (MU+'/guest/other',MU.replace('563781180','563781181')+'/guest',
                    MU+'/guest?token=changed',MU+'/guest#different',
                    MU.replace('q4inc.com','q4inc.com:444')+'/guest',
                    MU.replace('q4inc.com','q4inc.com.evil.test')+'/guest'):
            self.assertFalse(same_event_route(MU,url),url)

    def test_native_hls_same_player_recent_wall_time_and_motion_prove_delivery(self):
        self.remember(1,NOW-5);self.remember(2)
        first=self.assess();self.assertTrue(first['player_source_link_verified'])
        self.assertFalse(first['live_delivery_verified'])
        self.remember(3,NOW+5)
        result=self.assess(sample(current_time=96,seekable_end=105),now=NOW+5)
        self.assertTrue(result['live_delivery_verified'])
        self.assertEqual(result['source_phase'],'live_delivery_verified')
        self.assertFalse(result['live_success_verified']) # Speech/storage are separate.
        self.assertNotIn('DO_NOT_LOG',json.dumps(result))

    def test_ad_stream_cannot_bind_blob_or_different_selected_player(self):
        self.remember(1,NOW-5);self.remember(2)
        for source in ('blob:https://events.q4inc.com/some-id','https://cdn.example/other.m3u8'):
            r=self.assess(sample(source=source))
            self.assertFalse(r['player_source_link_verified'])
            self.assertFalse(r['live_delivery_verified'])

    def test_dvr_muted_or_nonadvancing_player_does_not_verify_live_delivery(self):
        for changes in ({'current_time':10},{'muted':True},{'volume':0},{'paused':True}):
            self.observer=SourceObservations();self.remember(1,NOW-5);self.remember(2)
            self.assess(sample(**changes));self.remember(3,NOW+5)
            self.assertFalse(self.assess(sample(**changes),now=NOW+5)['live_delivery_verified'],changes)

    def test_multiple_audible_players_never_verify_live_delivery(self):
        for other_frame in (MU+'/guest','https://ad.example/player'):
            with self.subTest(frame=other_frame):
                self.observer=SourceObservations()
                self.remember(1,NOW-5);self.remember(2)
                self.assess()
                self.remember(3,NOW+5)
                live=sample(current_time=96,seekable_end=105)
                other=sample(source='https://ad.example/promotion.mp4',frame=other_frame,key='other-player')
                r=self.observer.assessment(self.agent,MU+'/guest',[live,other],waiting=False,now=NOW+5)
                self.assertTrue(r['player_source_link_verified'])
                self.assertEqual(r['audible_player_count'],2)
                self.assertFalse(r['live_delivery_verified'])
                self.assertNotEqual(r['source_phase'],'live_delivery_verified')

    def test_muted_other_frame_does_not_mix_audible_live_player(self):
        self.remember(1,NOW-5);self.remember(2);self.assess()
        self.remember(3,NOW+5)
        live=sample(current_time=96,seekable_end=105)
        other=sample(source='https://ad.example/promotion.mp4',frame='https://ad.example/player',key='muted-ad',muted=True)
        r=self.observer.assessment(self.agent,MU+'/guest',[live,other],waiting=False,now=NOW+5)
        self.assertEqual(r['audible_player_count'],1)
        self.assertTrue(r['live_delivery_verified'])

    def test_old_wall_time_is_not_current_live(self):
        self.remember(1,NOW-500);self.remember(2,NOW-495)
        self.assertFalse(self.assess()['live_delivery_verified'])

    def test_jbl_fixed_waiting_music_then_live_is_not_rejected(self):
        # Reuse JBL's observed public event ID, with synthetic transport states.
        self.agent=make_agent(JBL)
        self.agent.ticker='JBL';self.agent.live_target_proof['call_ticker']='JBL'
        waiting=sample(source=MP4,frame=JBL,duration_seconds=3600,current_time=3599,ended=True,recording_status='ended')
        r=self.observer.assessment(self.agent,JBL,[waiting],waiting=True,now=NOW)
        self.assertEqual(r['source_phase'],'waiting_for_start')
        self.assertFalse(r['replay_verified']);self.assertFalse(r['ended_recording_observed'])
        self.remember(1,NOW-5,frame=JBL);self.remember(2,frame=JBL)
        self.observer.assessment(self.agent,JBL,[sample(frame=JBL)],waiting=False,now=NOW)
        self.remember(3,NOW+5,frame=JBL)
        current=sample(frame=JBL,current_time=96,seekable_end=105)
        self.assertTrue(self.observer.assessment(self.agent,JBL,[current],waiting=False,now=NOW+5)['live_delivery_verified'])

    def test_ccl_finished_mp4_without_event_end_is_observation_only(self):
        self.agent=make_agent(CCL)
        media=sample(source=MP4,frame=CCL,paused=True,ended=True,current_time=3583.535601,
                     duration_seconds=3583.535601,seekable_end=3583.535601)
        r=self.observer.assessment(self.agent,CCL,[media],waiting=False,now=NOW)
        self.assertTrue(r['ended_recording_observed'])
        self.assertEqual(r['source_phase'],'replay_candidate')
        self.assertFalse(r['replay_verified'])
        self.assertEqual(r['capture_action'],'continue_observing')

    def test_ccl_bound_long_mp4_with_explicit_event_end_is_verified_replay(self):
        self.agent=make_agent(CCL)
        media=sample(source=MP4,frame=CCL,paused=True,ended=True,current_time=3583.535601,
                     duration_seconds=3583.535601,seekable_end=3583.535601,recording_status='ended')
        r=self.observer.assessment(self.agent,CCL,[media],waiting=False,now=NOW)
        self.assertTrue(r['replay_verified'])
        self.assertEqual(r['capture_action'],'reject_replay_route')
        self.assertEqual(r['source_page_url'],CCL)

    def test_hls_vod_requires_explicit_event_state_and_exact_binding(self):
        self.remember(1,end=True,duration=600)
        self.assertFalse(self.assess()['replay_verified'])
        r=self.assess(sample(recording_status='replay',duration_seconds=1200))
        self.assertTrue(r['replay_verified'])
        self.assertFalse(self.assess(sample(source='blob:unbound',recording_status='replay'))['replay_verified'])

    def test_finished_recording_beside_active_blob_does_not_reject_route(self):
        ended=sample(source=MP4,paused=True,ended=True,duration_seconds=3600,recording_status='ended')
        playing=sample(source='blob:https://events.q4inc.com/live',key='live-player')
        r=self.observer.assessment(self.agent,MU+'/guest',[ended,playing],waiting=False,now=NOW)
        self.assertFalse(r['replay_verified'])
        self.assertEqual(r['capture_action'],'continue_observing')

    def test_extensionless_mp4_response_headers_bind_without_reading_media(self):
        source='https://cdn.example/stream?id=fixture'
        self.observer.remember_file(url=source,frame_url=MU+'/guest',content_type='video/mp4',observed_at=NOW)
        r=self.assess(sample(source=source,duration_seconds=3583,recording_status='ended',ended=True))
        self.assertTrue(r['player_source_link_verified'])
        self.assertTrue(r['replay_verified'])
        self.assertFalse(self.assess(sample(source=source,duration_seconds=3583,recording_status='ended'),now=NOW+121)['replay_verified'])

    def test_unknown_identity_is_observed_without_capture_rejection(self):
        self.agent.live_target_proof['target_date']='2020-01-01'
        r=self.assess(sample(source=MP4,duration_seconds=3600,recording_status='ended'))
        self.assertFalse(r['replay_verified'])
        self.assertEqual(r['capture_action'],'continue_observing')

    def test_source_timestamp_cannot_be_refreshed_by_reissued_proof(self):
        self.agent.live_target_proof['source_observed_at']='2020-01-01T00:00:00Z'
        self.assertFalse(self.assess()['target_identity_verified'])

    def test_status_true_requires_current_session_transport_audio_speech_and_db(self):
        stamp=datetime.fromtimestamp(NOW,timezone.utc).isoformat()
        call={'id':335,'ticker':'MU','schedule_revision':9,'capture_session_id':'MU-run','status':'running'}
        envelope={**call,'call_id':335,'timestamp_utc':stamp}
        progress={
          'capture_source':dict(envelope,source_phase='live_delivery_verified',target_identity_verified=True,
                                live_delivery_verified=True,player_source_link_verified=True),
          'audio':dict(envelope,audio_condition='signal_present'),
          'stt':dict(envelope,speech_seen=True,speech_evidence_reason='speech_continuity',last_speech_age_seconds=1),
          'archive':dict(envelope,event='segment_db_committed',status='saved',db_committed_sequence=4)}
        result=summarize_live_verification(call,progress,{'stored_rows':4},now=NOW)
        self.assertTrue(result['live_success_verified'])
        self.assertEqual(result['minimum_live_success'],'verified_live_audio_transcribed')
        self.assertEqual(result['coverage_verification'],'not_assessed')
        self.assertEqual(result['transcript_accuracy_verification'],'not_assessed')
        for stage in progress:
            mutated={**progress,stage:{**progress[stage],'capture_session_id':'other'}}
            self.assertFalse(summarize_live_verification(call,mutated,{'stored_rows':4},now=NOW)['live_success_verified'],stage)
        for change in ({'last_speech_age_seconds':90},{'speech_evidence_reason':'one_text'}, {'speech_seen':False}):
            mutated={**progress,'stt':{**progress['stt'],**change}}
            self.assertFalse(summarize_live_verification(call,mutated,{'stored_rows':4},now=NOW)['live_success_verified'])
        self.assertFalse(summarize_live_verification(call,progress,{'stored_rows':0},now=NOW)['live_success_verified'])
        self.assertFalse(summarize_live_verification(call,progress,{'stored_rows':4},now=NOW+46)['live_success_verified'])


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE')=='1','requires installed Chromium')
class PlayerSourceBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_selected_file_is_hashed_and_player_local_status_is_scoped(self):
        from playwright.async_api import async_playwright
        from data_pipeline.collectors.streams.browser.lifetime import observe_player
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True,args=['--no-sandbox'])
            try:
                page=await browser.new_page()
                await page.route('**/*',lambda route:route.fulfill(status=200,body='<html></html>',content_type='text/html'))
                await page.goto(MU+'/guest')
                await page.set_content('<nav><p>Webcast has ended.</p></nav><div class="player"><p role="status">Webcast has ended.</p><video></video></div>')
                await page.locator('video').evaluate('(el,src)=>{Object.defineProperty(el,"currentSrc",{value:src}); Object.defineProperty(el,"ended",{value:true}); Object.defineProperty(el,"duration",{value:3583.535601});}',MP4)
                row=(await observe_player(page))[0]
                self.assertEqual(row['media_source_kind'],'file')
                self.assertEqual(row['media_source_fingerprint'],media_source_descriptor(MP4)['media_source_fingerprint'])
                self.assertEqual(row['recording_status'],'ended')
                self.assertNotIn('DO_NOT_LOG',json.dumps(row))
                await page.locator('.player [role=status]').evaluate('(el)=>el.remove()')
                row=(await observe_player(page))[0]
                self.assertIsNone(row['recording_status'])
            finally:
                await browser.close()
