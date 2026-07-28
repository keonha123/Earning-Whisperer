import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.stt_worker.take import (
    TranscriptEmitter,
    build_ffmpeg_command,
    config_from_args,
    ffmpeg_exit_is_expected,
    load_whisper_model,
)


class SttWorkerConfigTest(unittest.TestCase):
    def _args(self, **overrides):
        values = {
            "ticker": "aapl",
            "call_id": "AAPL-2026Q3",
            "input_kind": "device",
            "input_source": "default",
            "input_format": "alsa",
            "ffmpeg_bin": "ffmpeg",
            "model_name": "tiny",
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": 1,
            "beam_size": 1,
            "language": "en",
            "read_bytes": 64000,
            "reads_per_emit": 5,
            "max_chunks": None,
            "no_ai_engine": True,
            "no_backend": True,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_device_input_builds_ffmpeg_device_command(self):
        config = config_from_args(self._args())

        self.assertEqual(config.ticker, "AAPL")
        self.assertEqual(
            build_ffmpeg_command(config),
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-f",
                "alsa",
                "-i",
                "default",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ],
        )

    def test_file_input_does_not_add_device_format(self):
        config = config_from_args(
            self._args(input_kind="file", input_source="/tmp/sample.wav")
        )

        command = build_ffmpeg_command(config)
        self.assertNotIn("-f alsa", json.dumps(command))
        self.assertIn("/tmp/sample.wav", command)

    def test_audio_capture_exports_browser_handshake_files(self):
        script_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_webcast_audio_capture.sh"
        )
        script = script_path.read_text(encoding="utf-8")

        self.assertIn(
            'export WEBCAST_MANUAL_READY_FILE="${MANUAL_READY_FILE}"',
            script,
        )
        self.assertIn(
            'export WEBCAST_PLAYBACK_READY_FILE="${PLAYBACK_READY_FILE}"',
            script,
        )
        self.assertIn(
            'export WEBCAST_ACTIVE_PLAYER_URL_FILE="${ACTIVE_PLAYER_URL_FILE}"',
            script,
        )
        self.assertIn('setsid xvfb-run -a', script)
        self.assertIn('kill -- "-${WEBCAST_PID}"', script)
        self.assertIn(
            'export WEBCAST_MEDIA_CANDIDATES_FILE="${MEDIA_CANDIDATES_FILE}"',
            script,
        )
        self.assertIn("wait_for_pulseaudio()", script)
        self.assertIn("MEDIA_PULSE_FALLBACK_STARTED", script)
        self.assertIn('extensions=(".m3u8", ".mpd", ".mp4", ".m4a", ".mp3", ".aac", ".wav")', script)
        self.assertIn("YOUTUBE_PULSE_FALLBACK_STARTED", script)
        self.assertIn("yt-dlp", script)
        self.assertIn("ffplay", script)

    def test_ffmpeg_255_is_expected_only_after_chunk_limit(self):
        self.assertTrue(ffmpeg_exit_is_expected(255, stopped_by_limit=True))
        self.assertFalse(ffmpeg_exit_is_expected(255, stopped_by_limit=False))

    def test_whisper_model_initialization_uses_process_lock(self):
        config = config_from_args(self._args())
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "model.lock"
            with (
                mock.patch.dict(os.environ, {"STT_MODEL_LOCK_PATH": str(lock_path)}),
                mock.patch("data_pipeline.stt_worker.take.WhisperModel", return_value="model") as model,
            ):
                loaded = load_whisper_model(config)

        self.assertEqual(loaded, "model")
        model.assert_called_once_with(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
        )

    def test_transcript_archive_can_be_disabled_without_affecting_live_config(self):
        with mock.patch.dict(os.environ, {"TRANSCRIPT_ARCHIVE_ENABLED": "false"}):
            config = config_from_args(self._args())

        self.assertFalse(config.archive_transcripts)

    def test_emitter_archives_text_once_per_emitted_segment(self):
        config = config_from_args(self._args())
        emitter = TranscriptEmitter(config)

        with (
            mock.patch("data_pipeline.database.ensure_transcript_archive_schema") as ensure_schema,
            mock.patch("data_pipeline.database.archive_transcript_segment") as archive,
        ):
            emitter.emit_chunk(mock.Mock(), "earnings increased")
            emitter.emit_chunk(mock.Mock(), "guidance is maintained")

        ensure_schema.assert_called_once_with()
        self.assertEqual(archive.call_count, 2)
        self.assertEqual(archive.call_args.args[0]["call_id"], "AAPL-2026Q3")
        archive.assert_any_call(mock.ANY, ensure_schema=False)


