from __future__ import annotations

from dataclasses import replace
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.stt_worker.speech_evidence import SpeechEvidenceTracker, segment_evidence_payload


def segment(text, **metadata):
    return SimpleNamespace(text=text, **metadata)


class MetadataModel:
    def transcribe(self, *args, **kwargs):
        return [segment("Hello.", no_speech_prob=.03, avg_logprob=-.1, compression_ratio=1.2)], None


def metadata_model_worker(connection, config):
    from data_pipeline.stt_worker.model_supervisor import _model_process
    with mock.patch("data_pipeline.stt_worker.take._load_whisper_model_direct", return_value=MetadataModel()):
        _model_process(connection, config)


class SpeechEvidenceTest(unittest.TestCase):
    def test_single_waiting_music_hallucination_does_not_confirm_first_speech(self):
        tracker = SpeechEvidenceTracker()
        first = tracker.observe([segment("Thank you.")], audio_seconds=20)
        self.assertFalse(first.confirmed)
        self.assertEqual(first.reason, "awaiting_continuity")
        for seconds in (38, 56, 74):
            evidence = tracker.observe([], audio_seconds=seconds)
            self.assertFalse(evidence.confirmed)
            self.assertFalse(evidence.credible_window)

    def test_explicit_non_speech_never_activates_shorter_idle_guard(self):
        tracker = SpeechEvidenceTracker()
        for index, text in enumerate(("[Music]", "(music)", "[applause]", "[silence]", "BORNAN BOR.")):
            with self.subTest(text=text):
                result = tracker.observe([segment(text)], audio_seconds=20 + index * 18)
                self.assertFalse(result.confirmed)
                self.assertEqual(result.reason, "explicit_non_speech")

    def test_repeated_model_text_does_not_supply_continuity(self):
        tracker = SpeechEvidenceTracker()
        for index in range(8):
            result = tracker.observe([segment("Thank you!")], audio_seconds=20 + index * 18)
            self.assertFalse(result.confirmed)
        self.assertEqual(result.reason, "repeated_window")

    def test_model_no_speech_and_repetition_metadata_remain_uncertain(self):
        tracker = SpeechEvidenceTracker()
        first = tracker.observe([segment("Welcome everyone.", no_speech_prob=.95)], audio_seconds=20)
        second = tracker.observe([segment("Our results follow.", compression_ratio=4.1)], audio_seconds=38)
        self.assertEqual(first.reason, "model_no_speech")
        self.assertEqual(second.reason, "model_repetition")
        self.assertFalse(second.confirmed)

    def test_different_adjacent_speech_windows_confirm_without_length_filter(self):
        tracker = SpeechEvidenceTracker()
        self.assertFalse(tracker.observe([segment("Hello.")], audio_seconds=20).confirmed)
        confirmed = tracker.observe([segment("Good morning.")], audio_seconds=38)
        self.assertTrue(confirmed.confirmed)
        self.assertTrue(confirmed.credible_window)
        self.assertTrue(tracker.observe([segment("Yes.")], audio_seconds=56).credible_window)

    def test_silence_and_distant_windows_reset_pending_continuity(self):
        tracker = SpeechEvidenceTracker()
        tracker.observe([segment("Welcome.")], audio_seconds=20)
        tracker.observe([], audio_seconds=38)
        self.assertFalse(tracker.observe([segment("Thank you.")], audio_seconds=56).confirmed)
        self.assertFalse(tracker.observe([segment("Good afternoon.")], audio_seconds=140).confirmed)
        self.assertTrue(tracker.observe([segment("We will begin.")], audio_seconds=158).confirmed)

    def test_confirmed_speech_is_not_revoked_by_music_but_music_is_not_progress(self):
        tracker = SpeechEvidenceTracker()
        tracker.observe([segment("Welcome.")], audio_seconds=20)
        tracker.observe([segment("Our earnings increased.")], audio_seconds=38)
        result = tracker.observe([segment("[Music]")], audio_seconds=56)
        self.assertTrue(result.confirmed)
        self.assertFalse(result.credible_window)

    def test_good_segment_still_counts_beside_uncertain_segment(self):
        tracker = SpeechEvidenceTracker()
        tracker.observe([segment("[Music]"), segment("Hello.")], audio_seconds=20)
        result = tracker.observe([segment("Please continue.", no_speech_prob=.02)], audio_seconds=38)
        self.assertTrue(result.confirmed)

    def test_optional_metadata_is_finite_and_plain_text_is_preserved(self):
        payload = segment_evidence_payload(segment(" Yes. ", no_speech_prob=.02,
                    avg_logprob=-.1, compression_ratio=float("nan")))
        self.assertEqual(payload, {"text": " Yes. ", "no_speech_prob": .02, "avg_logprob": -.1})
        self.assertEqual(segment_evidence_payload(segment("No.")), {"text": "No."})


