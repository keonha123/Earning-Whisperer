from __future__ import annotations

from datetime import datetime, timezone
import json
from dataclasses import replace
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.stt_worker.audio_rescue import allocate_pcm, finalize_pcm, prune_rescue
from data_pipeline.stt_worker.model_supervisor import ModelStalled, SupervisedWhisperModel


def fake_hanging_load(connection, config):
    time.sleep(30)


def fake_model(connection, config):
    connection.send(("ready", None))
    while True:
        kind, audio, _options = connection.recv()
        path = Path(config.test_directory)
        with (path / "windows.jsonl").open("a") as output:
            output.write(json.dumps(audio) + "\n")
        if config.mode == "hang_first" and not (path / "already_hung").exists():
            (path / "already_hung").touch()
            time.sleep(30)
        if config.mode == "hang_always":
            time.sleep(30)
        connection.send(("result", [] if config.mode == "music" else ["A single recovered sentence."]))


class IsolatedModelTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "WEBCAST_PROGRESS_DIR": str(self.directory / "progress"),
            "WEBCAST_CALL_DB_ID": "568", "WEBCAST_SCHEDULE_REVISION": "1",
            "WEBCAST_ATTEMPT_ID": "attempt-a", "STT_CAPTURE_SESSION_ID": "capture-a",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def model(self, mode="hang_first", **options):
        config = SimpleNamespace(test_directory=str(self.directory), mode=mode,
                                 capture_session_id="capture-a", max_session_seconds=None)
        defaults = dict(worker_target=fake_model, load_timeout=2, inference_timeout=.3, max_restarts=1)
        defaults.update(options)
        result = SupervisedWhisperModel(config, **defaults)
        self.addCleanup(result.close)
        return result

    def test_native_inference_hang_retries_same_uncommitted_window_once(self):
        model = self.model()
        started = time.monotonic()
        segments, _ = model.transcribe([1, 2, 3], vad_filter=True)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual([segment.text for segment in segments], ["A single recovered sentence."])
        self.assertEqual(model.restarts, 1)
        self.assertEqual([json.loads(line) for line in (self.directory / "windows.jsonl").read_text().splitlines()], [[1, 2, 3], [1, 2, 3]])

    def test_native_model_load_hang_is_bounded_and_child_reaped(self):
        before = {process.pid for process in multiprocessing.active_children()}
        started = time.monotonic()
        with self.assertRaisesRegex(ModelStalled, "model_load_timeout"):
            self.model(worker_target=fake_hanging_load, load_timeout=.15, max_restarts=0)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual({process.pid for process in multiprocessing.active_children()}, before)

    def test_exhausted_inference_recovery_is_explicit_and_child_reaped(self):
        model = self.model("hang_always", max_restarts=0)
        with self.assertRaisesRegex(ModelStalled, "inference_timeout"):
            model.transcribe([0])
        self.assertIsNone(model.process)

    def test_music_without_text_keeps_same_model_and_returns_empty_windows(self):
        model = self.model("music")
        pid = model.process.pid
        for _ in range(5):
            segments, _ = model.transcribe([0, 1, 0])
            self.assertEqual(segments, [])
        self.assertEqual(model.process.pid, pid)
        self.assertEqual(model.restarts, 0)

    def write_restart(self, **overrides):
        request = dict(call_id=568, schedule_revision=1, attempt_id="attempt-a",
                       capture_session_id="capture-a", requested_at=datetime.now(timezone.utc).isoformat(), request_id="request-a")
        request.update(overrides)
        path = self.directory / "progress" / "stt-restart.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(request))

    def test_operator_restart_changes_only_model_before_same_window_result(self):
        model = self.model("normal")
        previous_pid = model.process.pid
        self.write_restart()
        segments, _ = model.transcribe([4, 5])
        self.assertNotEqual(model.process.pid, previous_pid)
        self.assertEqual(len(segments), 1)
        self.assertEqual(model.restarts, 1)

    def test_wrong_session_or_expired_restart_request_is_ignored(self):
        model = self.model("normal")
        self.write_restart(capture_session_id="different")
        previous_pid = model.process.pid
        model.transcribe([3])
        self.assertEqual(previous_pid, model.process.pid)
        self.assertEqual(model.restarts, 0)


class RescueAudioTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        env = mock.patch.dict(os.environ, {"STT_AUDIO_RESCUE_DIR": str(self.root),
            "STT_PCM_HANDOFF_MAX_BYTES": "32000", "STT_AUDIO_RESCUE_TOTAL_MAX_BYTES": "96000",
            "STT_CAPTURE_SESSION_ID": "session-a", "WEBCAST_CALL_DB_ID": "568",
            "WEBCAST_PROGRESS_DIR": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_failed_audio_and_exact_recovery_manifest_survive_cleanup(self):
        pcm = allocate_pcm()
        pcm.write_bytes(b"\x01\x00" * 16000)
        manifest = finalize_pcm(pcm, 79)
        self.assertTrue(pcm.exists())
        record = json.loads(manifest.read_text())
        self.assertEqual(record["pcm_bytes"], 32000)
        self.assertEqual(record["capture_session_id"], "session-a")
        self.assertFalse(record["automatic_consumer_resume"])
        self.assertEqual(stat.S_IMODE(pcm.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)

    def test_only_successful_session_audio_is_removed(self):
        pcm = allocate_pcm()
        pcm.write_bytes(b"\0\0" * 16000)
        self.assertIsNone(finalize_pcm(pcm, 0))
        self.assertFalse(pcm.exists())

    def test_retention_removes_closed_old_sessions_but_protects_active_audio(self):
        closed = allocate_pcm()
        closed.write_bytes(b"0" * 32000)
        manifest = finalize_pcm(closed, 79)
        data = json.loads(manifest.read_text())
        data["closed_at"] = 0
        manifest.write_text(json.dumps(data))
        active = self.root / "active.pcm"
        active.write_bytes(b"1" * 32000)
        prune_rescue(self.root, now=200000)
        self.assertFalse(closed.exists())
        self.assertTrue(active.exists())

    def test_expired_orphan_is_reclaimed_only_when_producer_identity_is_gone(self):
        pcm = self.root / "orphan.pcm"
        pcm.write_bytes(b"0" * 32000)
        Path(str(pcm) + ".owner.json").write_text(json.dumps({
            "pcm_name": pcm.name, "created_at": 0, "pid": 99999999, "process_start": "0",
        }))
        with mock.patch("data_pipeline.stt_worker.audio_rescue._legacy_runtime_quiescent", return_value=True), mock.patch("data_pipeline.stt_worker.audio_rescue._has_reader", return_value=False):
            prune_rescue(self.root, now=200000)
        self.assertFalse(pcm.exists())
        self.assertTrue((self.root / "quarantine" / pcm.stem / pcm.name).exists())

    def test_old_owner_record_never_prunes_a_still_running_producer(self):
        pcm = self.root / "active.pcm"
        pcm.write_bytes(b"0" * 32000)
        process_start = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
        Path(str(pcm) + ".owner.json").write_text(json.dumps({
            "pcm_name": pcm.name, "created_at": 0, "pid": os.getpid(), "process_start": process_start,
        }))
        prune_rescue(self.root, now=200000)
        self.assertTrue(pcm.exists())

    def test_rescue_capacity_never_deletes_active_recordings(self):
        active = self.root / "active.pcm"
        active.write_bytes(b"1" * 96000)
        with self.assertRaisesRegex(OSError, "active recordings are protected"):
            allocate_pcm()
        self.assertEqual(active.stat().st_size, 96000)

    def test_silent_pcm_has_bytes_but_is_not_reported_as_speech_or_wrong_candidate(self):
        progress = self.root / "progress"
        pcm = self.root / "silent.pcm"
        command = [sys.executable, "-m", "data_pipeline.stt_worker.pcm_handoff", "--record", str(pcm),
                   "--max-bytes", "32000", "--", sys.executable, "-c",
                   "import sys,time; [(sys.stdout.buffer.write(b'\\0'*6400),sys.stdout.buffer.flush(),time.sleep(.15)) for _ in range(4)]"]
        env = {**os.environ, "WEBCAST_PROGRESS_DIR": str(progress), "STT_AUDIO_PROGRESS_INTERVAL_SECONDS": ".1"}
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = []
        for path in progress.glob("*.jsonl"):
            events.extend(json.loads(line) for line in path.read_text().splitlines())
        samples = [event for event in events if event.get("event") == "pcm_progress"]
        self.assertTrue(samples, list(progress.iterdir()))
        self.assertTrue(any(event.get("pcm_bytes", 0) > 0 and event.get("audio_condition") == "silent" for event in samples))
        self.assertTrue(all(event["speech_classification"] == "unknown" and not event["wrong_candidate"] for event in samples))


class ArchiveAcknowledgementTest(unittest.TestCase):
    def test_database_outage_keeps_fsynced_text_without_false_commit_then_replays(self):
        import httpx
        from data_pipeline.stt_worker import delivery
        from data_pipeline.stt_worker.config import _parse_args, config_from_args
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {
            "TRANSCRIPT_ARCHIVE_SPOOL_PATH": str(Path(directory) / "archive.jsonl"),
        }):
            config = replace(config_from_args(_parse_args(["--ticker", "AZO", "--call-id", "AZO-recovery-test"])),
                             archive_transcripts=True, send_to_backend=False, send_to_ai_engine=False)
            emitter = delivery.TranscriptEmitter(config)
            with mock.patch.object(delivery, "emit_live_event") as events, mock.patch(
                "data_pipeline.database.ensure_transcript_archive_schema"), mock.patch(
                "data_pipeline.database.archive_transcript_segment", side_effect=RuntimeError("database unavailable")), httpx.Client() as client:
                committed = emitter.emit_chunk(client, "A durable earnings statement.")
            self.assertFalse(committed)
            self.assertEqual(emitter._last_durable_sequence, 0)
            self.assertIsNone(emitter._last_archived_sequence)
            kinds = [call.args[1] for call in events.call_args_list]
            self.assertIn("segment_fsynced", kinds)
            self.assertIn("db_commit_deferred", kinds)
            self.assertNotIn("segment_db_committed", kinds)
            self.assertIn("A durable earnings statement.", emitter._archive_spool_path.read_text())
            with mock.patch.object(delivery, "emit_live_event") as events, mock.patch(
                "data_pipeline.database.archive_transcript_segment") as archive:
                replay = emitter._replay_local_archive_spool()
            self.assertEqual(replay.archived_segments, {("AZO-recovery-test", 0)})
            archive.assert_called_once()
            self.assertIn("segment_db_committed", [call.args[1] for call in events.call_args_list])
            self.assertFalse(emitter._archive_spool_path.exists())


if __name__ == "__main__":
    unittest.main()
