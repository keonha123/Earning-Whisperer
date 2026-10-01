"""Only typed, current issuer evidence can skip fresh browser discovery."""
from datetime import date, datetime, timezone
import unittest

from data_pipeline.collectors.schedules.event_routes import route_proof
from data_pipeline.stt_worker.manager import STTWorkerManager


class ScheduleRouteHandoffTest(unittest.TestCase):
    def call(self):
        return {"id": 1, "ticker": "TEST", "earning_at": datetime(2026, 9, 23),
                "call_year": 2026, "quarter": "Q3",
                "ir_url": "https://issuer.test/events", "event_url": "https://issuer.test/current",
                "webcast_url": "https://unknown-provider.test/session/current",
                "schedule_source": "official_ir_discovery", "schedule_revalidation_status": "clear",
                "schedule_discovery_fingerprint": "version2",
                "schedule_discovery_checked_at": datetime.now(timezone.utc)}

    def proof(self, call, **overrides):
        values = dict(ticker=call["ticker"], day=date(2026, 9, 23), issuer_url=call["ir_url"],
                      event_url=call["event_url"], webcast_url=call["webcast_url"])
        values.update(overrides)
        return route_proof(**values)

    def test_legacy_date_marker_requires_rediscovery(self):
        call = self.call()
        call["schedule_evidence"] = "[target-linked:webcast_url=2026-09-23] Earnings webcast"
        self.assertIsNone(STTWorkerManager._stored_target_proof(call))

    def test_scoped_unknown_provider_can_be_used(self):
        call = self.call(); call["schedule_evidence"] = self.proof(call)
        self.assertEqual(STTWorkerManager._stored_target_proof(call)["target_url"], call["webcast_url"])

    def test_wrong_issuer_or_date_or_ticker_cannot_authenticate_route(self):
        for overrides in ({"issuer_url": "https://different.test/events"},
                          {"ticker": "OTHER"}, {"day": date(2026, 9, 24)}):
            with self.subTest(overrides=overrides):
                call = self.call(); call["schedule_evidence"] = self.proof(call, **overrides)
                self.assertIsNone(STTWorkerManager._stored_target_proof(call))

    def test_ads_and_documents_cannot_be_live_entrypoints(self):
        call = self.call()
        call.update(webcast_url="https://googleads.g.doubleclick.net/earnings-webcast",
                    event_url="https://issuer.test/earnings-presentation.pdf")
        self.assertEqual(STTWorkerManager._live_entrypoints(call), [("ir_url", call["ir_url"])])
        call["schedule_evidence"] = self.proof(call)
        self.assertIsNone(STTWorkerManager._stored_target_proof(call))

    def test_proof_must_match_verified_fiscal_period(self):
        call = self.call()
        call.update(verified_fiscal_year=2027, verified_fiscal_quarter="Q1")
        call["schedule_evidence"] = self.proof(call, fiscal_year=2026, fiscal_quarter="Q3")
        self.assertIsNone(STTWorkerManager._stored_target_proof(call))
        call["schedule_evidence"] = self.proof(call, fiscal_year=2027, fiscal_quarter="Q1")
        self.assertIsNotNone(STTWorkerManager._stored_target_proof(call))

    def test_release_only_event_is_not_playback_proof(self):
        call = self.call()
        call["schedule_evidence"] = self.proof(call, event_type="earnings_date")
        self.assertIsNone(STTWorkerManager._stored_target_proof(call))

    def test_live_browser_uses_issuer_fiscal_period_not_calendar_bucket(self):
        call = self.call()
        env = STTWorkerManager._probe_runtime_environment(call, {"WEBCAST_LIFECYCLE": "live"})
        self.assertEqual(env["WEBCAST_TARGET_YEAR"], "")
        self.assertEqual(env["WEBCAST_TARGET_QUARTER"], "")
        call.update(verified_fiscal_year=2027, verified_fiscal_quarter="Q1")
        env = STTWorkerManager._probe_runtime_environment(call, {"WEBCAST_LIFECYCLE": "live"})
        self.assertEqual(env["WEBCAST_TARGET_YEAR"], "2027")
        self.assertEqual(env["WEBCAST_TARGET_QUARTER"], "Q1")
