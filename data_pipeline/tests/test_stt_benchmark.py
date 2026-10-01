from pathlib import Path
from contextlib import redirect_stdout
import io
import json
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline.tools.debug.benchmark_stt import (
    BenchmarkTranscriptSink, MetricsCapture, benchmark_worker_runtime,
    paced_file_command, resolve_local_model,
    main,
)


class SttBenchmarkTest(unittest.TestCase):
    def test_paces_input_and_preserves_worker_output_conversion(self):
        source = ["ffmpeg", "-i", "speech.wav", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]
        paced = paced_file_command(source, 120)
        self.assertEqual(paced[paced.index("-i") - 1], "-re")
        self.assertEqual(paced[-3:], ["-t", "120", "pipe:1"])
        self.assertNotIn("-re", source)

    def test_worker_runtime_always_restores_original_dependencies(self):
        original_command = lambda config: ["ffmpeg", "-i", "speech.wav", "pipe:1"]
        original_emitter = object()
        worker = SimpleNamespace(build_ffmpeg_command=original_command, TranscriptEmitter=original_emitter)
        sink = BenchmarkTranscriptSink()
        with self.assertRaises(RuntimeError):
            with benchmark_worker_runtime(worker, sink, 20):
                self.assertIs(worker.TranscriptEmitter(None), sink)
                self.assertIn("-re", worker.build_ffmpeg_command(None))
                raise RuntimeError("interrupted")
        self.assertIs(worker.build_ffmpeg_command, original_command)
        self.assertIs(worker.TranscriptEmitter, original_emitter)

    def test_metrics_capture_does_not_retain_transcript_and_handles_split_writes(self):
        capture = MetricsCapture()
        capture.write("\r[transcribing] confidential sample " * 10000)
        self.assertLessEqual(len(capture.pending), 16384)
        capture.write('\n[BENCHMARK] STT_PERFORMANCE {"realtime_')
        capture.write('factor":0.5,"dropped_bytes":0}\n')
        self.assertEqual(capture.metrics, {"realtime_factor": 0.5, "dropped_bytes": 0})
        self.assertEqual(capture.pending, "")

    def test_local_sink_only_retains_counters(self):
        sink = BenchmarkTranscriptSink()
        sink.emit_chunk(None, "example earnings statement", is_final=False)
        self.assertEqual(sink.sequence, 1)
        self.assertEqual(sink.text_characters, 26)
        self.assertTrue(sink.finish_session(success_eligible=True))
        self.assertNotIn("example earnings statement", repr(vars(sink)))

    def test_explicit_model_directory_requires_model_binary(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                resolve_local_model(directory)
            (Path(directory) / "model.bin").write_bytes(b"test only")
            self.assertEqual(resolve_local_model(directory), str(Path(directory).resolve()))

    def test_cli_disables_chunk_limit_and_production_delivery(self):
        from data_pipeline.stt_worker import take

        def run(config):
            self.assertIsNone(config.max_chunks)
            self.assertIsNone(config.max_session_seconds)
            self.assertFalse(config.send_to_backend)
            self.assertFalse(config.send_to_ai_engine)
            self.assertFalse(config.archive_transcripts)
            self.assertEqual(config.input_kind, "file")
            sink = take.TranscriptEmitter(config)
            sink.emit_chunk(None, "test earnings statement")
            sink.finish_session(success_eligible=True)
            print('[BENCHMARK] STT_PERFORMANCE {"realtime_factor": 0.5, "dropped_bytes": 0}')
            return 0

        with TemporaryDirectory() as directory:
            audio = Path(directory) / "speech.wav"
            audio.write_bytes(b"the inference function is isolated in this CLI wiring test")
            output = io.StringIO()
            with mock.patch("data_pipeline.tools.debug.benchmark_stt.resolve_local_model", return_value="/local/model"), \
                    mock.patch.object(take, "run_transcription", side_effect=run), redirect_stdout(output):
                result = main(["--audio-file", str(audio)])
            self.assertEqual(result, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["transcript_segments"], 1)
            self.assertFalse(report["production_delivery_exercised"])


if __name__ == "__main__":
    unittest.main()
