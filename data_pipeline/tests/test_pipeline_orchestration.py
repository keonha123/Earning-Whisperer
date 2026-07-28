import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from data_pipeline.orchestrator import EarningsOrchestrator
from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.maintenance import purge_webcast_artifacts


class PipelineOrchestrationTest(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