class SpeechEvidenceIntegrationTest(unittest.TestCase):
    def run_windows(self, windows, *, no_text_timeout=600):
        from data_pipeline.stt_worker import take
        from data_pipeline.stt_worker.config import _parse_args, config_from_args
        config = replace(config_from_args(_parse_args(["--ticker", "CCL", "--call-id", "speech-test"])),
            live_capture=True, supervised_live=False, target_identity_verified=True,
            read_bytes=32000, overlap_bytes=0, reads_per_emit=1, max_chunks=None,
            max_session_seconds=None, initial_speech_timeout_seconds=3600,
            no_text_timeout_seconds=no_text_timeout, send_to_backend=False, send_to_ai_engine=False)
        model = SimpleNamespace(transcribe=mock.Mock(side_effect=[(items, None) for items in windows]))
        process = SimpleNamespace(stdout=None, stderr=None, returncode=0, poll=lambda: 0, wait=lambda **kw: 0)
        emitter = SimpleNamespace(sequence=0, emit_chunk=None, finish_session=lambda **kw: True)
        texts = []
        def emit(client, text, **kwargs):
            texts.append(text)
            emitter.sequence += 1
            return True
        emitter.emit_chunk = emit
        def read(process, audio_queue, state, **kwargs):
            for _ in windows:
                audio_queue.put(b"\0" * 32000)
                state.bytes_read += 32000
            state.finished.set()
        with (mock.patch.object(take, "load_whisper_model", return_value=model),
              mock.patch.object(take.subprocess, "Popen", return_value=process),
              mock.patch.object(take, "_read_audio_continuously", side_effect=read),
              mock.patch.object(take, "TranscriptEmitter", return_value=emitter),
              mock.patch.object(take, "emit_live_event") as events,
              mock.patch.dict(os.environ, {"STT_PCM_HANDOFF_FILE": ""})):
            code = take.run_transcription(config)
        return texts, [call.kwargs for call in events.call_args_list if call.args[1] == "window_processed"], code

    def test_music_hallucination_is_archived_but_does_not_shorten_initial_wait(self):
        from data_pipeline.stt_worker.take import STT_EXIT_LIVE_INCOMPLETE
        texts, events, code = self.run_windows([[segment("Thank you.")], [], []], no_text_timeout=.000001)
        self.assertEqual(len(events), 3)  # old logic stops after the hallucinated first window
        self.assertEqual([text.strip() for text in texts], ["Thank you."])
        self.assertTrue(all(not event["speech_seen"] for event in events))
        self.assertEqual(code, STT_EXIT_LIVE_INCOMPLETE)

    def test_short_real_speech_and_closing_are_preserved(self):
        from data_pipeline.live_end import explicit_operator_close
        closing = "This concludes our conference call. You may now disconnect."
        texts, events, _ = self.run_windows([[segment("Hello.")], [segment("Yes.")], [segment(closing)]])
        self.assertEqual([text.strip() for text in texts], ["Hello.", "Yes.", closing])
        self.assertFalse(events[0]["speech_seen"])
        self.assertTrue(events[1]["speech_seen"])
        self.assertTrue(explicit_operator_close(texts[-1]))

    def test_model_process_preserves_metadata_on_its_pipe(self):
        from data_pipeline.stt_worker import model_supervisor
        model = SimpleNamespace(transcribe=lambda *a, **kw: ([segment("Hello.", no_speech_prob=.04,
                               avg_logprob=-.2, compression_ratio=1.1)], None))
        pipe = mock.Mock()
        pipe.recv.side_effect = [("transcribe", [0], {}), ("close",)]
        with mock.patch("data_pipeline.stt_worker.take._load_whisper_model_direct", return_value=model):
            model_supervisor._model_process(pipe, SimpleNamespace())
        pipe.send.assert_any_call(("result", [{"text": "Hello.", "no_speech_prob": .04,
                                               "avg_logprob": -.2, "compression_ratio": 1.1}]))

    def test_metadata_survives_real_isolated_model_pipe_without_loading_model(self):
        from data_pipeline.stt_worker.model_supervisor import SupervisedWhisperModel
        config = SimpleNamespace(capture_session_id="speech-metadata-test", max_session_seconds=None)
        model = SupervisedWhisperModel(config, worker_target=metadata_model_worker,
                                       load_timeout=5, inference_timeout=2, max_restarts=0)
        try:
            segments, _ = model.transcribe([0, 0], vad_filter=True)
            self.assertEqual(segment_evidence_payload(segments[0]), {
                "text": "Hello.", "no_speech_prob": .03, "avg_logprob": -.1, "compression_ratio": 1.2})
        finally:
            model.close()

    def test_supervisor_returns_segment_metadata_and_supports_legacy_text(self):
        from data_pipeline.stt_worker.model_supervisor import SupervisedWhisperModel
        supervisor = SupervisedWhisperModel.__new__(SupervisedWhisperModel)
        supervisor.connection = mock.Mock()
        supervisor.inference_timeout = 90
        supervisor.restarts = 0
        values = [{"text": "Hello.", "no_speech_prob": .03, "avg_logprob": -.1}, "legacy"]
        with mock.patch.object(supervisor, "_receive", return_value=("result", values)):
            segments, _ = supervisor.transcribe([0])
        self.assertEqual(segments[0].text, "Hello.")
        self.assertEqual(segments[0].no_speech_prob, .03)
        self.assertEqual(segments[1].text, "legacy")


if __name__ == "__main__":
    unittest.main()
