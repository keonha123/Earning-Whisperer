"""Passive transport diagnostics: no external sites, no success/end decisions."""
from datetime import date, datetime, timezone
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.collectors.streams.browser.source_observation import (
    SourceObservations, attach_source_observer, playlist_summary,
    record_source_observation, summarize_live_verification,
)

EVENT = 'https://events.q4inc.com/attendee/186598450'


def playlist(sequence=1, *, end=False, duration=4, segments=2, program_time=None):
    text = '#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:' + str(sequence) + '\n'
    if program_time is not None:
        text += '#EXT-X-PROGRAM-DATE-TIME:' + datetime.fromtimestamp(program_time, timezone.utc).isoformat() + '\n'
    for i in range(segments):
        text += f'#EXTINF:{duration},\nsegment-{sequence+i}.ts?secret=DO_NOT_LOG\n'
    return text + ('#EXT-X-ENDLIST\n' if end else '')


def agent(now=None):
    return SimpleNamespace(lifecycle='live', live_target_identity_confirmed=True,
        target_date=date(2026, 9, 24), ticker='COST',
        live_target_proof={'verified': True, 'target_url': EVENT,
                           'call_ticker': 'COST', 'target_date': '2026-09-24',
                           'observed_at':datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat()})


def player(**kwargs):
    return dict(frame_url=EVENT, paused=False, ended=False, ready_state=4,
                current_time=30, duration_seconds=3600, seekable_end=3600, **kwargs)


class SourceEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.observer = SourceObservations()
        self.now = 1800000000.0
        self.agent = agent(self.now)

    def remember(self, text, *, stamp=None, frame=EVENT, url='https://cdn.test/live.m3u8?token=SECRET'):
        self.observer.remember(url=url, frame_url=frame, summary=playlist_summary(text),
                               observed_at=self.now if stamp is None else stamp)

    def assess(self, **kwargs):
        return self.observer.assessment(self.agent, EVENT, [player()], waiting=False,
                                       now=self.now, **kwargs)

    def test_master_malformed_and_oversized_manifests_are_not_evidence(self):
        for body in ('<html>Login</html>', '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nvariant.m3u8',
                     '#EXTM3U\n#EXTINF:nan,\nx.ts', '#EXTM3U\n#EXTINF:inf,\nx.ts',
                     '#EXTM3U\n#EXTINF:4,', '#EXTM3U\n' + 'a' * 262144):
            self.assertIsNone(playlist_summary(body))

    def test_summary_retains_timing_and_discards_raw_urls(self):
        value = playlist_summary(playlist(program_time=self.now-8))
        self.assertEqual(value['program_end_timestamp'], self.now)
        self.assertEqual(value['segment_count'], 2)
        self.assertNotIn('DO_NOT_LOG', json.dumps(value))

    def test_one_manifest_and_static_reloads_do_not_prove_live(self):
        self.remember(playlist())
        self.remember(playlist())
        self.assertEqual(self.assess()['source_phase'], 'unconfirmed')

    def test_dynamic_transport_never_establishes_speech_success(self):
        self.remember(playlist(1), stamp=self.now-5)
        self.remember(playlist(2))
        result = self.assess()
        self.assertEqual(result['source_phase'], 'live_transport_observed')
        self.assertFalse(result['live_success_verified'])
        self.assertFalse(result['speech_content_verified'])
        self.assertFalse(result['player_source_link_verified'])

    def test_growing_event_playlist_can_advance_without_sequence_change(self):
        self.remember(playlist(1, segments=2), stamp=self.now-5)
        self.remember(playlist(1, segments=3))
        self.assertEqual(self.assess()['source_phase'], 'live_transport_observed')

    def test_fixed_waiting_music_does_not_terminate_call(self):
        self.remember(playlist(end=True, duration=10, segments=2))
        result = self.assess()
        self.assertEqual(result['source_phase'], 'unconfirmed')
        self.assertEqual(result['capture_action'], 'continue_observing')

    def test_long_finalized_media_is_replay_candidate_not_event_end(self):
        self.remember(playlist(end=True, duration=4, segments=970))
        result = self.assess()
        self.assertEqual(result['source_phase'], 'replay_candidate')
        self.assertEqual(result['capture_action'], 'continue_observing')
        self.assertFalse(result['live_success_verified'])

    def test_waiting_state_takes_precedence_over_replay_candidate(self):
        self.remember(playlist(end=True, duration=600))
        result = self.observer.assessment(self.agent, EVENT, [player()], waiting=True, now=self.now)
        self.assertEqual(result['source_phase'], 'waiting_for_start')

    def test_other_event_iframe_is_excluded(self):
        self.remember(playlist(end=True, duration=600), frame=EVENT.replace('186598450', '999'))
        self.assertEqual(self.assess()['playlist_evidence'], [])

    def test_page_navigated_elsewhere_cannot_reuse_target_identity(self):
        result = self.observer.assessment(self.agent, EVENT.replace('186598450', '999'),
                                         [player()], waiting=False, now=self.now)
        self.assertFalse(result['target_identity_verified'])

    def test_ticker_and_date_mismatch_are_not_same_event(self):
        for field, value in (('call_ticker', 'GIS'), ('target_date', '2026-06-01')):
            with self.subTest(field=field):
                self.agent = agent(self.now)
                self.agent.live_target_proof[field] = value
                self.assertEqual(self.assess()['source_phase'], 'identity_unverified')

    def test_stale_target_proof_is_not_current_identity(self):
        self.agent.live_target_proof['observed_at'] = '2025-01-01T00:00:00Z'
        self.assertFalse(self.assess()['target_identity_verified'])

    def test_stale_and_future_network_evidence_ignored(self):
        for stamp in (self.now-121, self.now+1):
            with self.subTest(stamp=stamp):
                self.remember(playlist(end=True, duration=600), stamp=stamp)
                self.assertEqual(self.assess()['source_phase'], 'unconfirmed')

    def test_advertisement_and_dvr_player_cannot_be_combined_into_live_edge_proof(self):
        self.remember(playlist(1, program_time=self.now-8), stamp=self.now-5)
        self.remember(playlist(2, program_time=self.now-8))
        p = player(); p['current_time'] = 3599
        result = self.observer.assessment(self.agent, EVENT, [p], waiting=False, now=self.now)
        self.assertTrue(result['transport_recent_wall_clock'])
        self.assertTrue(result['any_player_near_edge'])
        self.assertFalse(result['player_source_link_verified'])
        self.assertFalse(result['live_success_verified'])
        self.assertNotIn('live_edge_observed', result)

    def test_phase_is_logged_with_session_envelope_without_secret_url(self):
        self.remember(playlist(end=True, duration=600))
        self.agent._source_observations = self.observer
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {
            'WEBCAST_PROGRESS_DIR': directory, 'STT_CAPTURE_SESSION_ID': 'COST-session',
            'WEBCAST_CALL_DB_ID': '120', 'WEBCAST_SCHEDULE_REVISION': '5',
            'WEBCAST_ATTEMPT_ID': 'attempt-one', 'TICKER': 'COST',
        }), mock.patch('data_pipeline.collectors.streams.browser.source_observation.time.time', return_value=self.now):
            record_source_observation(self.agent, EVENT, [player()], waiting=False)
            text = (Path(directory)/'capture_source.json').read_text()
            record = json.loads(text)
            self.assertEqual(record['capture_session_id'], 'COST-session')
            self.assertEqual(record['source_phase'], 'replay_candidate')
            self.assertNotIn('SECRET', text)
            self.assertNotIn('DO_NOT_LOG', text)

    def test_status_requires_fresh_matching_call_session_revision_ticker(self):
        call = {'id':120, 'ticker':'COST', 'schedule_revision':5, 'capture_session_id':'COST-session'}
        source = {**call, 'call_id':'120', 'source_phase':'live_transport_observed',
                  'target_identity_verified':True,
                  'timestamp_utc':datetime.fromtimestamp(self.now, timezone.utc).isoformat()}
        result = summarize_live_verification(call, {'capture_source':source}, {'stored_rows':3}, now=self.now)
        self.assertEqual(result['source_phase'], 'live_transport_observed')
        self.assertEqual(result['minimum_live_success'], 'requires_source_and_speech_review')
        for change in ({'capture_session_id':'other'}, {'schedule_revision':6}, {'call_id':123},
                       {'ticker':'GIS'}, {'timestamp_utc':'2025-01-01T00:00:00+00:00'},
                       {'timestamp_utc':'broken'}):
            result = summarize_live_verification(call, {'capture_source':{**source, **change}},
                                                 {'stored_rows':3}, now=self.now)
            self.assertEqual(result['source_phase'], 'unconfirmed', change)
            self.assertFalse(result['target_identity_verified'], change)

    def test_waiting_capture_without_text_is_not_reported_as_failed(self):
        for status in ('upcoming', 'live', 'running'):
            result = summarize_live_verification({'status':status}, {}, {'stored_rows':0})
            self.assertEqual(result['minimum_live_success'], 'awaiting_text')

    def test_completed_capture_without_observation_is_not_live_proof(self):
        result = summarize_live_verification({'status':'completed'}, {}, {'stored_rows':216})
        self.assertEqual(result['source_phase'], 'unconfirmed')
        self.assertEqual(result['minimum_live_success'], 'requires_source_and_speech_review')


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires installed Chromium')
class PassiveBrowserSourceTest(unittest.IsolatedAsyncioTestCase):
    async def test_already_fetched_hls_is_observed_without_issuing_extra_requests(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
            try:
                page = await browser.new_page()
                requests = []
                body = [playlist(1)]
                async def route(request):
                    requests.append(request.request.url)
                    if request.request.url.endswith('.m3u8'):
                        await request.fulfill(status=200, content_type='application/vnd.apple.mpegurl', body=body[0])
                    else:
                        await request.fulfill(status=200, content_type='text/html', body='<h1>Fixture earnings call</h1>')
                await page.route('**/*', route)
                a = agent()
                attach_source_observer(a, page)
                attach_source_observer(a, page)
                await page.goto(EVENT)
                for sequence in (1, 2):
                    body[0] = playlist(sequence)
                    await page.evaluate("async () => (await fetch('/fixture.m3u8')).text()")
                    await asyncio.gather(*a._source_observations.tasks)
                result = a._source_observations.assessment(a, EVENT, [], waiting=False)
                self.assertEqual(result['source_phase'], 'live_transport_observed')
                self.assertEqual(len(requests), 3)
                self.assertFalse(result['live_success_verified'])
            finally:
                await browser.close()


class PassiveResponseBoundsTest(unittest.IsolatedAsyncioTestCase):
    async def test_unbounded_compressed_and_oversized_responses_are_not_read(self):
        for headers in ({'content-type':'application/vnd.apple.mpegurl'},
                        {'content-length':'-1'}, {'content-length':'262145'},
                        {'content-length':'100','content-encoding':'gzip'}):
            with self.subTest(headers=headers):
                a = agent()
                listeners = {}
                page = SimpleNamespace(on=lambda name, handler:listeners.update({name:handler}))
                attach_source_observer(a, page)
                response = SimpleNamespace(url=EVENT+'/media.m3u8', status=200, headers=headers,
                    request=SimpleNamespace(frame=SimpleNamespace(url=EVENT)),
                    text=mock.AsyncMock(return_value=playlist()))
                listeners['response'](response)
                await asyncio.gather(*a._source_observations.tasks)
                response.text.assert_not_awaited()
                self.assertFalse(a._source_observations.rows)
