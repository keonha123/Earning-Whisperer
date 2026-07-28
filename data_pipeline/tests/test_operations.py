import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from data_pipeline.operations import build_daily_report, classify_error, record_event, write_daily_report
from data_pipeline.orchestrator import EarningsOrchestrator


class OperationsReportTest(unittest.TestCase):
    def test_error_categories_are_stable(self):
        self.assertEqual(classify_error("NOT_LIVE_YET page has not started"), "not_live_yet")
        self.assertEqual(classify_error("AUDIO_NOT_DETECTED within=90s"), "audio_not_detected")
        self.assertEqual(classify_error("unexpected provider response"), "other")

    def test_events_are_aggregated_into_daily_report(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"OPERATIONS_LOG_DIR": directory},
            clear=False,
        ):
            record_event("probe_result", ticker="MSFT", call_id=1, status="stream_ready")
            record_event(
                "probe_result",
                ticker="AAPL",
                call_id=2,
                status="pending",
                error="NOT_LIVE_YET page has not started",
            )
            report = build_daily_report()
            self.assertEqual(report["probe_count"], 2)
            self.assertEqual(report["probe_success_tickers"], ["MSFT"])
            self.assertEqual(report["probe_failure_categories"], {"not_live_yet": 1})
            json_path, markdown_path = write_daily_report()
            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())


class ProbeWindowTest(unittest.TestCase):
    def test_known_start_time_tightens_only_inside_event_window(self):
        scheduled = datetime.now(timezone.utc) + timedelta(minutes=5)
        call = {"scheduled_at_utc": scheduled}
        with mock.patch.dict(
            os.environ,
            {
                "DATE_STREAM_NEAR_START_MINUTES": "20",
                "DATE_STREAM_NEAR_END_MINUTES": "180",
                "DATE_STREAM_NEAR_INTERVAL_MINUTES": "1",
            },
            clear=False,
        ):
            state, cooldown = EarningsOrchestrator._probe_window(call, 15)
        self.assertEqual(state, "event_window")
        self.assertEqual(cooldown, 1)


if __name__ == "__main__":
    unittest.main()
