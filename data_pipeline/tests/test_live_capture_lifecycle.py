"""Run the real STT queue/loop against a simulated PCM producer and clock.

Whisper and delivery are replaced, but input reading, queue consumption,
rolling/tail transcription, watchdogs and terminal classification all execute.
No network, model download, production database or real-time waiting is used.
"""

from argparse import Namespace
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import time as wall_time
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.stt_worker.config import config_from_args
from data_pipeline.stt_worker import take


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now


class Producer:
    stdout = None
    stderr = None

    def __init__(self, blocks, exit_code=0):
        self.blocks = iter(blocks)
        self.returncode = None
        self.exit_code = exit_code

    def read(self, *_args):
        try:
            return next(self.blocks)
        except StopIteration:
            self.returncode = self.exit_code
            return b""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class CaptureEmitter:
    def __init__(self):
        self.sequence = 0
        self.texts = []
        self.terminal = None

    def emit_chunk(self, client, text, *, is_final=False):
        self.sequence += 1
        self.texts.append(text.strip())
        return True

    def finish_session(self, **marker):
        self.terminal = marker
        return True


class StopThenTailProducer(Producer):
    """A live input that exposes its final PCM only after SIGTERM is requested."""
    def __init__(self, blocks, exit_code=255):
        super().__init__(blocks, exit_code)
        self.first = True
        self.stop = threading.Event()
        self.terminate_calls = 0

    def read(self, *_args):
        if self.first:
            self.first = False
            return super().read()
        if not self.stop.wait(0.05):
            return None
        return super().read()

    def terminate(self):
        self.terminate_calls += 1
        self.stop.set()


class NeverStoppingProducer(Producer):
    """Continue supplying PCM after ignored SIGTERM, one block per inference."""
    def __init__(self, blocks, exit_code=0):
        super().__init__(blocks, exit_code)
        self.permit = threading.Event()
        self.permit.set()
        self.identifier = 0
        self.terminate_calls = 0

    def read(self, *_args):
        if self.returncode is not None:
            return b""
        if not self.permit.wait(0.05):
            return None
        self.permit.clear()
        self.identifier += 1
        return struct.pack("<h", self.identifier) * 16000

    def after_transcribe(self):
        self.permit.set()

    def terminate(self):
        self.terminate_calls += 1

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("simulated-direct-recorder", timeout)
        return self.returncode


class BackloggedFollower(Producer):
    """A spool follower whose reading advances only when inference frees space."""
    def __init__(self, blocks, exit_code=130):
        super().__init__(blocks, exit_code)
        self.permit = threading.Event()
        self.permit.set()
        self.terminate_calls = 0

    def read(self, *_args):
        if not self.permit.wait(0.05):
            return None
        self.permit.clear()
        return super().read()

    def after_transcribe(self):
        self.permit.set()

    def terminate(self):
        self.terminate_calls += 1
        super().terminate()


def args():
    return Namespace(
        ticker="TEST", call_id="TEST-current-call", input_kind="device",
        input_source="isolated.monitor", input_format="pulse", ffmpeg_bin="ffmpeg",
        model_name="fake", device="cpu", compute_type="int8", cpu_threads=1,
        beam_size=1, language="en", read_bytes=32000, overlap_bytes=0,
        reads_per_emit=1, max_chunks=None, no_ai_engine=True, no_backend=True,
    )


class LiveCaptureLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.marker = Path(self.directory.name) / "live-end.json"
        self.started = wall_time.time() - 2
        self.environment = {
            "WEBCAST_LIFECYCLE": "live", "WEBCAST_SUPERVISED_LIVE": "true",
            "WEBCAST_LIVE_TERMINATION_FILE": str(self.marker),
            "WEBCAST_LIVE_RUN_ID": "unique-current-run",
            "WEBCAST_LIVE_RUN_STARTED_AT": str(self.started),
            "STT_CAPTURE_SESSION_ID": "unique-capture-session",
            "STT_TARGET_IDENTITY_VERIFIED": "true",
            "WEBCAST_TARGET_DATE": "2026-09-18",
        }

    def write_marker(self, **changes):
        marker = {
            "version": 1, "reason": "event_ended", "call_id": "TEST-current-call",
            "capture_session_id": "unique-capture-session", "run_id": "unique-current-run",
            "created_at": wall_time.time(), "target_identity_verified": True,
            "event_identity": {"verified": True, "call_ticker": "TEST", "target_date": "2026-09-18"},
            "url": "https://provider.example/current", "evidence": "The webcast has ended",
        }
        marker.update(changes)
        self.marker.write_text(json.dumps(marker))

    def run_capture(self, *, count=3, step_seconds=1, end_after=None, end_changes=None,
                    overrides=None, silent_ids=(), tail_bytes=0, producer_exit=0,
                    producer_factory=Producer):
        clock = Clock()
        emitter = CaptureEmitter()
        ids = list(range(1, count + 1))
        blocks = [struct.pack("<h", number) * 16000 for number in ids]
        if tail_bytes:
            blocks.append(struct.pack("<h", count + 1) * (tail_bytes // 2))
        producer = producer_factory(blocks, exit_code=producer_exit)
        self.last_producer = producer
        seen = []

        def transcribe(audio, **_kwargs):
            identifier = int(round(float(audio[0]) * 32768))
            seen.append((identifier, len(audio) * 2))
            clock.now += step_seconds
            if end_after == identifier:
                self.write_marker(**(end_changes or {}))
            if hasattr(producer, "after_transcribe"):
                producer.after_transcribe()
            segments = [] if identifier in silent_ids else [SimpleNamespace(text=f"utterance number {identifier}")]
            return segments, None

        model = SimpleNamespace(transcribe=transcribe)
        with mock.patch.dict(os.environ, self.environment, clear=True):
            config = replace(config_from_args(args()), **(overrides or {}))
            with (
                mock.patch.object(take, "time", SimpleNamespace(monotonic=clock.monotonic, time=wall_time.time)),
                mock.patch.object(take, "load_whisper_model", return_value=model),
                mock.patch.object(take, "run_audio_preflight", return_value=None),
                mock.patch.object(take.subprocess, "Popen", return_value=producer),
                mock.patch.object(take, "_read_available_audio", side_effect=producer.read),
                mock.patch.object(take, "TranscriptEmitter", return_value=emitter),
            ):
                code = take.run_transcription(config)
        return code, emitter, seen, clock.now - 100

    def assert_incomplete(self, result, code, reason):
        actual, emitter, _, _ = result
        self.assertEqual(actual, code)
        if emitter.sequence:
            self.assertFalse(emitter.terminal["success_eligible"])
            self.assertEqual(emitter.terminal["termination_reason"], reason)

    def test_live_default_survives_old_one_hour_limit_then_drains_tail(self):
        result = self.run_capture(count=10, step_seconds=600, end_after=9, tail_bytes=8000)
        code, emitter, seen, elapsed = result
        self.assertEqual(code, 0)
        self.assertGreater(elapsed, 3900)
        self.assertEqual([identifier for identifier, _ in seen], list(range(1, 12)))
        self.assertEqual(seen[-1], (11, 8000))
        self.assertEqual(emitter.terminal["termination_reason"], "event_ended")
        self.assertTrue(emitter.terminal["success_eligible"])

    def test_live_eof_after_real_text_without_end_is_incomplete(self):
        self.assert_incomplete(self.run_capture(), take.STT_EXIT_LIVE_INCOMPLETE, "live_input_ended_without_event_end")

    def test_explicit_end_drains_already_queued_audio_past_session_guard(self):
        code, emitter, seen, _ = self.run_capture(count=4, step_seconds=100, end_after=1,
                                                  tail_bytes=4000, overrides={"max_session_seconds": 150})
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 5)
        self.assertEqual(emitter.terminal["termination_reason"], "event_ended")

    def test_session_guard_is_incomplete_even_with_good_earlier_text(self):
        self.assert_incomplete(self.run_capture(count=5, step_seconds=100, overrides={"max_session_seconds": 150}),
                               take.STT_EXIT_LIVE_GUARD, "live_session_guard")

    def test_chunk_limit_is_incomplete_for_live(self):
        self.assert_incomplete(self.run_capture(overrides={"max_chunks": 1}),
                               take.STT_EXIT_LIVE_GUARD, "live_chunk_limit")

    def test_silence_after_speech_is_incomplete_not_natural_end(self):
        # Two distinct adjacent audio windows establish speech continuity;
        # one possible waiting-music hallucination must not activate this guard.
        with mock.patch.object(take, "emit_live_event") as events:
            result = self.run_capture(count=5, step_seconds=400, silent_ids={3, 4, 5})
        self.assert_incomplete(result, take.STT_EXIT_LIVE_GUARD, "live_speech_idle_timeout")
        self.assertEqual(result[1].texts, ["utterance number 1", "utterance number 2"])
        windows = [call.kwargs for call in events.call_args_list if call.args[1] == "window_processed"]
        self.assertFalse(windows[0]["speech_seen"])
        self.assertTrue(windows[1]["speech_seen"])
        self.assertEqual(windows[1]["speech_evidence_reason"], "speech_continuity")
        self.assertGreaterEqual(windows[-1]["last_speech_age_seconds"], 600)

    def test_initial_speech_wait_does_not_use_after_speech_600_second_limit(self):
        code, emitter, seen, _ = self.run_capture(count=6, step_seconds=200, silent_ids={1, 2, 3, 4}, end_after=5)
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 6)
        self.assertTrue(emitter.texts[0].endswith("5"))

    def test_initial_speech_guard_never_completes_without_text(self):
        result = self.run_capture(count=5, step_seconds=200, silent_ids={1, 2, 3, 4, 5},
                                  overrides={"initial_speech_timeout_seconds": 300})
        self.assertEqual(result[0], take.STT_EXIT_LIVE_GUARD)
        self.assertIsNone(result[1].terminal)

    def test_source_lost_marker_preserves_tail_but_is_incomplete(self):
        result = self.run_capture(end_after=1, end_changes={"reason": "source_lost", "target_identity_verified": False}, tail_bytes=4000)
        self.assert_incomplete(result, take.STT_EXIT_LIVE_SOURCE_LOST, "live_source_lost")
        self.assertEqual(result[2][-1], (4, 4000))

    def test_stale_foreign_and_empty_markers_cannot_complete(self):
        cases = [
            {"call_id": "OTHER"}, {"capture_session_id": "previous-session"},
            {"run_id": "previous-run"}, {"created_at": self.started - 120},
            {"created_at": wall_time.time() + 120}, {"event_identity": {}},
            {"target_identity_verified": False}, {"evidence": ""},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.write_marker(**changes)
                self.assert_incomplete(self.run_capture(), take.STT_EXIT_LIVE_INCOMPLETE,
                                       "live_input_ended_without_event_end")
        self.marker.write_text("")
        self.assert_incomplete(self.run_capture(), take.STT_EXIT_LIVE_INCOMPLETE, "live_input_ended_without_event_end")

    def test_fresh_end_before_stt_start_is_accepted_for_this_run(self):
        self.write_marker(created_at=self.started + 1)
        self.assertEqual(self.run_capture()[0], 0)

    def test_supervisor_stop_code_is_expected_only_with_verified_end(self):
        result = self.run_capture(end_after=1, producer_exit=130)
        self.assertEqual(result[0], 0)
        self.assertTrue(result[1].terminal["success_eligible"])
        self.marker.unlink()
        result = self.run_capture(producer_exit=130)
        self.assert_incomplete(result, take.STT_EXIT_LIVE_INCOMPLETE, "live_input_ended_without_event_end")

    def test_unverified_target_cannot_complete_even_with_end_signal(self):
        result = self.run_capture(end_after=1, overrides={"target_identity_verified": False})
        self.assert_incomplete(result, take.STT_EXIT_TARGET_UNVERIFIED, "target_identity_unverified")

    def test_replay_bounded_capture_remains_supported(self):
        result = self.run_capture(overrides={"live_capture": False, "supervised_live": False, "max_chunks": 1})
        self.assertEqual(result[0], 0)
        self.assertEqual(result[1].terminal["termination_reason"], "bounded_capture_complete")

    def test_direct_live_input_is_stopped_once_then_last_pcm_is_drained(self):
        code, emitter, seen, _ = self.run_capture(
            count=3, tail_bytes=8000, end_after=1,
            producer_factory=StopThenTailProducer, producer_exit=255,
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.last_producer.terminate_calls, 1)
        self.assertEqual(seen, [(1, 32000), (2, 32000), (3, 32000), (4, 8000)])
        self.assertEqual(emitter.terminal["termination_reason"], "event_ended")

    def test_direct_source_loss_stops_once_and_preserves_tail_without_completion(self):
        result = self.run_capture(
            count=2, tail_bytes=4000, end_after=1,
            end_changes={"reason": "source_lost", "target_identity_verified": False},
            producer_factory=StopThenTailProducer, producer_exit=255,
        )
        self.assert_incomplete(result, take.STT_EXIT_LIVE_SOURCE_LOST, "live_source_lost")
        self.assertEqual(self.last_producer.terminate_calls, 1)
        self.assertEqual(result[2][-1], (3, 4000))

    def test_unstoppable_direct_input_has_bounded_incomplete_drain(self):
        result = self.run_capture(
            end_after=1, step_seconds=10, producer_factory=NeverStoppingProducer,
            overrides={"live_drain_timeout_seconds": 25},
        )
        self.assert_incomplete(result, take.STT_EXIT_LIVE_GUARD, "live_drain_timeout")
        self.assertEqual(self.last_producer.terminate_calls, 1)
        self.assertLessEqual(result[3], 50)
        self.assertEqual(self.last_producer.returncode, -9)

    def test_stopped_spool_backlog_outlives_stop_deadline_without_killing_follower(self):
        spool = Path(self.directory.name) / "recorded.pcm"
        spool.write_bytes(b"\0" * (6 * 32000))
        Path(str(spool) + ".done").write_text(json.dumps({"exit_code": 130, "bytes": spool.stat().st_size}))
        self.environment["STT_PCM_HANDOFF_FILE"] = str(spool)
        code, emitter, seen, elapsed = self.run_capture(
            count=6, step_seconds=10, end_after=1, producer_factory=BackloggedFollower,
            producer_exit=130, overrides={"live_drain_timeout_seconds": 25},
        )
        self.assertEqual(code, 0)
        self.assertGreater(elapsed, 25)
        self.assertEqual(len(seen), 6)
        self.assertEqual(self.last_producer.terminate_calls, 0)
        self.assertEqual(emitter.terminal["termination_reason"], "event_ended")


if __name__ == "__main__":
    unittest.main()
