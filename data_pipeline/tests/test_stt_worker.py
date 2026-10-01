import asyncio
import json
import os
import queue
import tempfile
import threading
import time
import unittest
from argparse import Namespace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from data_pipeline.collectors.schedules.event_routes import route_proof
from data_pipeline.stt_worker.manager import STTWorkerManager, WebcastProbeResult
from data_pipeline.stt_worker.take import (
    ArchiveSpoolReplay,
    STT_EXIT_NO_CHUNKS,
    STT_EXIT_NO_TEXT,
    TranscriptEmitter,
    _AudioReaderState,
    _deduplicate_transcript_fragment,
    _read_audio_continuously,
    build_ffmpeg_command,
    config_from_args,
    ffmpeg_exit_is_expected,
    run_audio_preflight,
    run_audio_preflight_only,
    load_whisper_model,
    retry_transcript_outbox_once,
    run_transcription,
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
        self.assertIn('terminate_child "${WEBCAST_PID:-}" true', script)
        self.assertIn(
            'export WEBCAST_MEDIA_CANDIDATES_FILE="${MEDIA_CANDIDATES_FILE}"',
            script,
        )
        self.assertIn(
            'WEBCAST_CAPTURE_LOG_FILE="${WEBCAST_CAPTURE_LOG_FILE:-}"',
            script,
        )
        self.assertIn("wait_for_pulseaudio()", script)
        self.assertIn('XDG_RUNTIME_DIR="${PULSE_RUNTIME_ROOT}/${PULSE_SINK_NAME}"', script)
        self.assertIn('export PULSE_RUNTIME_PATH', script)
        self.assertIn("pulseaudio --kill", script)
        self.assertIn('pactl set-default-sink "${PULSE_SINK_NAME}"', script)
        self.assertIn('export PULSE_SERVER="unix:${PULSE_RUNTIME_PATH}/native"', script)
        self.assertIn('FFMPEG_BIN="/usr/bin/ffmpeg"', script)
        self.assertIn("MEDIA_PULSE_FALLBACK_STARTED", script)
        self.assertIn("MEDIA_PULSE_FALLBACK_ROUTED", script)
        self.assertIn("-stream_loop -1", script)
        self.assertIn('MEDIA_FALLBACK_PID:-', script)
        self.assertIn("short historical clips are discarded", script)
        self.assertIn("restart_media_stream_fallback_if_needed", script)
        self.assertIn("MEDIA_PULSE_FALLBACK_EXITED", script)
        self.assertIn("MEDIA_PULSE_FALLBACK_ROUTE_TIMEOUT", script)
        self.assertIn('tail -n 12 "${MEDIA_FALLBACK_LOG}"', script)
        self.assertIn('"${MEDIA_CANDIDATES_FILE}" "${PROBE_MEDIA_CANDIDATES_FILE}"', script)
        self.assertIn("PROBE_READY_FOR_PROMOTION", script)
        self.assertIn("PROBE_PROMOTED_TO_CAPTURE", script)
        self.assertIn('[[ -s "${TARGET_IDENTITY_READY_FILE}" ]]', script)
        self.assertIn("export STT_TARGET_IDENTITY_VERIFIED=true", script)
        self.assertIn("PLAYBACK_READY_RECOVERED_FROM_MEDIA_CANDIDATE", script)
        self.assertIn("if start_media_stream_fallback; then", script)
        self.assertIn(r'\.(?:m3u8|mpd|mp4|m4a|mp3|aac|wav|ts)', script)
        self.assertIn("route_sink_inputs()", script)
        self.assertIn('pactl move-sink-input "${sink_input}"', script)
        self.assertIn("pulse_sink_index()", script)
        self.assertIn('while read -r sink_input sink_index _; do', script)
        self.assertIn("-v sink_index=\"${target_sink_index}\"", script)
        self.assertIn("-re", script)
        self.assertIn("-map 0:a:0?", script)
        self.assertIn("YOUTUBE_PULSE_FALLBACK_STARTED", script)
        self.assertIn("yt-dlp", script)
        self.assertIn('"${FFMPEG_BIN}" -hide_banner -loglevel error -nostdin', script)
        self.assertIn("STT_MAX_SESSION_SECONDS", script)
        self.assertIn("STT_NO_CHUNK_TIMEOUT_SECONDS", script)
        self.assertIn("STT_NO_TEXT_TIMEOUT_SECONDS", script)
        self.assertIn("capture_stt_audio_preflight()", script)
        self.assertIn("STT_PREFLIGHT_CAPTURED", script)
        self.assertIn("STT_AUDIO_PREFLIGHT_FILE", script)
        self.assertIn("STT_AUDIO_PREFLIGHT_REPORT_FILE", script)
        self.assertIn("SPEECH_PENDING short_sample_without_speech", script)
        self.assertIn("trap cleanup EXIT", script)
        self.assertIn("trap 'exit 143' TERM", script)
        self.assertIn("terminate_child()", script)
        self.assertIn('kill -KILL -- "-${pid}"', script)

    def test_ffmpeg_255_is_expected_only_after_chunk_limit(self):
        self.assertTrue(ffmpeg_exit_is_expected(255, stopped_by_limit=True))
        self.assertFalse(ffmpeg_exit_is_expected(255, stopped_by_limit=False))

    def test_rolling_window_removes_only_exact_boundary_overlap(self):
        recent = ["revenue", "grew", "ten", "percent"]

        unique = _deduplicate_transcript_fragment(
            "ten percent and guidance increased",
            recent,
        )

        self.assertEqual(unique, "and guidance increased")
        self.assertEqual(
            recent[-5:],
            ["ten", "percent", "and", "guidance", "increased"],
        )

    def test_audio_reader_drains_input_and_records_oldest_queue_drop(self):
        class Process:
            def poll(self):
                return None

        chunks: queue.Queue[bytes] = queue.Queue(maxsize=1)
        state = _AudioReaderState(
            finished=threading.Event(),
            stop_requested=threading.Event(),
            last_audio_at=time.monotonic(),
        )
        with mock.patch(
            "data_pipeline.stt_worker.take._read_available_audio",
            side_effect=[b"a" * 4, b"b" * 4, b""],
        ):
            _read_audio_continuously(Process(), chunks, state, chunk_bytes=4)

        self.assertTrue(state.finished.is_set())
        self.assertEqual(state.bytes_read, 8)
        self.assertEqual(state.dropped_bytes, 4)
        self.assertEqual(chunks.get_nowait(), b"b" * 4)

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

    def test_emitter_marks_the_last_archived_segment_as_session_end(self):
        config = config_from_args(self._args())
        emitter = TranscriptEmitter(config)

        with (
            mock.patch("data_pipeline.database.ensure_transcript_archive_schema"),
            mock.patch("data_pipeline.database.archive_transcript_segment"),
            mock.patch(
                "data_pipeline.database.mark_transcript_session_end",
                return_value=True,
            ) as mark_end,
        ):
            self.assertTrue(emitter.emit_chunk(mock.Mock(), "earnings increased"))
            self.assertTrue(
                emitter.finish_session(
                    termination_reason="bounded_capture_complete",
                    success_eligible=True,
                    target_identity_verified=True,
                )
            )

        mark_end.assert_called_once_with(
            "AAPL-2026Q3",
            0,
            termination_reason="bounded_capture_complete",
            success_eligible=True,
            target_identity_verified=True,
            ensure_schema=False,
        )

    def test_no_chunk_watchdog_returns_retryable_exit_code(self):
        class SilentProcess:
            returncode = 0
            stdout = mock.Mock()
            stderr = None

            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

        config = config_from_args(
            self._args(
                max_session_seconds=None,
                no_chunk_timeout_seconds=0.001,
            )
        )
        with (
            mock.patch("data_pipeline.stt_worker.take.load_whisper_model"),
            mock.patch("data_pipeline.stt_worker.take.subprocess.Popen", return_value=SilentProcess()),
            mock.patch("data_pipeline.stt_worker.take._read_available_audio", return_value=None),
        ):
            self.assertEqual(run_transcription(config), STT_EXIT_NO_CHUNKS)

    def test_empty_transcription_returns_no_text_instead_of_success(self):
        class EmptyProcess:
            returncode = 0
            stdout = mock.Mock()
            stderr = None

            def poll(self):
                return 0

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

        config = config_from_args(self._args(read_bytes=32000))
        model = mock.Mock()
        model.transcribe.return_value = ([], None)
        with (
            mock.patch("data_pipeline.stt_worker.take.load_whisper_model", return_value=model),
            mock.patch("data_pipeline.stt_worker.take.subprocess.Popen", return_value=EmptyProcess()),
            mock.patch(
                "data_pipeline.stt_worker.take._read_available_audio",
                side_effect=[b"\x00" * 32000, b""],
            ),
        ):
            self.assertEqual(run_transcription(config), STT_EXIT_NO_TEXT)

    def test_audio_preflight_compares_vad_without_persisting_source_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.wav"
            report_path = Path(directory) / "report.json"
            import wave

            with wave.open(str(sample_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16_000)
                wav_file.writeframes(b"\x00\x20" * 16_000)

            config = config_from_args(
                self._args(
                    preflight_audio_file=str(sample_path),
                    preflight_report_file=str(report_path),
                )
            )
            model = mock.Mock()

            def transcribe(audio_data, *, vad_filter, **kwargs):
                del audio_data, kwargs
                if vad_filter:
                    return [], None
                return [SimpleNamespace(text="voice detected")], None

            model.transcribe.side_effect = transcribe
            result = run_audio_preflight(config, model)

            self.assertIsNotNone(result)
            self.assertTrue(result.speech_detected)
            self.assertTrue(result.vad_suppressed)
            self.assertFalse(sample_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "ok")
            self.assertTrue(report["speech_detected"])
            self.assertTrue(report["vad_suppressed"])
            self.assertNotIn("voice detected", report)

    def test_audio_preflight_only_returns_retryable_code_without_speech(self):
        with tempfile.TemporaryDirectory() as directory:
            sample_path = Path(directory) / "silent.wav"
            import wave

            with wave.open(str(sample_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16_000)
                wav_file.writeframes(b"\x00\x00" * 16_000)

            config = config_from_args(
                self._args(preflight_audio_file=str(sample_path))
            )
            model = mock.Mock()
            model.transcribe.return_value = ([], None)
            with mock.patch(
                "data_pipeline.stt_worker.take.load_whisper_model",
                return_value=model,
            ):
                self.assertEqual(run_audio_preflight_only(config), STT_EXIT_NO_TEXT)

            self.assertFalse(sample_path.exists())

    def test_required_audio_preflight_blocks_long_capture_without_speech(self):
        with tempfile.TemporaryDirectory() as directory:
            sample_path = Path(directory) / "silent.wav"
            import wave

            with wave.open(str(sample_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16_000)
                wav_file.writeframes(b"\x00\x00" * 16_000)

            config = config_from_args(
                self._args(
                    preflight_audio_file=str(sample_path),
                    require_preflight_speech=True,
                )
            )
            model = mock.Mock()
            model.transcribe.return_value = ([], None)
            with (
                mock.patch(
                    "data_pipeline.stt_worker.take.load_whisper_model",
                    return_value=model,
                ),
                mock.patch("data_pipeline.stt_worker.take.subprocess.Popen") as popen,
            ):
                self.assertEqual(run_transcription(config), STT_EXIT_NO_TEXT)

            popen.assert_not_called()
            self.assertFalse(sample_path.exists())

    def test_outbox_queues_delivery_before_any_http_attempt(self):
        config = config_from_args(self._args())
        emitter = TranscriptEmitter(config)
        payload = {"call_id": "AAPL-2026Q3", "ticker": "AAPL", "sequence": 0}

        with (
            mock.patch("data_pipeline.database.ensure_transcript_outbox_schema") as ensure,
            mock.patch("data_pipeline.database.enqueue_transcript_delivery") as enqueue,
        ):
            emitter._queue_delivery(payload, "ai_engine")

        ensure.assert_called_once_with()
        enqueue.assert_called_once_with(payload, "ai_engine", ensure_schema=False)

    def test_outbox_flush_marks_successful_delivery(self):
        config = config_from_args(self._args())
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"STT_OUTBOX_SPOOL_PATH": str(Path(directory) / "outbox.jsonl")},
            clear=False,
        ):
            emitter = TranscriptEmitter(config)
            row = {
                "id": 11,
                "destination": "ai_engine",
                "payload_json": json.dumps({"call_id": "AAPL-2026Q3", "ticker": "AAPL"}),
                "attempt_count": 0,
            }
            with (
                mock.patch("data_pipeline.database.get_pending_transcript_deliveries", return_value=[row]),
                mock.patch("data_pipeline.database.mark_transcript_delivery_result") as mark,
                mock.patch.object(emitter, "_post_json", return_value=True) as post,
            ):
                emitter._flush_outbox(mock.Mock(), limit=1)

        post.assert_called_once()
        mark.assert_called_once_with(11, success=True)

    def test_outbox_local_spool_replays_atomically_after_db_recovery(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"STT_OUTBOX_SPOOL_PATH": str(Path(directory) / "outbox.jsonl")},
            clear=False,
        ):
            emitter = TranscriptEmitter(config_from_args(self._args()))
            payload = {"call_id": "AAPL-2026Q3", "ticker": "AAPL", "sequence": 1}
            with (
                mock.patch(
                    "data_pipeline.database.ensure_transcript_outbox_schema",
                    side_effect=RuntimeError("db unavailable"),
                ),
                mock.patch("data_pipeline.database.redact_sensitive_text", side_effect=lambda value: value),
            ):
                emitter._queue_delivery(payload, "ai_engine")

            self.assertTrue(emitter._outbox_spool_path.exists())
            with mock.patch("data_pipeline.database.enqueue_transcript_delivery") as enqueue:
                emitter._replay_local_spool()

        enqueue.assert_called_once_with(payload, "ai_engine")
        self.assertFalse(emitter._outbox_spool_path.exists())

    def test_archive_spool_replays_terminal_segment_after_database_recovery(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"TRANSCRIPT_ARCHIVE_SPOOL_PATH": str(Path(directory) / "archive.jsonl")},
            clear=False,
        ):
            emitter = TranscriptEmitter(config_from_args(self._args()))
            with mock.patch(
                "data_pipeline.database.ensure_transcript_archive_schema",
                side_effect=RuntimeError("db unavailable"),
            ):
                self.assertFalse(
                    emitter.emit_chunk(mock.Mock(), "earnings increased", is_final=True)
                )
                self.assertFalse(
                    emitter.finish_session(
                        termination_reason="bounded_capture_complete",
                        success_eligible=True,
                        target_identity_verified=True,
                    )
                )

            self.assertTrue(emitter._archive_spool_path.exists())
            with (
                mock.patch("data_pipeline.database.ensure_transcript_archive_schema"),
                mock.patch("data_pipeline.database.archive_transcript_segment") as archive,
                mock.patch(
                    "data_pipeline.database.mark_transcript_session_end",
                    return_value=True,
                ) as mark_end,
            ):
                replay = emitter._replay_local_archive_spool()
            self.assertFalse(emitter._archive_spool_path.exists())

        self.assertIn(("AAPL-2026Q3", 0), replay.archived_segments)
        self.assertEqual(replay.terminal_sessions, {"AAPL-2026Q3"})
        archive.assert_called_once_with(mock.ANY, ensure_schema=False)
        mark_end.assert_called_once_with(
            "AAPL-2026Q3",
            0,
            termination_reason="bounded_capture_complete",
            success_eligible=True,
            target_identity_verified=True,
            ensure_schema=False,
        )

    def test_outbox_retry_reconciles_completed_archive_sessions(self):
        emitter = mock.Mock()
        emitter._replay_local_archive_spool.return_value = ArchiveSpoolReplay(
            set(),
            set(),
            {"AAPL-capture-1"},
        )
        emitter._flush_outbox.return_value = {"attempted": 0, "sent": 0, "failed": 0}
        with (
            mock.patch(
                "data_pipeline.stt_worker.delivery.TranscriptEmitter",
                return_value=emitter,
            ),
            mock.patch(
                "data_pipeline.database.complete_recovered_call_captures_from_transcripts",
                return_value=1,
            ) as recover,
        ):
            retry_transcript_outbox_once(limit=7)

        recover.assert_called_once_with({"AAPL-capture-1"}, limit=7)


class SttWorkerManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_audible_probe_is_promoted_without_starting_a_second_process(self):
        class EmptyReader:
            async def read(self, size):
                del size
                return b""

        class HeldProcess:
            def __init__(self):
                self.pid = None
                self.returncode = None
                self.stdout = EmptyReader()
                self.finished = asyncio.Event()

            async def wait(self):
                await self.finished.wait()
                return self.returncode

            def terminate(self):
                self.returncode = -15
                self.finished.set()

            def kill(self):
                self.terminate()

        manager = STTWorkerManager()
        process = HeldProcess()
        call = {
            "ticker": "MSFT",
            "ir_url": "https://ir.example.test/events",
            "_capture_session_id": "MSFT-capture-live-1",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = {
                "WEBCAST_PROBE_PROMOTION_ENABLED": "true",
                "WEBCAST_AUDIO_READY_FILE": str(root / "audio-ready"),
                "WEBCAST_PROBE_PROMOTE_FILE": str(root / "promote"),
                "WEBCAST_PROBE_ABORT_FILE": str(root / "abort"),
                "STT_CAPTURE_SESSION_ID": "MSFT-capture-live-1",
            }

            async def spawn(*args, **kwargs):
                del args, kwargs
                asyncio.get_running_loop().call_later(
                    0.01,
                    Path(runtime["WEBCAST_AUDIO_READY_FILE"]).touch,
                )
                return process

            with (
                mock.patch.object(manager, "_probe_runtime_environment", return_value=runtime),
                mock.patch.object(manager, "_probe_command", return_value=(["fake"], None)),
                mock.patch("asyncio.create_subprocess_exec", side_effect=spawn) as create_process,
                mock.patch.object(manager, "_watch_process", new_callable=mock.AsyncMock) as watch,
            ):
                result = await manager.probe_webcast_url_detailed(call, timeout_seconds=1)
                self.assertTrue(result.audible)
                await manager.launch_date_based_audio_capture(call, capture_env=runtime)
                await asyncio.sleep(0)

            self.assertEqual(create_process.await_count, 1)
            self.assertIs(manager._active_processes["MSFT"], process)
            self.assertTrue(Path(runtime["WEBCAST_PROBE_PROMOTE_FILE"]).exists())
            watch.assert_awaited_once()
            manager._active_processes.clear()
            process.returncode = 0
            process.finished.set()

    async def test_capture_process_stops_when_database_lease_is_lost(self):
        class RunningProcess:
            def __init__(self):
                self.pid = None
                self.returncode = None
                self.finished = asyncio.Event()
                self.terminated = False

            async def wait(self):
                await self.finished.wait()
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15
                self.finished.set()

            def kill(self):
                self.terminate()

        manager = STTWorkerManager()
        process = RunningProcess()
        call = {
            "id": 31,
            "ticker": "MSFT",
            "_capture_session_id": "MSFT-capture-31-lease",
        }
        with (
            mock.patch.dict(
                os.environ,
                {"DATE_STREAM_CAPTURE_HEARTBEAT_SECONDS": "0.1"},
                clear=False,
            ),
            mock.patch(
                "data_pipeline.database.heartbeat_call_capture",
                return_value=False,
            ) as heartbeat,
            mock.patch(
                "data_pipeline.database.requeue_failed_call_capture",
                return_value=False,
            ),
        ):
            await asyncio.wait_for(
                manager._watch_process(call, "MSFT-call-31", process),
                timeout=1,
            )

        self.assertTrue(process.terminated)
        heartbeat.assert_called_once_with(
            31,
            capture_session_id="MSFT-capture-31-lease",
        )
    def test_capture_manifest_contains_probe_handoff_identity(self):
        manager = STTWorkerManager()
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "capture-manifest.json"
            active_url_path = Path(directory) / "active-url"
            media_candidates_path = Path(directory) / "media-candidates.json"
            probe_media_candidates_path = Path(directory) / "probe-media-candidates.json"
            active_url_path.write_text(
                "https://provider.example.test/replay?id=winning", encoding="utf-8"
            )
            media_candidates_path.write_text(
                json.dumps(["https://cdn.example.test/replay/master.m3u8"]),
                encoding="utf-8",
            )
            call = {
                "id": 7,
                "ticker": "MSFT",
                "call_year": 2026,
                "quarter": "Q3",
                "earning_at": "2026-08-27 14:30:00",
                "scheduled_at_utc": "2026-08-27T18:30:00+00:00",
                "_live_entrypoint_url": "https://ir.example.test/events",
                "_live_entrypoint_kind": "ir_url",
                "_live_excluded_urls": ["https://provider.example.test/replay?id=old"],
            }
            env = {
                "WEBCAST_CAPTURE_MANIFEST_FILE": str(manifest_path),
                "WEBCAST_ACTIVE_PLAYER_URL_FILE": str(active_url_path),
                "WEBCAST_MEDIA_CANDIDATES_FILE": str(media_candidates_path),
                "WEBCAST_PROBE_MEDIA_CANDIDATES_FILE": str(probe_media_candidates_path),
            }
            result = WebcastProbeResult(True, None, "AUDIO_DETECTED", 0)

            written = manager._write_capture_manifest(call, env, result)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            copied_probe_media = json.loads(
                probe_media_candidates_path.read_text(encoding="utf-8")
            )

        self.assertEqual(written, str(manifest_path))
        self.assertEqual(manifest["ticker"], "MSFT")
        self.assertEqual(manifest["quarter"], "Q3")
        self.assertEqual(manifest["target_time_utc"], "2026-08-27T18:30:00+00:00")
        self.assertEqual(manifest["final_target_url"], "https://provider.example.test/replay?id=winning")
        self.assertEqual(
            manifest["media_candidates"],
            ["https://cdn.example.test/replay/master.m3u8"],
        )
        self.assertEqual(manifest["probe_media_candidates"], str(probe_media_candidates_path))
        self.assertEqual(copied_probe_media, ["https://cdn.example.test/replay/master.m3u8"])
        self.assertEqual(manifest["audio_preflight_report"], "")
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

    async def test_failed_capture_is_requeued_instead_of_marked_terminal(self):
        class FailedProcess:
            async def wait(self):
                return 17

        manager = STTWorkerManager()
        call = {"id": 31, "ticker": "MSFT"}
        with (
            mock.patch(
                "data_pipeline.database.requeue_failed_call_capture",
                return_value=True,
            ) as requeue,
            mock.patch("data_pipeline.database.update_call_status") as update_status,
        ):
            await manager._watch_process(call, "MSFT-call-31", FailedProcess())

        requeue.assert_called_once_with(
            31,
            error="capture process exited with code 17",
        )
        update_status.assert_not_called()

    async def test_legacy_zero_exit_without_session_is_requeued_not_completed(self):
        class FinishedProcess:
            async def wait(self):
                return 0

        manager = STTWorkerManager()
        call = {"id": 31, "ticker": "MSFT"}
        with (
            mock.patch(
                "data_pipeline.database.requeue_failed_call_capture",
                return_value=True,
            ) as requeue,
            mock.patch("data_pipeline.database.update_call_status") as update_status,
        ):
            await manager._watch_process(call, "MSFT-call-31", FinishedProcess())

        requeue.assert_called_once_with(
            31,
            error="capture exited without a durable capture session",
        )
        update_status.assert_not_called()

    async def test_date_capture_completes_only_after_durable_session_proof(self):
        class FinishedProcess:
            async def wait(self):
                return 0

        manager = STTWorkerManager()
        call = {
            "id": 31,
            "ticker": "MSFT",
            "_capture_session_id": "MSFT-capture-31-proof",
        }
        with (
            mock.patch(
                "data_pipeline.database.complete_call_capture_from_transcript",
                return_value={
                    "completed": True,
                    "segment_count": 2,
                    "session_end_count": 1,
                    "ownership_lost": False,
                },
            ) as complete,
            mock.patch("data_pipeline.database.requeue_failed_call_capture") as requeue,
            mock.patch("data_pipeline.database.update_call_status") as update_status,
        ):
            await manager._watch_process(call, "MSFT-call-31", FinishedProcess())

        complete.assert_called_once_with(31, "MSFT-capture-31-proof")
        requeue.assert_not_called()
        update_status.assert_not_called()

    async def test_date_capture_with_zero_segments_is_requeued(self):
        class FinishedProcess:
            async def wait(self):
                return 0

        manager = STTWorkerManager()
        call = {
            "id": 31,
            "ticker": "MSFT",
            "_capture_session_id": "MSFT-capture-31-empty",
        }
        with (
            mock.patch(
                "data_pipeline.database.complete_call_capture_from_transcript",
                return_value={
                    "completed": False,
                    "segment_count": 0,
                    "session_end_count": 0,
                    "ownership_lost": False,
                },
            ),
            mock.patch(
                "data_pipeline.database.requeue_failed_call_capture",
                return_value=True,
            ) as requeue,
            mock.patch("data_pipeline.database.update_call_status") as update_status,
        ):
            await manager._watch_process(call, "MSFT-call-31", FinishedProcess())

        requeue.assert_called_once_with(
            31,
            error="capture exited without archived STT segments",
            capture_session_id="MSFT-capture-31-empty",
        )
        update_status.assert_not_called()

    async def test_date_capture_with_too_little_text_is_requeued(self):
        class FinishedProcess:
            async def wait(self):
                return 0

        manager = STTWorkerManager()
        call = {
            "id": 31,
            "ticker": "MSFT",
            "_capture_session_id": "MSFT-capture-31-short",
        }
        with (
            mock.patch(
                "data_pipeline.database.complete_call_capture_from_transcript",
                return_value={
                    "completed": False,
                    "segment_count": 2,
                    "text_character_count": 19,
                    "minimum_segment_count": 2,
                    "minimum_text_character_count": 80,
                    "session_end_count": 1,
                    "successful_end_count": 1,
                    "identity_verified_end_count": 1,
                    "valid_end_count": 1,
                    "ownership_lost": False,
                },
            ),
            mock.patch(
                "data_pipeline.database.requeue_failed_call_capture",
                return_value=True,
            ) as requeue,
        ):
            await manager._watch_process(call, "MSFT-call-31", FinishedProcess())

        requeue.assert_called_once_with(
            31,
            error="capture transcript contained too little text: characters=19 required=80",
            capture_session_id="MSFT-capture-31-short",
        )

    async def test_date_probe_accepts_playable_audio_even_before_speech(self):
        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return (
                    b"AUDIO_DETECTED max_volume=-12.0dB threshold=-55dB\n"
                    b"SPEECH_DETECTED vad_suppressed=false\n",
                    None,
                )

        manager = STTWorkerManager()
        call = {"ticker": "MSFT", "ir_url": "https://ir.example.com/events"}

        with (
            mock.patch("asyncio.create_subprocess_exec", return_value=FakeProcess()) as spawn,
            mock.patch.object(
                manager,
                "_probe_target_identity_verified",
                return_value=True,
            ),
        ):
            ready, error = await manager.probe_date_based_call(
                call,
                capture_env={"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true"},
            )

        self.assertTrue(ready)
        self.assertIsNone(error)
        command = spawn.call_args.args
        self.assertIn("--probe-only", command)
        self.assertIn("data_pipeline/scripts/run_webcast_audio_capture.sh", command)
        self.assertIn("MSFT", command)
        self.assertIn("https://ir.example.com/events", command)

    async def test_date_probe_keeps_webcast_ready_when_speech_is_pending(self):
        class FakeProcess:
            returncode = 71

            async def communicate(self):
                return (
                    b"AUDIO_DETECTED max_volume=-12.0dB threshold=-55dB\n"
                    b"SPEECH_NOT_DETECTED\n",
                    None,
                )

        manager = STTWorkerManager()
        with (
            mock.patch("asyncio.create_subprocess_exec", return_value=FakeProcess()),
            mock.patch.object(
                manager,
                "_probe_target_identity_verified",
                return_value=True,
            ),
        ):
            ready, error = await manager.probe_date_based_call(
                {"ticker": "MSFT", "ir_url": "https://ir.example.com/events"},
                capture_env={"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true"},
            )

        self.assertTrue(ready)
        self.assertIsNone(error)

    def test_long_capture_uses_the_unique_transcript_session_as_call_id(self):
        manager = STTWorkerManager()
        session_id = "MSFT-capture-31-unique"
        with mock.patch.dict(os.environ, {"WEBCAST_CAPTURE_RUNNER": "docker"}, clear=False):
            command = manager._build_audio_capture_command(
                {"id": 31, "ticker": "MSFT", "ir_url": "https://ir.example.com/events"},
                probe_only=False,
                capture_env={"STT_CAPTURE_SESSION_ID": session_id},
            )

        self.assertIn(f"CALL_ID={session_id}", command)

    async def test_detailed_probe_preserves_browser_training_evidence(self):
        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return (
                    b"REPLAY_TRAINING_PROXY event=Technology Conference\n"
                    b"AUDIO_DETECTED max_volume=-9.0dB threshold=-55dB\n"
                    b"SPEECH_DETECTED vad_suppressed=false\n",
                    None,
                )

        manager = STTWorkerManager()
        with mock.patch("asyncio.create_subprocess_exec", return_value=FakeProcess()):
            result = await manager.probe_webcast_url_detailed(
                {"ticker": "CRM", "ir_url": "https://ir.example.com/events"}
            )

        self.assertIsInstance(result, WebcastProbeResult)
        self.assertTrue(result.audible)
        self.assertIn("REPLAY_TRAINING_PROXY", result.output)

    async def test_detailed_probe_timeout_terminates_its_process_session(self):
        class SlowProcess:
            def __init__(self):
                self.returncode = None
                self.pid = 43210
                self.terminated = False
                self.finished = asyncio.Event()

            async def communicate(self):
                await self.finished.wait()
                return (
                    b"webcast target opened: about:blank\n"
                    b"CANDIDATE_NAVIGATION_FAILED\n",
                    None,
                )

            def terminate(self):
                self.terminated = True
                self.returncode = -15
                self.finished.set()

        process = SlowProcess()
        manager = STTWorkerManager()
        with (
            mock.patch("asyncio.create_subprocess_exec", return_value=process) as spawn,
            mock.patch.object(manager, "_probe_timeout_seconds", return_value=0.01),
        ):
            result = await manager.probe_webcast_url_detailed(
                {"ticker": "COO", "ir_url": "https://ir.example.com/events"}
            )

        self.assertFalse(result.audible)
        self.assertTrue(process.terminated)
        self.assertIn("PROBE_TIMEOUT stage=candidate_navigation", result.error)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])

    def test_live_target_extraction_includes_direct_navigation_fallbacks(self):
        targets = STTWorkerManager._extract_live_target_urls(
            "opening candidate href directly: https://provider.example/q3\n"
            "opening direct replay candidate: https://provider.example/replay\n"
        )

        self.assertEqual(
            targets,
            {
                "https://provider.example/q3",
                "https://provider.example/replay",
            },
        )

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

    async def test_live_probe_retries_excluded_target_and_preserves_successful_entrypoint(self):
        manager = STTWorkerManager()
        results = [
            WebcastProbeResult(
                False,
                "NOT_LIVE_YET scheduled event is in the future",
                "webcast target opened: https://provider.example.com/event-old\n",
                0,
            ),
            WebcastProbeResult(
                False,
                "no candidate",
                "",
                1,
            ),
            WebcastProbeResult(
                True,
                None,
                "AUDIO_DETECTED max_volume=-10.0dB threshold=-55dB\n",
                0,
                {"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true"},
            ),
        ]
        calls = []

        async def fake_probe(call, *, capture_env=None, timeout_seconds=None):
            calls.append((dict(call), dict(capture_env or {})))
            return results.pop(0)

        call = {
            "id": 7,
            "ticker": "MSFT",
            "ir_url": "https://ir.example.com/events",
            "event_url": "https://ir.example.com/event/q4",
            "earning_at": "2026-08-27",
        }
        with (
            mock.patch.object(manager, "probe_webcast_url_detailed", side_effect=fake_probe),
            mock.patch.dict(
                os.environ,
                {
                    "DATE_STREAM_CANDIDATE_ATTEMPTS": "3",
                    "DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS": "0",
                },
                clear=False,
            ),
        ):
            ready, error = await manager.probe_date_based_call(
                call,
                capture_env={"WEBCAST_LIFECYCLE": "live"},
            )

        self.assertTrue(ready)
        self.assertIsNone(error)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0]["ir_url"], "https://ir.example.com/event/q4")
        self.assertEqual(calls[1][0]["ir_url"], "https://ir.example.com/events")
        self.assertEqual(calls[2][0]["ir_url"], "https://ir.example.com/event/q4")
        self.assertIn(
            "https://provider.example.com/event-old",
            calls[2][1]["WEBCAST_LIVE_EXCLUDED_URLS"],
        )
        self.assertEqual(call["_live_entrypoint_kind"], "event_url")
        self.assertEqual(call["_live_entrypoint_url"], "https://ir.example.com/event/q4")
        self.assertEqual(
            call["_live_excluded_urls"],
            ["https://provider.example.com/event-old"],
        )

    async def test_live_probe_rejects_audible_media_without_target_identity(self):
        manager = STTWorkerManager()
        result = WebcastProbeResult(
            True,
            None,
            "AUDIO_DETECTED max_volume=-10.0dB threshold=-55dB\n",
            0,
            {"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false"},
        )
        with mock.patch.object(
            manager,
            "probe_webcast_url_detailed",
            return_value=result,
        ):
            ready, error = await manager.probe_date_based_call(
                {"ticker": "CPRT", "ir_url": "https://ir.example.com/events"},
                capture_env={"WEBCAST_LIFECYCLE": "live"},
            )

        self.assertFalse(ready)
        self.assertIn("TARGET_IDENTITY_UNCONFIRMED", error)

    async def test_auth_route_cooldown_does_not_block_ir_fallback(self):
        manager = STTWorkerManager()
        calls: list[str] = []

        async def fake_probe(call, *, capture_env=None, timeout_seconds=None):
            del capture_env, timeout_seconds
            calls.append(call["ir_url"])
            if "protected" in call["ir_url"]:
                return WebcastProbeResult(
                    False,
                    "AUTH_REQUIRED email verification",
                    "",
                    1,
                )
            return WebcastProbeResult(
                True,
                None,
                "AUDIO_DETECTED\n",
                0,
                {"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true"},
            )

        call = {
            "id": 19,
            "ticker": "KR",
            "event_url": "https://provider.example.com/protected",
            "ir_url": "https://ir.example.com/events",
        }
        with (
            mock.patch.object(
                manager,
                "probe_webcast_url_detailed",
                side_effect=fake_probe,
            ),
            mock.patch.dict(
                os.environ,
                {"DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS": "0"},
                clear=False,
            ),
        ):
            self.assertEqual(
                await manager.probe_date_based_call(
                    call,
                    capture_env={"WEBCAST_LIFECYCLE": "live"},
                ),
                (True, None),
            )
            self.assertEqual(
                await manager.probe_date_based_call(
                    call,
                    capture_env={"WEBCAST_LIFECYCLE": "live"},
                ),
                (True, None),
            )

        self.assertEqual(
            calls,
            [
                "https://provider.example.com/protected",
                "https://ir.example.com/events",
                "https://ir.example.com/events",
            ],
        )

    async def test_live_probe_falls_back_to_ir_when_stored_event_attempt_fails(self):
        manager = STTWorkerManager()
        calls = []

        async def fake_probe(call, *, capture_env=None, timeout_seconds=None):
            calls.append(dict(call))
            if len(calls) == 1:
                return WebcastProbeResult(False, "no candidate", "", 1)
            return WebcastProbeResult(
                True,
                None,
                "AUDIO_DETECTED\n",
                0,
                {"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true"},
            )

        call = {
            "ticker": "AAPL",
            "ir_url": "https://ir.example.com/events",
            "event_url": "https://provider.example.com/event/current",
        }
        with mock.patch.object(manager, "probe_webcast_url_detailed", side_effect=fake_probe):
            ready, error = await manager.probe_date_based_call(
                call,
                capture_env={"WEBCAST_LIFECYCLE": "live"},
            )

        self.assertTrue(ready)
        self.assertIsNone(error)
        self.assertEqual(calls[0]["ir_url"], "https://provider.example.com/event/current")
        self.assertEqual(calls[1]["ir_url"], "https://ir.example.com/events")
        self.assertEqual(call["_live_entrypoint_kind"], "ir_url")

    def test_live_entrypoints_prefer_webcast_then_event_then_ir(self):
        self.assertEqual(
            STTWorkerManager._live_entrypoints(
                {
                    "ir_url": "https://ir.example.com/events",
                    "event_url": "https://ir.example.com/events/q2",
                    "webcast_url": "https://provider.example.com/live/42",
                }
            ),
            [
                ("webcast_url", "https://provider.example.com/live/42"),
                ("event_url", "https://ir.example.com/events/q2"),
                ("ir_url", "https://ir.example.com/events"),
            ],
        )

    async def test_live_probe_promotes_the_winning_entrypoint_artifacts_to_capture(self):
        manager = STTWorkerManager()
        with tempfile.TemporaryDirectory() as directory:
            original_manifest = Path(directory) / "original-manifest.json"
            winner_manifest = Path(directory) / "winner-manifest.json"
            winner_active_url = Path(directory) / "winner-active-url"
            winner_active_url.write_text(
                "https://provider.example.test/current-player",
                encoding="utf-8",
            )
            result = WebcastProbeResult(
                True,
                None,
                "AUDIO_DETECTED",
                0,
                {
                    "WEBCAST_LIFECYCLE": "live",
                    "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true",
                    "WEBCAST_CAPTURE_MANIFEST_FILE": str(winner_manifest),
                    "WEBCAST_ACTIVE_PLAYER_URL_FILE": str(winner_active_url),
                    "WEBCAST_STORAGE_STATE": "winner-storage.json",
                },
            )
            calls = 0

            async def fake_probe(call, *, capture_env=None, timeout_seconds=None):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return WebcastProbeResult(False, "no candidate", "", 1)
                return result

            call = {
                "ticker": "AAPL",
                "ir_url": "https://ir.example.test/events",
                "event_url": "https://provider.example.test/event/current",
            }
            capture_env = {
                "WEBCAST_LIFECYCLE": "live",
                "WEBCAST_CAPTURE_MANIFEST_FILE": str(original_manifest),
                "WEBCAST_ACTIVE_PLAYER_URL_FILE": str(Path(directory) / "original-active"),
            }
            with mock.patch.object(
                manager,
                "probe_webcast_url_detailed",
                side_effect=fake_probe,
            ):
                ready, error = await manager.probe_date_based_call(
                    call,
                    capture_env=capture_env,
                )
            manifest = json.loads(winner_manifest.read_text(encoding="utf-8"))

        self.assertTrue(ready)
        self.assertIsNone(error)
        self.assertEqual(
            capture_env["WEBCAST_CAPTURE_MANIFEST_FILE"],
            str(winner_manifest),
        )
        self.assertEqual(capture_env["WEBCAST_STORAGE_STATE"], "winner-storage.json")
        self.assertEqual(
            capture_env["WEBCAST_LIVE_ENTRYPOINT_VERIFIED"],
            "true",
        )
        self.assertEqual(
            manifest["final_target_url"],
            "https://provider.example.test/current-player",
        )
        self.assertTrue(manifest["target_identity_verified"])

    async def test_failed_capture_uses_provider_failure_evidence_for_retry_policy(self):
        class FailedProcess:
            async def wait(self):
                return 1

        manager = STTWorkerManager()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "capture.log"
            log_path.write_text(
                "[AAPL] AUTH_REQUIRED webcast registration already exists; email login link is required\n",
                encoding="utf-8",
            )
            call = {
                "id": 31,
                "ticker": "AAPL",
                "_capture_session_id": "AAPL-capture-31",
                "_capture_log_path": str(log_path),
            }
            with mock.patch(
                "data_pipeline.database.requeue_failed_call_capture",
                return_value=False,
            ) as requeue:
                await manager._watch_process(call, "AAPL-call-31", FailedProcess())

        self.assertIn("AUTH_REQUIRED", requeue.call_args.kwargs["error"])
        self.assertEqual(
            requeue.call_args.kwargs["capture_session_id"],
            "AAPL-capture-31",
        )

    def test_selected_live_entrypoint_is_used_by_container_probe_and_capture(self):
        manager = STTWorkerManager()
        call = {
            "ticker": "MSFT",
            "ir_url": "https://ir.example.com/events",
            "_live_entrypoint_url": "https://provider.example.com/event/current",
        }
        with mock.patch.dict(os.environ, {"WEBCAST_CAPTURE_RUNNER": "container"}):
            probe_command, _ = manager._probe_command(call, capture_env={})
            capture_command = manager._build_audio_capture_command(
                call,
                probe_only=False,
                capture_env={},
            )

        self.assertEqual(probe_command[-2:], ["MSFT", "https://provider.example.com/event/current"])
        self.assertEqual(capture_command[-2:], ["MSFT", "https://provider.example.com/event/current"])

    def test_live_runtime_environment_contains_scheduled_event_date(self):
        manager = STTWorkerManager()
        environment = manager.build_isolated_capture_environment(
            {
                "ticker": "MSFT",
                "ir_url": "https://ir.example.com/events",
                "earning_at": "2026-08-27 20:00:00",
            },
            {"WEBCAST_LIFECYCLE": "live"},
        )

        self.assertEqual(environment["WEBCAST_TARGET_DATE"], "2026-08-27")

    def test_live_runtime_environment_prefers_official_webcast_date(self):
        manager = STTWorkerManager()
        environment = manager.build_isolated_capture_environment(
            {
                "ticker": "LEN",
                "ir_url": "https://ir.example.com/events",
                "earning_at": "2026-09-16 00:00:00",
                "webcast_date": "2026-09-17",
            },
            {"WEBCAST_LIFECYCLE": "live"},
        )

        self.assertEqual(environment["WEBCAST_TARGET_DATE"], "2026-09-17")

    def test_only_official_pre_resolved_live_entrypoint_is_preverified(self):
        manager = STTWorkerManager()
        official = manager.build_isolated_capture_environment(
            {
                "ticker": "CTAS",
                "ir_url": "https://provider.example.com/current",
                "_live_entrypoint_kind": "webcast_url",
                "schedule_source": "official_ir_discovered_event",
                "schedule_discovery_fingerprint": "verified-fingerprint",
                "schedule_discovery_checked_at": datetime.now(timezone.utc),
                "webcast_url": "https://provider.example.com/current",
                "schedule_evidence": route_proof(ticker="CTAS", day=date(2026, 9, 24),
                    issuer_url="https://provider.example.com/current", event_url=None,
                    webcast_url="https://provider.example.com/current"),
                "schedule_revalidation_status": "clear",
                "earning_at": "2026-09-24",
            },
            {"WEBCAST_LIFECYCLE": "live"},
        )
        generic = manager.build_isolated_capture_environment(
            {
                "ticker": "CPRT",
                "ir_url": "https://ir.example.com/events",
                "_live_entrypoint_kind": "ir_url",
                "schedule_source": "yahoo_calendar",
                "earning_at": "2026-09-10",
            },
            {"WEBCAST_LIFECYCLE": "live"},
        )

        self.assertEqual(official["WEBCAST_LIVE_ENTRYPOINT_VERIFIED"], "true")
        self.assertEqual(generic["WEBCAST_LIVE_ENTRYPOINT_VERIFIED"], "false")

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
        self.assertNotEqual(
            first_env["WEBCAST_PROBE_MEDIA_CANDIDATES_FILE"],
            second_env["WEBCAST_PROBE_MEDIA_CANDIDATES_FILE"],
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
        self.assertNotEqual(
            first_env["STT_AUDIO_PREFLIGHT_FILE"],
            second_env["STT_AUDIO_PREFLIGHT_FILE"],
        )
        self.assertNotEqual(
            first_env["STT_AUDIO_PREFLIGHT_REPORT_FILE"],
            second_env["STT_AUDIO_PREFLIGHT_REPORT_FILE"],
        )
        self.assertNotEqual(first_env["WEBCAST_STORAGE_STATE"], second_env["WEBCAST_STORAGE_STATE"])

    def test_explicit_storage_state_is_read_only_input_with_isolated_save_path(self):
        manager = STTWorkerManager()
        shared_state = "/app/data_pipeline/.runtime/state/q4_auth.json"

        environment = manager.build_isolated_capture_environment(
            {"ticker": "CRH", "ir_url": "https://ir.example.com/events"},
            {"WEBCAST_STORAGE_STATE": shared_state},
        )

        self.assertEqual(environment["WEBCAST_STORAGE_STATE"], shared_state)
        self.assertIn("ew-webcast-crh-", environment["WEBCAST_SAVE_STORAGE_STATE"])
        self.assertNotEqual(
            environment["WEBCAST_STORAGE_STATE"],
            environment["WEBCAST_SAVE_STORAGE_STATE"],
        )

    def test_replay_candidate_is_passed_as_direct_target(self):
        manager = STTWorkerManager()
        environment = manager.build_isolated_capture_environment(
            {
                "id": "training-surface-DPZ-stored-0",
                "ticker": "DPZ",
                "ir_url": "https://ir.dominos.com/events",
                "replay_target_url": "https://video.example.com/replay/123",
            },
            {"WEBCAST_LIFECYCLE": "replay"},
        )

        self.assertEqual(
            environment["WEBCAST_DIRECT_TARGET_URL"],
            "https://video.example.com/replay/123",
        )

    def test_container_artifact_path_maps_to_host_repository(self):
        path = STTWorkerManager.host_runtime_artifact_path(
            "/app/data_pipeline/.runtime/example.json"
        )

        self.assertEqual(
            path,
            Path(__file__).resolve().parents[2]
            / "data_pipeline"
            / ".runtime"
            / "example.json",
        )

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
