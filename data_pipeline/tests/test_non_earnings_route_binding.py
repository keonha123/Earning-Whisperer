"""A contradictory old event can exclude only the exact routes it identified."""
from datetime import datetime,timezone
import unittest
from data_pipeline.collectors.schedules.event_routes import route_proof
from data_pipeline.stt_worker.manager import STTWorkerManager


class NonEarningsRouteBindingTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.call=dict(id=1,ticker='TEST',earning_at=self.now.date(),schedule_revision=1,
            ir_url='https://issuer.test/events',event_url='https://issuer.test/event/analyst',
            webcast_url='https://provider.test/analyst',schedule_source='official_ir_event',
            schedule_revalidation_status='clear',schedule_discovery_checked_at=self.now,
            schedule_discovery_fingerprint='proof')
        self.call['schedule_evidence']=self.evidence()

    def evidence(self,**overrides):
        values=dict(ticker='TEST',day=self.now.date(),issuer_url=self.call['ir_url'],
                    event_url=self.call['event_url'],webcast_url=self.call['webcast_url'])
        values.update(overrides)
        return route_proof(**values)+' Post Earnings Analyst Call'

    def proof(self,url,evidence='target date and earnings context matched'):
        return dict(verified=True,call_id=1,call_ticker='TEST',schedule_revision=1,
                    target_date=str(self.now.date()),source_url=self.call['ir_url'],
                    target_url=url,observed_at=self.now.isoformat(),evidence=evidence)

    def test_known_wrong_provider_and_detail_excluded_but_issuer_kept(self):
        self.assertEqual(STTWorkerManager._live_entrypoints(self.call), [('ir_url',self.call['ir_url'])])
        self.assertFalse(STTWorkerManager._fresh_discovery_proof(
            self.call,self.call['webcast_url'],self.proof(self.call['webcast_url'])))

    def test_replacement_provider_is_not_tainted_by_old_route_evidence(self):
        replacement='https://provider.test/actual-earnings'
        self.call['webcast_url']=replacement
        proof=self.proof(replacement,'Q4 earnings call '+str(self.now.date()))
        self.assertIn(('webcast_url',replacement),STTWorkerManager._live_entrypoints(self.call))
        self.assertTrue(STTWorkerManager._fresh_discovery_proof(self.call,replacement,proof))
        self.call.update(_live_entrypoint_kind='webcast_url',_live_entrypoint_url=replacement,
                         _live_discovery_proof=proof)
        self.assertEqual(STTWorkerManager._probe_runtime_environment(self.call,{})['WEBCAST_LIVE_ENTRYPOINT_VERIFIED'],'true')

    def test_missing_or_generic_evidence_is_not_a_route_blacklist(self):
        for evidence in ('','target date and earnings context matched',
                         'Post Earnings Analyst Call'):
            self.call['schedule_evidence']=evidence
            self.assertIn(('webcast_url',self.call['webcast_url']),STTWorkerManager._live_entrypoints(self.call))

    def test_wrong_ticker_or_date_or_period_cannot_blacklist_reused_url(self):
        from datetime import timedelta
        self.call.update(verified_fiscal_year=2026,verified_fiscal_quarter='Q4')
        for override in ({'ticker':'OTHER'},{'day':self.now.date()-timedelta(days=90)},
                         {'fiscal_year':2025,'fiscal_quarter':'Q4'},
                         {'fiscal_year':2026,'fiscal_quarter':'Q3'},
                         {'issuer_url':'https://different.test/events'}):
            with self.subTest(override=override):
                self.call['schedule_evidence']=self.evidence(**override)
                self.assertIn(('webcast_url',self.call['webcast_url']),STTWorkerManager._live_entrypoints(self.call))

    def test_shared_issuer_listing_remains_discoverable(self):
        self.call['event_url']=self.call['ir_url']
        self.call['schedule_evidence']=self.evidence()
        self.assertEqual(STTWorkerManager._live_entrypoints(self.call), [('event_url',self.call['ir_url'])])

    def test_generic_proof_for_same_rejected_url_cannot_be_remembered(self):
        proof=self.proof(self.call['webcast_url'])
        self.assertIsNone(STTWorkerManager._bound_route_proof(self.call,proof))