class SttWorkerManagerTest(unittest.IsolatedAsyncioTestCase):
    def test_build_command_uses_discovered_video_url(self):
        manager = STTWorkerManager()

        with mock.patch.dict(os.environ, {"STT_WORKER_INPUT_KIND": "url"}):
            command = manager._build_command(
                {
                    "ticker": "MSFT",
                    "video_url": "https://cdn.example.com/event/playlist.m3u8",
                },
                "MSFT-2026Q2",
            )

        self.assertIn("--input-kind", command)
        self.assertIn("url", command)
        self.assertIn("--input-source", command)
        self.assertIn("https://cdn.example.com/event/playlist.m3u8", command)

    async def test_date_probe_accepts_only_audio_detection(self):
        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return b"AUDIO_DETECTED max_volume=-12.0dB threshold=-55dB\n", None

        manager = STTWorkerManager()
        call = {"ticker": "MSFT", "ir_url": "https://ir.example.com/events"}

        with mock.patch("asyncio.create_subprocess_exec", return_value=FakeProcess()) as spawn:
            ready, error = await manager.probe_date_based_call(call)

        self.assertTrue(ready)
        self.assertIsNone(error)
        command = spawn.call_args.args
        self.assertIn("--probe-only", command)
        self.assertIn("data_pipeline/scripts/run_webcast_audio_capture.sh", command)
        self.assertIn("MSFT", command)
        self.assertIn("https://ir.example.com/events", command)

    async def test_date_probe_rejects_success_exit_without_audio(self):
        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return b"webcast button clicked\n", None

        manager = STTWorkerManager()
        with mock.patch("asyncio.create_subprocess_exec", return_value=FakeProcess()):
            ready, error = await manager.probe_date_based_call(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/events"}
            )

        self.assertFalse(ready)
        self.assertIn("audio probe failed", error)

    async def test_date_probe_rejects_audio_from_not_live_page(self):
        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return (
                    b"NOT_LIVE_YET scheduled event is in the future\n"
                    b"AUDIO_DETECTED max_volume=-12.0dB threshold=-55dB\n",
                    None,
                )

        manager = STTWorkerManager()
        with mock.patch("asyncio.create_subprocess_exec", return_value=FakeProcess()):
            ready, error = await manager.probe_date_based_call(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/events"}
            )

        self.assertFalse(ready)
        self.assertIn("NOT_LIVE_YET", error)

    def test_discovery_error_is_not_reported_as_an_audio_probe(self):
        error = STTWorkerManager._process_error(
            "webcast button not found\n",
            1,
            operation="webcast discovery",
        )

        self.assertIn("webcast discovery failed", error)
        self.assertNotIn("audio probe failed", error)

    def test_container_probe_runs_audio_script_without_docker(self):
        manager = STTWorkerManager()
        with mock.patch.dict(os.environ, {"WEBCAST_CAPTURE_RUNNER": "container"}):
            command, environment = manager._probe_command(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/events"},
                capture_env={"DATE_STREAM_AUDIO_WAIT_SECONDS": "15"},
            )

        self.assertEqual(command[:3], ["bash", "data_pipeline/scripts/run_webcast_audio_capture.sh", "--probe-only"])
        self.assertEqual(command[-2:], ["MSFT", "https://ir.example.com/events"])
        self.assertEqual(environment["DATE_STREAM_AUDIO_WAIT_SECONDS"], "15")

    def test_container_probe_isolates_concurrent_runtime_paths(self):
        manager = STTWorkerManager()
        with mock.patch.dict(os.environ, {"WEBCAST_CAPTURE_RUNNER": "container"}):
            _, first_env = manager._probe_command(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/q1"},
                capture_env={},
            )
            _, second_env = manager._probe_command(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/q2"},
                capture_env={},
            )

        self.assertNotEqual(first_env["WEBCAST_PULSE_SINK"], second_env["WEBCAST_PULSE_SINK"])
        self.assertNotEqual(
            first_env["WEBCAST_PLAYBACK_READY_FILE"],
            second_env["WEBCAST_PLAYBACK_READY_FILE"],
        )

    def test_build_isolated_capture_environment_keeps_call_files_separate(self):
        manager = STTWorkerManager()

        first_env = manager.build_isolated_capture_environment(
            {"id": 101, "ticker": "MSFT", "ir_url": "https://ir.example.com/events"},
            {"WEBCAST_LIFECYCLE": "live"},
        )
        second_env = manager.build_isolated_capture_environment(
            {"id": 202, "ticker": "MSFT", "ir_url": "https://ir.example.com/events"},
            {"WEBCAST_LIFECYCLE": "live"},
        )

        self.assertEqual(first_env["WEBCAST_LIFECYCLE"], "live")
        self.assertNotEqual(first_env["WEBCAST_PULSE_SINK"], second_env["WEBCAST_PULSE_SINK"])
        self.assertNotEqual(
            first_env["WEBCAST_RECIPE_CONTEXT_PATH"],
            second_env["WEBCAST_RECIPE_CONTEXT_PATH"],
        )
        self.assertNotEqual(first_env["WEBCAST_STORAGE_STATE"], second_env["WEBCAST_STORAGE_STATE"])

    def test_infers_missing_quarter_from_target_url(self):
        self.assertEqual(
            STTWorkerManager._infer_call_quarter(
                {
                    "ir_url": "https://investors.example.com/events/q1-2026-earnings-call",
                    "quarter": None,
                }
            ),
            "Q1",
        )
        self.assertEqual(
            STTWorkerManager._infer_call_quarter(
                {"ir_url": "https://investors.example.com/events", "quarter": "Q2"}
            ),
            "Q2",
        )

    async def test_resolve_webcast_source_from_ir_url(self):
        class FakeBrowserWebcastAgent:
            def __init__(self, *args, **kwargs):
                pass

            async def run(self):
                return SimpleNamespace(
                    success=True,
                    error=None,
                    media_candidates=["https://cdn.example.com/event/playlist.m3u8"],
                )

        call = {"id": 7, "ticker": "MSFT", "ir_url": "https://ir.example.com/events"}
        manager = STTWorkerManager()

        with mock.patch.dict(
            os.environ,
            {
                "STT_WEBCAST_DISCOVERY_ENABLED": "true",
                "STT_WORKER_INPUT_KIND": "url",
            },
        ):
            with mock.patch(
                "data_pipeline.collectors.streams.browser_webcast.BrowserWebcastAgent",
                FakeBrowserWebcastAgent,
            ):
                with mock.patch("data_pipeline.database.update_call_video_url") as update_url:
                    await manager._resolve_webcast_source(call)

        self.assertEqual(call["video_url"], "https://cdn.example.com/event/playlist.m3u8")
        update_url.assert_called_once_with(7, "https://cdn.example.com/event/playlist.m3u8")


if __name__ == "__main__":
    unittest.main()
