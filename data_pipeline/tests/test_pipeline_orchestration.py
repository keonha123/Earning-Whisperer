import asyncio
import inspect
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy.exc import OperationalError

from data_pipeline.application.settings import capture_runtime_environment
from data_pipeline.orchestrator import EarningsOrchestrator
from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.maintenance import purge_webcast_artifacts
from data_pipeline import database


class PipelineOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    def test_capture_environment_forwards_all_browser_and_stt_settings(self):
        with mock.patch.dict(
            os.environ,
            {
                "WEBCAST_EMAIL": "automation@example.com",
                "STT_AUDIO_QUEUE_SECONDS": "240",
                "Q4_EMAIL": "q4@example.com",
                "DB_URL": "mysql://example",
                "UNRELATED_SETTING": "do-not-forward",
            },
            clear=True,
        ):
            environment = capture_runtime_environment(
                {"WEBCAST_LIFECYCLE": "live"}
            )

        self.assertEqual(environment["WEBCAST_EMAIL"], "automation@example.com")
        self.assertEqual(environment["STT_AUDIO_QUEUE_SECONDS"], "240")
        self.assertEqual(environment["Q4_EMAIL"], "q4@example.com")
        self.assertEqual(environment["DB_URL"], "mysql://example")
        self.assertEqual(environment["WEBCAST_LIFECYCLE"], "live")
        self.assertNotIn("UNRELATED_SETTING", environment)

    def test_webcast_artifact_cleanup_removes_old_files_as_a_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_jpg = root / "MSFT-old.jpg"
            old_json = root / "MSFT-old.json"
            recent_jpg = root / "AAPL-recent.jpg"
            recent_json = root / "AAPL-recent.json"
            for path in (old_jpg, old_json, recent_jpg, recent_json):
                path.write_text("artifact", encoding="utf-8")

            old_timestamp = 1.0
            os.utime(old_jpg, (old_timestamp, old_timestamp))
            os.utime(old_json, (old_timestamp, old_timestamp))

            with mock.patch.dict(os.environ, {"WEBCAST_ARTIFACTS_DIR": directory}):
                removed = purge_webcast_artifacts(retention_days=1, max_groups=2000)

            self.assertEqual(removed, 2)
            self.assertFalse(old_jpg.exists())
            self.assertFalse(old_json.exists())
            self.assertTrue(recent_jpg.exists())
            self.assertTrue(recent_json.exists())

    def test_isolated_capture_environment_uses_unique_paths_per_call(self):
        manager = STTWorkerManager()

        first = manager.build_isolated_capture_environment(
            {"ticker": "MSFT", "ir_url": "https://example.com/q1"},
            {"WEBCAST_LIFECYCLE": "live"},
        )
        second = manager.build_isolated_capture_environment(
            {"ticker": "MSFT", "ir_url": "https://example.com/q2"},
            {"WEBCAST_LIFECYCLE": "live"},
        )

        self.assertEqual(first["WEBCAST_LIFECYCLE"], "live")
        self.assertNotEqual(first["WEBCAST_PULSE_SINK"], second["WEBCAST_PULSE_SINK"])
        self.assertNotEqual(
            first["WEBCAST_PLAYBACK_READY_FILE"],
            second["WEBCAST_PLAYBACK_READY_FILE"],
        )
        self.assertNotEqual(
            first["WEBCAST_STORAGE_STATE"],
            second["WEBCAST_STORAGE_STATE"],
        )

    def test_capture_environment_forwards_stt_watchdog_bounds(self):
        orchestrator = EarningsOrchestrator()
        with mock.patch.dict(
            os.environ,
            {
                "STT_MAX_SESSION_SECONDS": "600",
                "STT_NO_CHUNK_TIMEOUT_SECONDS": "30",
                "STT_NO_TEXT_TIMEOUT_SECONDS": "120",
                "TRANSCRIPT_ARCHIVE_SPOOL_PATH": "/tmp/archive-spool.jsonl",
            },
            clear=False,
        ):
            environment = orchestrator.live_watch._capture_environment(
                {"id": 1, "ticker": "MSFT", "ir_url": "https://example.com/events"}
            )

        self.assertEqual(environment["STT_MAX_SESSION_SECONDS"], "600")
        self.assertEqual(environment["STT_NO_CHUNK_TIMEOUT_SECONDS"], "30")
        self.assertEqual(environment["STT_NO_TEXT_TIMEOUT_SECONDS"], "120")
        self.assertEqual(
            environment["TRANSCRIPT_ARCHIVE_SPOOL_PATH"],
            "/tmp/archive-spool.jsonl",
        )

    def test_schedule_mismatch_policy_only_slows_explicit_stale_evidence(self):
        mismatch = database.stream_probe_retry_policy(
            "target date mismatch on a verified event"
        )
        normal_pending = database.stream_probe_retry_policy("not live yet; no candidate")

        self.assertTrue(mismatch["requires_schedule_refresh"])
        self.assertEqual(mismatch["reason"], "schedule_mismatch")
        self.assertFalse(normal_pending["requires_schedule_refresh"])

    def test_future_page_date_does_not_invalidate_the_call_schedule(self):
        error = "NOT_LIVE_YET scheduled event date is in the future: September 9, 2026"

        same_day = database.stream_probe_retry_policy(
            error,
            watch_state="date_only",
            expected_date=date(2026, 9, 9),
        )
        different_day = database.stream_probe_retry_policy(
            error,
            watch_state="date_only",
            expected_date=date(2026, 9, 2),
        )

        self.assertFalse(same_day["requires_schedule_refresh"])
        self.assertEqual(same_day["reason"], "candidate_unavailable")
        self.assertFalse(different_day["requires_schedule_refresh"])
        self.assertEqual(different_day["reason"], "candidate_unavailable")

    def test_exact_future_start_waits_until_the_early_entry_window(self):
        future_start = datetime.now(timezone.utc) + timedelta(minutes=31)
        error = (
            "NOT_LIVE_YET scheduled event time is in the future: "
            f"{future_start.isoformat()}"
        )

        with mock.patch.dict(
            os.environ,
            {"DATE_STREAM_EARLY_ENTRY_MINUTES": "5"},
            clear=False,
        ):
            policy = database.stream_probe_retry_policy(
                error,
                watch_state="date_only",
                expected_date=future_start.date(),
            )

        self.assertEqual(policy["reason"], "scheduled_start_wait")
        self.assertFalse(policy["requires_schedule_refresh"])
        self.assertGreaterEqual(policy["retry_delay_minutes"], 25)
        self.assertLessEqual(policy["retry_delay_minutes"], 26)
        self.assertEqual(
            database.future_event_time_from_probe_error(error),
            future_start,
        )

    def test_probe_retry_policy_cools_access_failures_but_keeps_event_window_fast(self):
        with mock.patch.dict(
            os.environ,
            {
                "DATE_STREAM_BLOCKED_RETRY_MINUTES": "360",
                "DATE_STREAM_AUTH_RETRY_MINUTES": "720",
                "DATE_STREAM_NO_CANDIDATE_RETRY_MINUTES": "15",
                "DATE_STREAM_TRANSIENT_RETRY_MINUTES": "5",
                "DATE_STREAM_NEAR_LIVE_RETRY_MINUTES": "1",
                "DATE_STREAM_DATE_ONLY_RETRY_MINUTES": "1",
            },
            clear=False,
        ):
            blocked = database.stream_probe_retry_policy("HTTP 429 rate limit")
            auth = database.stream_probe_retry_policy("CAPTCHA human verification")
            near_live_auth = database.stream_probe_retry_policy(
                "CAPTCHA human verification",
                watch_state="event_window",
            )
            no_candidate = database.stream_probe_retry_policy("no playable candidate")
            near_live = database.stream_probe_retry_policy(
                "no playable candidate",
                watch_state="near_live",
            )
            event_window = database.stream_probe_retry_policy(
                "no playable candidate",
                watch_state="event_window",
            )
            date_only = database.stream_probe_retry_policy(
                "NOT_LIVE_YET no playable candidate",
                watch_state="date_only",
            )
            date_only_transient = database.stream_probe_retry_policy(
                "browser navigation failed",
                watch_state="date_only",
            )
            transient = database.stream_probe_retry_policy("browser navigation failed")

        self.assertEqual((blocked["reason"], blocked["retry_delay_minutes"]), ("access_blocked", 360))
        self.assertEqual((auth["reason"], auth["retry_delay_minutes"]), ("auth_required", 720))
        self.assertEqual(
            (
                near_live_auth["reason"],
                near_live_auth["retry_delay_minutes"],
                near_live_auth["requires_schedule_refresh"],
            ),
            ("auth_required", 1, True),
        )
        self.assertEqual(
            (no_candidate["reason"], no_candidate["retry_delay_minutes"]),
            ("candidate_unavailable", 15),
        )
        self.assertEqual((near_live["reason"], near_live["retry_delay_minutes"]), ("candidate_unavailable", 1))
        self.assertEqual(
            (event_window["reason"], event_window["retry_delay_minutes"]),
            ("candidate_unavailable", 1),
        )
        self.assertEqual(
            (date_only["reason"], date_only["retry_delay_minutes"]),
            ("candidate_unavailable", 1),
        )
        self.assertEqual(
            (date_only_transient["reason"], date_only_transient["retry_delay_minutes"]),
            ("transient_error", 1),
        )
        self.assertEqual((transient["reason"], transient["retry_delay_minutes"]), ("transient_error", 5))

    def test_capture_retry_policy_backs_off_transients_and_stops_access_barriers(self):
        with mock.patch.dict(
            os.environ,
            {
                "DATE_STREAM_CAPTURE_RETRY_MINUTES": "3",
                "DATE_STREAM_CAPTURE_RETRY_BACKOFF_MULTIPLIER": "2",
                "DATE_STREAM_CAPTURE_MAX_RETRY_MINUTES": "60",
                "DATE_STREAM_CAPTURE_MAX_ATTEMPTS": "0",
                "DATE_STREAM_CAPTURE_AUTH_MAX_ATTEMPTS": "1",
                "DATE_STREAM_CAPTURE_BLOCKED_MAX_ATTEMPTS": "1",
            },
            clear=False,
        ):
            first = database.capture_retry_policy("capture process exited with code 1", attempts=1)
            fourth = database.capture_retry_policy("capture process exited with code 1", attempts=4)
            auth = database.capture_retry_policy(
                "AUTH_REQUIRED email login link is required",
                attempts=1,
            )
            blocked = database.capture_retry_policy("HTTP 429 rate limit", attempts=1)

        self.assertEqual((first["reason"], first["retry_delay_minutes"]), ("transient_capture_error", 3))
        self.assertEqual((fourth["reason"], fourth["retry_delay_minutes"]), ("transient_capture_error", 24))
        self.assertEqual((auth["reason"], auth["max_attempts"]), ("auth_required", 1))
        self.assertEqual((blocked["reason"], blocked["max_attempts"]), ("access_blocked", 1))

    async def test_date_stream_dispatch_pauses_cleanly_when_database_is_unavailable(self):
        orchestrator = EarningsOrchestrator()
        outage = OperationalError("SELECT 1", {}, RuntimeError("database unavailable"))

        with (
            mock.patch(
                "data_pipeline.orchestrator.database.get_date_based_stream_candidates",
                side_effect=outage,
            ),
            mock.patch.object(orchestrator.health, "record_event") as record,
        ):
            dispatched = await orchestrator.dispatch_date_based_streams()

        self.assertEqual(dispatched, 0)
        event_types = [args[0] for args, _ in record.call_args_list]
        self.assertIn("database_unavailable", event_types)
        self.assertIn("watch_cycle", event_types)

    async def test_database_failure_after_probe_discards_promotable_process(self):
        orchestrator = EarningsOrchestrator()
        discarded: list[int] = []
        outage = OperationalError("UPDATE calls", {}, RuntimeError("database unavailable"))
        call = {
            "id": 41,
            "ticker": "MSFT",
            "earning_at": datetime(2026, 9, 14),
            "ir_url": "https://example.com/events",
        }

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return dict(capture_env or {})

            async def probe_date_based_call(self, call, *, capture_env=None):
                return True, None

            async def discard_promotable_probe(self, call):
                discarded.append(int(call["id"]))

        orchestrator.worker_manager = FakeWorkerManager()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.claim_stream_probe",
                return_value=True,
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.record_stream_probe",
                side_effect=outage,
            ),
            mock.patch(
                "data_pipeline.application.live_watch.probe_window",
                return_value=("date_only", 1),
            ),
            mock.patch.object(orchestrator.health, "record_event"),
        ):
            await orchestrator.live_watch._probe_and_launch_date_stream_call(
                call,
                {
                    "cooldown_minutes": 1,
                    "near_start_minutes": 20,
                    "near_end_minutes": 180,
                    "near_cooldown_minutes": 1,
                },
            )

        self.assertEqual(discarded, [41])

    def test_stale_recovery_pauses_cleanly_when_database_is_unavailable(self):
        orchestrator = EarningsOrchestrator()
        outage = OperationalError("SELECT 1", {}, RuntimeError("database unavailable"))

        with (
            mock.patch(
                "data_pipeline.orchestrator.database.recover_stale_stream_operations",
                side_effect=outage,
            ),
            mock.patch.object(orchestrator.health, "record_event") as record,
        ):
            recovered = orchestrator.recover_stale_stream_operations()

        self.assertEqual(recovered, {"probes": 0, "captures": 0})
        self.assertIn("database_unavailable", [args[0] for args, _ in record.call_args_list])

    def test_schedule_upsert_leaves_running_capture_state_untouched(self):
        source = inspect.getsource(database.save_earnings_schedules)

        self.assertIn("AND status <> 'running'", source)
        self.assertIn("AND stream_probe_status <> 'probing'", source)
        self.assertIn("status = 'running' OR stream_probe_status = 'probing'", source)

    def test_local_orphan_detection_requires_a_dead_or_reused_local_process(self):
        owner = "pipeline|test-host|123|old-start"
        with (
            mock.patch("data_pipeline.storage.live_calls.socket.gethostname", return_value="test-host"),
            mock.patch("data_pipeline.storage.live_calls.os.kill", side_effect=ProcessLookupError),
        ):
            self.assertTrue(database._is_dead_local_worker_owner(owner))

        with (
            mock.patch("data_pipeline.storage.live_calls.socket.gethostname", return_value="test-host"),
            mock.patch("data_pipeline.storage.live_calls.os.kill"),
            mock.patch("data_pipeline.storage.live_calls._linux_process_start_token", return_value="new-start"),
        ):
            self.assertTrue(database._is_dead_local_worker_owner(owner))

        with mock.patch("data_pipeline.storage.live_calls.os.kill") as kill:
            self.assertFalse(
                database._is_dead_local_worker_owner("pipeline|other-host|123|old-start")
            )
        kill.assert_not_called()

    async def test_legacy_monitor_assigns_a_unique_durable_capture_session(self):
        orchestrator = EarningsOrchestrator()
        launched: list[dict] = []
        call = {"id": 71, "ticker": "MSFT", "ir_url": "https://example.com/events"}

        class FakeWorkerManager:
            async def launch_mission(self, assigned_call):
                launched.append(dict(assigned_call))

        orchestrator.worker_manager = FakeWorkerManager()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.get_imminent_calls",
                return_value=[call],
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.mark_call_running",
                return_value=True,
            ) as mark_running,
        ):
            await orchestrator.monitor_and_trigger_stt()

        self.assertEqual(len(launched), 1)
        session_id = launched[0]["_capture_session_id"]
        self.assertTrue(session_id.startswith("MSFT-capture-71-"))
        mark_running.assert_called_once_with(71, capture_session_id=session_id)

    def test_recovery_can_request_immediate_local_orphan_reclaim(self):
        orchestrator = EarningsOrchestrator()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.recover_stale_stream_operations",
                return_value={"probes": 0, "captures": 0},
            ) as recover,
            mock.patch.object(orchestrator.health, "record_event"),
        ):
            orchestrator.recover_stale_stream_operations(recover_local_orphans=True)

        recover.assert_called_once_with(recover_local_orphans=True)

    async def test_date_stream_monitor_passes_isolated_environment_to_probe_and_capture(self):
        orchestrator = EarningsOrchestrator()
        real_manager = STTWorkerManager()
        probe_envs: list[dict[str, str] | None] = []
        capture_envs: list[dict[str, str] | None] = []
        calls = [
            {"id": 1, "ticker": "MSFT", "ir_url": "https://example.com/q1"},
            {"id": 2, "ticker": "AAPL", "ir_url": "https://example.com/q2"},
        ]

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return real_manager.build_isolated_capture_environment(call, capture_env)

            async def probe_date_based_call(self, call, *, capture_env=None):
                probe_envs.append(capture_env)
                return True, None

            async def launch_date_based_audio_capture(self, call, *, capture_env=None):
                capture_envs.append(capture_env)

        orchestrator.worker_manager = FakeWorkerManager()

        with (
            mock.patch(
                "data_pipeline.orchestrator.database.get_date_based_stream_candidates",
                return_value=calls,
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.claim_stream_probe",
                return_value=True,
            ),
            mock.patch("data_pipeline.orchestrator.database.record_stream_probe"),
            mock.patch(
                "data_pipeline.orchestrator.database.mark_call_running",
                return_value=True,
            ),
            mock.patch.dict(
                os.environ,
                {
                    "DATE_STREAM_AUTO_CAPTURE_ENABLED": "true",
                    "DATE_STREAM_WATCH_CONCURRENCY": "2",
                },
                clear=False,
            ),
        ):
            await orchestrator.monitor_date_based_streams()

        self.assertEqual(len(probe_envs), 2)
        self.assertEqual(len(capture_envs), 2)
        self.assertNotEqual(probe_envs[0]["WEBCAST_PULSE_SINK"], probe_envs[1]["WEBCAST_PULSE_SINK"])
        self.assertNotEqual(
            capture_envs[0]["WEBCAST_PLAYBACK_READY_FILE"],
            capture_envs[1]["WEBCAST_PLAYBACK_READY_FILE"],
        )

    async def test_date_stream_dispatch_does_not_wait_for_long_probe(self):
        orchestrator = EarningsOrchestrator()
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()
        call = {"id": 11, "ticker": "MSFT", "ir_url": "https://example.com/events"}

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return dict(capture_env or {})

            async def probe_date_based_call(self, call, *, capture_env=None):
                probe_started.set()
                await release_probe.wait()
                return False, "not live yet"

        orchestrator.worker_manager = FakeWorkerManager()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.get_date_based_stream_candidates",
                return_value=[call],
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.claim_stream_probe",
                return_value=True,
            ),
            mock.patch("data_pipeline.orchestrator.database.record_stream_probe"),
            mock.patch.object(orchestrator.health, "record_event"),
            mock.patch.dict(
                os.environ,
                {
                    "DATE_STREAM_WATCH_CONCURRENCY": "1",
                    "DATE_STREAM_MAINTENANCE_START": "",
                    "DATE_STREAM_MAINTENANCE_END": "",
                },
                clear=False,
            ),
        ):
            dispatched = await orchestrator.dispatch_date_based_streams()
            await asyncio.wait_for(probe_started.wait(), timeout=0.2)

            self.assertEqual(dispatched, 1)
            self.assertIn(11, orchestrator.live_watch._date_stream_background_tasks)

            # The next one-minute tick returns promptly while the old browser
            # probe remains in flight, instead of APScheduler skipping it.
            self.assertEqual(await orchestrator.dispatch_date_based_streams(), 0)
            release_probe.set()
            await asyncio.gather(
                *list(orchestrator.live_watch._date_stream_background_tasks.values())
            )

    async def test_date_stream_dispatch_counts_active_capture_against_concurrency(self):
        orchestrator = EarningsOrchestrator()
        call = {"id": 12, "ticker": "AAPL", "ir_url": "https://example.com/events"}

        class RunningProcess:
            returncode = None

        orchestrator.worker_manager._active_processes["MSFT-2026Q3"] = RunningProcess()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.get_date_based_stream_candidates",
                return_value=[call],
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.claim_stream_probe",
            ) as claim,
            mock.patch.object(orchestrator.health, "record_event"),
            mock.patch.dict(
                os.environ,
                {
                    "DATE_STREAM_WATCH_CONCURRENCY": "1",
                    "DATE_STREAM_DISCOVERY_ENABLED": "false",
                    "DATE_STREAM_MAINTENANCE_START": "",
                    "DATE_STREAM_MAINTENANCE_END": "",
                },
                clear=False,
            ),
        ):
            dispatched = await orchestrator.dispatch_date_based_streams()

        self.assertEqual(dispatched, 0)
        claim.assert_not_called()

    async def test_schedule_mismatch_defers_probe_and_refreshes_only_that_call(self):
        orchestrator = EarningsOrchestrator()
        call = {"id": 11, "ticker": "MSFT", "ir_url": "https://example.com/events"}

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return dict(capture_env or {})

            async def probe_date_based_call(self, call, *, capture_env=None):
                return False, "candidate ticker contradicts target call"

        orchestrator.worker_manager = FakeWorkerManager()
        with (
            mock.patch("data_pipeline.orchestrator.database.claim_stream_probe", return_value=True),
            mock.patch(
                "data_pipeline.orchestrator.database.record_stream_probe",
                return_value={
                    "reason": "schedule_mismatch",
                    "retry_delay_minutes": 60,
                    "requires_schedule_refresh": True,
                },
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.request_schedule_refresh",
                return_value=True,
            ) as request_refresh,
            mock.patch.object(
                orchestrator.schedules,
                "_refresh_single_live_call_schedule",
                return_value=True,
            ) as refresh,
            mock.patch(
                "data_pipeline.application.schedules.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as to_thread,
            mock.patch("data_pipeline.orchestrator.database.record_schedule_refresh_outcome") as outcome,
            mock.patch.object(orchestrator.health, "record_event"),
        ):
            await orchestrator.live_watch._probe_and_launch_date_stream_call(
                call,
                {
                    "cooldown_minutes": 1,
                    "near_start_minutes": 20,
                    "near_end_minutes": 180,
                    "near_cooldown_minutes": 1,
                },
            )

        request_refresh.assert_called_once_with(11, "candidate ticker contradicts target call")
        to_thread.assert_awaited_once_with(refresh, 11, "MSFT")
        outcome.assert_called_once_with(11, success=True, error=None)

    async def test_unrelated_future_date_never_quarantines_or_refreshes_schedule(self):
        orchestrator = EarningsOrchestrator()
        call = {
            "id": 12,
            "ticker": "HPE",
            "earning_at": datetime(2026, 9, 2),
            "ir_url": "https://example.com/events",
        }
        error = (
            "NOT_LIVE_YET scheduled event date is in the future: December 9, 2026 "
            "| MEDIA_FALLBACK_BLOCKED target_identity_unconfirmed"
        )

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return dict(capture_env or {})

            async def probe_date_based_call(self, call, *, capture_env=None):
                return False, error

        orchestrator.worker_manager = FakeWorkerManager()
        with (
            mock.patch("data_pipeline.orchestrator.database.claim_stream_probe", return_value=True),
            mock.patch(
                "data_pipeline.orchestrator.database.record_stream_probe",
                return_value=database.stream_probe_retry_policy(
                    error, watch_state="date_only", expected_date=call["earning_at"],
                ),
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.quarantine_schedule_for_official_page_date_mismatch",
                return_value=True,
            ) as quarantine,
            mock.patch(
                "data_pipeline.orchestrator.database.request_schedule_refresh",
                return_value=True,
            ),
            mock.patch.object(
                orchestrator.schedules,
                "_refresh_single_live_call_schedule",
                return_value=True,
            ) as refresh,
            mock.patch(
                "data_pipeline.application.schedules.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as to_thread,
            mock.patch("data_pipeline.orchestrator.database.record_schedule_refresh_outcome"),
            mock.patch.object(orchestrator.health, "record_event"),
        ):
            await orchestrator.live_watch._probe_and_launch_date_stream_call(
                call,
                {
                    "cooldown_minutes": 1,
                    "near_start_minutes": 20,
                    "near_end_minutes": 180,
                    "near_cooldown_minutes": 1,
                },
            )

        quarantine.assert_not_called()
        to_thread.assert_not_awaited()
        refresh.assert_not_called()

    async def test_date_capture_uses_unique_transcript_session_id(self):
        orchestrator = EarningsOrchestrator()
        captured_calls: list[dict] = []
        captured_envs: list[dict] = []
        fingerprint = "b" * 64
        call = {
            "id": 12,
            "ticker": "MSFT",
            "earning_at": datetime(2026, 9, 2),
            "schedule_discovery_fingerprint": fingerprint,
            "ir_url": "https://example.com/events",
        }

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return dict(capture_env or {})

            async def probe_date_based_call(self, call, *, capture_env=None):
                return True, None

            async def launch_date_based_audio_capture(self, call, *, capture_env=None):
                captured_calls.append(dict(call))
                captured_envs.append(dict(capture_env or {}))

        orchestrator.worker_manager = FakeWorkerManager()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.claim_stream_probe",
                return_value=True,
            ) as claim_probe,
            mock.patch("data_pipeline.orchestrator.database.record_stream_probe", return_value={}),
            mock.patch("data_pipeline.orchestrator.database.mark_call_running", return_value=True) as mark_running,
            mock.patch(
                "data_pipeline.application.live_watch.probe_window",
                return_value=("date_only", 1),
            ),
            mock.patch.object(orchestrator.health, "record_event"),
            mock.patch.dict(os.environ, {"DATE_STREAM_AUTO_CAPTURE_ENABLED": "true"}, clear=False),
        ):
            await orchestrator.live_watch._probe_and_launch_date_stream_call(
                call,
                {
                    "cooldown_minutes": 1,
                    "near_start_minutes": 20,
                    "near_end_minutes": 180,
                    "near_cooldown_minutes": 1,
                },
            )

        self.assertEqual(len(captured_calls), 1)
        session_id = captured_calls[0]["_capture_session_id"]
        self.assertTrue(session_id.startswith("MSFT-capture-12-"))
        self.assertEqual(captured_envs[0]["STT_CAPTURE_SESSION_ID"], session_id)
        identity = {
            "expected_event_date": datetime(2026, 9, 2),
            "expected_discovery_fingerprint": fingerprint,
        }
        claim_probe.assert_called_once_with(12, cooldown_minutes=1, **identity)
        mark_running.assert_called_once_with(
            12,
            capture_session_id=session_id,
            **identity,
        )

    async def test_future_call_uses_low_priority_total_probe_budget(self):
        orchestrator = EarningsOrchestrator()
        probe_environments: list[dict[str, str]] = []
        call = {
            "id": 13,
            "ticker": "MSFT",
            "earning_at": datetime(2026, 9, 16),
            "ir_url": "https://example.com/events",
        }

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return dict(capture_env or {})

            async def probe_date_based_call(self, call, *, capture_env=None):
                probe_environments.append(dict(capture_env or {}))
                return False, "NOT_LIVE_YET"

        orchestrator.worker_manager = FakeWorkerManager()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.claim_stream_probe",
                return_value=True,
            ),
            mock.patch(
                "data_pipeline.orchestrator.database.record_stream_probe",
                return_value={},
            ),
            mock.patch(
                "data_pipeline.application.live_watch.probe_window",
                return_value=("date_only_future", 60),
            ),
            mock.patch.object(orchestrator.health, "record_event"),
            mock.patch.dict(
                os.environ,
                {
                    "DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS": "600",
                    "DATE_STREAM_LOW_PRIORITY_PROBE_TIMEOUT_SECONDS": "75",
                },
                clear=False,
            ),
        ):
            await orchestrator.live_watch._probe_and_launch_date_stream_call(
                call,
                {
                    "cooldown_minutes": 1,
                    "near_start_minutes": 20,
                    "near_end_minutes": 180,
                    "near_cooldown_minutes": 1,
                },
            )

        self.assertEqual(
            probe_environments[0]["DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS"],
            "75",
        )

    async def test_simulated_24h_run_survives_restarts_and_reclaims_live_call(self):
        orchestrator = EarningsOrchestrator()
        call = {
            "id": 99,
            "ticker": "MSFT",
            "status": "live",
            "ir_url": "https://example.com/live",
        }
        claims = mock.Mock(side_effect=[True] * 24)
        launches: list[int] = []

        class FakeWorkerManager:
            def build_isolated_capture_environment(self, call, capture_env=None):
                return {**(capture_env or {}), "WEBCAST_PULSE_SINK": f"sink-{call['id']}"}

            async def probe_date_based_call(self, call, *, capture_env=None):
                return True, None

            async def launch_date_based_audio_capture(self, call, *, capture_env=None):
                launches.append(call["id"])

        orchestrator.worker_manager = FakeWorkerManager()
        fake_manager = FakeWorkerManager()
        with (
            mock.patch(
                "data_pipeline.orchestrator.database.get_date_based_stream_candidates",
                return_value=[call],
            ),
            mock.patch("data_pipeline.orchestrator.database.claim_stream_probe", claims),
            mock.patch("data_pipeline.orchestrator.database.record_stream_probe"),
            mock.patch("data_pipeline.orchestrator.database.mark_call_running", return_value=True),
            mock.patch(
                "data_pipeline.orchestrator.database.recover_stale_stream_operations",
                return_value={"probes": 1, "captures": 1},
            ) as recover,
            mock.patch.object(orchestrator.health, "record_event"),
            mock.patch.dict(
                os.environ,
                {
                    "DATE_STREAM_AUTO_CAPTURE_ENABLED": "true",
                    "DATE_STREAM_WATCH_CONCURRENCY": "1",
                },
                clear=False,
            ),
        ):
            for hour in range(24):
                if hour in {8, 16}:
                    orchestrator.recover_stale_stream_operations()
                if hour == 12:
                    # A fresh orchestrator represents a process/container restart.
                    orchestrator = EarningsOrchestrator()
                    orchestrator.worker_manager = fake_manager
                await orchestrator.monitor_date_based_streams()

        self.assertEqual(recover.call_count, 2)
        self.assertEqual(claims.call_count, 24)
        self.assertEqual(launches, [99] * 24)


if __name__ == "__main__":
    unittest.main()
