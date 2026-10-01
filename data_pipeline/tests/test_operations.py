import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from data_pipeline.operations import (
    build_daily_report,
    check_operational_alerts,
    classify_error,
    classify_failure,
    purge_operation_logs,
    record_event,
    write_daily_report,
)
from data_pipeline.orchestrator import EarningsOrchestrator


class OperationsReportTest(unittest.TestCase):
    def test_error_categories_are_stable(self):
        self.assertEqual(classify_error("NOT_LIVE_YET page has not started"), "not_live_yet")
        self.assertEqual(classify_error("AUDIO_NOT_DETECTED within=90s"), "audio_not_detected")
        self.assertEqual(classify_error("unexpected provider response"), "other")
        self.assertEqual(classify_error("page access blocked: HTTP 403"), "access_blocked")
        self.assertEqual(
            classify_error("page access blocked: Cloudflare verify you are human"),
            "access_blocked",
        )
        self.assertEqual(
            classify_error(
                "PROBE_TIMEOUT stage=candidate_navigation after 540s: "
                "webcast target opened: about:blank"
            ),
            "candidate_navigation",
        )

    def test_failure_classifier_produces_actionable_learning_record(self):
        failure = classify_failure("ESS AUDIO_NOT_DETECTED sink_state=IDLE input_state=not-found")
        self.assertEqual(failure["category"], "audio_not_detected")
        self.assertEqual(failure["stage"], "audio")
        self.assertEqual(failure["action"], "inspect_sink_and_media_route")
        self.assertEqual(len(failure["signature"]), 16)

        self.assertEqual(
            classify_failure("NON_TARGET_EVENT INVESTOR DAY")["action"],
            "ignore_and_reselect",
        )

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
            self.assertEqual(report["probe_failure_categories"], {})
            self.assertEqual(report["probe_waiting_count"], 1)
            self.assertEqual(report["probe_failure_actions"], {})
            self.assertEqual(report["latest_probe_ticker_count"], 2)
            self.assertEqual(report["latest_probe_success_count"], 1)
            self.assertEqual(report["latest_probe_failure_categories"], {})
            json_path, markdown_path = write_daily_report()
            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())

    def test_latest_probe_collapses_repeated_ticker_results(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"OPERATIONS_LOG_DIR": directory},
            clear=False,
        ):
            record_event("probe_result", ticker="MSFT", call_id=1, status="pending", error="AUDIO_NOT_DETECTED")
            record_event("probe_result", ticker="MSFT", call_id=1, status="stream_ready")
            report = build_daily_report()
            self.assertEqual(report["probe_count"], 2)
            self.assertEqual(report["latest_probe_ticker_count"], 1)
            self.assertEqual(report["latest_probe_success_tickers"], ["MSFT"])
            self.assertEqual(report["latest_probe_failure_count"], 0)

    def test_operation_logs_redact_urls_and_expire_old_files(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"OPERATIONS_LOG_DIR": directory},
            clear=False,
        ):
            path = record_event(
                "probe_result",
                ticker="MSFT",
                destination_url="https://provider.example.test/start?token=secret-value",
                error="request failed https://provider.example.test/start?session=session-secret",
            )
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("secret-value", raw)
            self.assertNotIn("session-secret", raw)
            self.assertIn("%5BREDACTED%5D", raw)

            old_timestamp = 1.0
            os.utime(path, (old_timestamp, old_timestamp))
            self.assertEqual(purge_operation_logs(retention_days=1), 1)
            self.assertFalse(path.exists())

    def test_operational_alerts_are_deduplicated_and_recovery_is_logged(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {
                "OPERATIONS_LOG_DIR": directory,
                "OPERATIONS_ALERT_STATE_FILE": os.path.join(directory, "alerts.json"),
                "OPERATIONS_ALERT_STALE_COUNT": "1",
                "OPERATIONS_ALERT_COOLDOWN_SECONDS": "60",
            },
            clear=False,
        ), mock.patch("data_pipeline.operations._post_alert") as post_alert:
            snapshot = {
                "stale_probe_count": 1,
                "stale_capture_count": 0,
                "due_outbox_count": 0,
                "total_outbox_count": 0,
                "failed_outbox_count": 0,
            }
            self.assertEqual(len(check_operational_alerts(snapshot)), 1)
            self.assertEqual(len(check_operational_alerts(snapshot)), 0)
            post_alert.assert_not_called()

            recovered = {
                **snapshot,
                "stale_probe_count": 0,
            }
            self.assertEqual(check_operational_alerts(recovered), [])
            events = build_daily_report()["events"]
            self.assertEqual(
                [event["event_type"] for event in events],
                ["operational_alert", "operational_alert_recovered"],
            )


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

    def test_date_only_future_and_stale_calls_do_not_use_one_minute_loop(self):
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/New_York")).date()
        with mock.patch.dict(
            os.environ,
            {
                "DATE_STREAM_FUTURE_DATE_INTERVAL_MINUTES": "60",
                "DATE_STREAM_STALE_DATE_INTERVAL_MINUTES": "180",
            },
            clear=False,
        ):
            future = EarningsOrchestrator._probe_window(
                {"webcast_date": today + timedelta(days=1)},
                1,
            )
            stale = EarningsOrchestrator._probe_window(
                {"webcast_date": today - timedelta(days=1)},
                1,
            )

        self.assertEqual(future, ("date_only_future", 60))
        self.assertEqual(stale, ("date_only_stale", 180))


if __name__ == "__main__":
    unittest.main()
