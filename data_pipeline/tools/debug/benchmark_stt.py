"""Measure the real STT worker using paced local audio and a local transcript sink.

Usage:
    python -m data_pipeline.tools.debug.benchmark_stt --audio-file speech.wav \
        --model /models/distil-large-v3 --duration-seconds 180 --output metrics.json

An existing model cache is required: this command never downloads a model. The
input is played at wall-clock speed with FFmpeg -re, including during model load.
The production audio queue/transcription loop runs unchanged. Only its FFmpeg
command and delivery sink are replaced for this isolated benchmark process.
No registration, DB archive, AI API, or backend delivery is performed. Results
describe this machine and audio sample, not browser acquisition or AWS capacity.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any


class BenchmarkTranscriptSink:
    """A deliberately local destination; counters contain no transcript text."""

    def __init__(self, _config=None):
        self.sequence = 0
        self.text_characters = 0
        self.terminal: dict[str, Any] | None = None

    def emit_chunk(self, _client, value: str, *, is_final: bool = False):
        if value.strip():
            self.sequence += 1
            self.text_characters += len(value.strip())

    def finish_session(self, **terminal):
        self.terminal = terminal
        return True  # Accepted by the benchmark sink, not persisted to production.


class MetricsCapture(io.TextIOBase):
    """Read the worker's metrics line without retaining or printing speech text."""

    def __init__(self):
        self.pending = ""
        self.metrics: dict[str, Any] | None = None

    def write(self, value: str) -> int:
        self.pending += value
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if "STT_PERFORMANCE " in line:
                self.metrics = json.loads(line.split("STT_PERFORMANCE ", 1)[1])
        # Long sessions can emit many carriage-return transcript fragments.
        self.pending = self.pending[-16384:]
        return len(value)

    def flush(self):
        return None


def paced_file_command(command: list[str], duration_seconds: float) -> list[str]:
    """Pace the existing file input; preserve worker resampling/output settings."""
    result = list(command)
    input_index = result.index("-i")
    result.insert(input_index, "-re")
    if duration_seconds > 0:
        result[-1:-1] = ["-t", str(duration_seconds)]
    return result


def resolve_local_model(model: str, cache_dir: str | None = None) -> str:
    """Resolve aliases using only already downloaded CTranslate2 model files."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    candidate = Path(model).expanduser()
    if candidate.is_dir():
        if not (candidate / "model.bin").is_file():
            raise ValueError(f"Local model directory has no model.bin: {candidate}")
        return str(candidate.resolve())
    from faster_whisper.utils import download_model

    # The helper's name says download, but local_files_only prohibits fetching.
    return download_model(model, cache_dir=cache_dir, local_files_only=True)


@contextmanager
def benchmark_worker_runtime(worker, sink, duration_seconds: float):
    original_command = worker.build_ffmpeg_command
    original_emitter = worker.TranscriptEmitter
    worker.build_ffmpeg_command = lambda config: paced_file_command(original_command(config), duration_seconds)
    worker.TranscriptEmitter = lambda config: sink
    try:
        yield
    finally:
        worker.build_ffmpeg_command = original_command
        worker.TranscriptEmitter = original_emitter


def _resource_limit(name: str) -> str | None:
    try:
        return (Path("/sys/fs/cgroup") / name).read_text().strip()
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio-file", required=True, type=Path)
    parser.add_argument("--model", default=os.getenv("STT_MODEL_NAME", "distil-large-v3"))
    parser.add_argument("--model-cache-dir")
    parser.add_argument("--device", default=os.getenv("STT_DEVICE", "cpu"))
    parser.add_argument("--compute-type", default=os.getenv("STT_COMPUTE_TYPE", "int8"))
    parser.add_argument("--cpu-threads", type=int, default=int(os.getenv("STT_CPU_THREADS", "8")))
    parser.add_argument("--beam-size", type=int, default=int(os.getenv("STT_BEAM_SIZE", "1")))
    parser.add_argument("--duration-seconds", type=float, default=180)
    parser.add_argument("--read-bytes", type=int, default=int(os.getenv("STT_READ_BYTES", "640000")))
    parser.add_argument("--overlap-bytes", type=int, default=int(os.getenv("STT_OVERLAP_BYTES", "64000")))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.audio_file.is_file():
        parser.error("--audio-file must be an existing local audio file")
    if args.duration_seconds < 0:
        parser.error("--duration-seconds must be nonnegative; zero processes the complete file")
    report: dict[str, Any] = {
        "kind": "paced_local_audio_stt_benchmark",
        "model_requested": args.model,
        "local_models_only": True,
        "delivery_sink": "benchmark_memory",
        "production_delivery_exercised": False,
        "audio_file": str(args.audio_file.resolve()),
        "device": args.device,
        "compute_type": args.compute_type,
        "cpu_threads": max(1, args.cpu_threads),
        "duration_limit_seconds": args.duration_seconds,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "cgroup_cpu_max": _resource_limit("cpu.max"),
        "cgroup_memory_max": _resource_limit("memory.max"),
    }
    started = time.monotonic()
    exit_code = 2
    capture = MetricsCapture()
    sink = BenchmarkTranscriptSink()
    try:
        model_path = resolve_local_model(args.model, args.model_cache_dir)
        # Imports occur after offline mode is set. Keep worker settings such as
        # queue size/VAD, but explicitly disable all production destinations.
        from data_pipeline.stt_worker import take as worker

        config = worker.config_from_args(worker._parse_args([
            "--ticker", "BENCHMARK", "--call-id", "local-stt-benchmark",
            "--input-kind", "file", "--input-source", str(args.audio_file.resolve()),
            "--model-name", model_path, "--device", args.device,
            "--compute-type", args.compute_type, "--cpu-threads", str(args.cpu_threads),
            "--beam-size", str(args.beam_size), "--read-bytes", str(args.read_bytes),
            "--overlap-bytes", str(args.overlap_bytes), "--max-session-seconds", "0",
            "--max-chunks", "0", "--no-ai-engine", "--no-backend", "--no-transcript-archive",
        ]))
        config = replace(config, target_identity_verified=True, preflight_required=False, max_chunks=None,
                         preflight_audio_file="", preflight_report_file="")
        with benchmark_worker_runtime(worker, sink, args.duration_seconds), redirect_stdout(capture):
            exit_code = worker.run_transcription(config)
        report["worker_exit_code"] = exit_code
        report["performance"] = capture.metrics
        report["transcript_segments"] = sink.sequence
        report["transcript_characters"] = sink.text_characters
        report["terminal"] = sink.terminal
        report["metrics_complete"] = capture.metrics is not None
        if capture.metrics is None and exit_code == 0:
            exit_code = 2
        # RTF is an average compute measure. Do not infer sustained live service
        # quality from a short file; retain queue/drop/first-text metrics too.
        factor = (capture.metrics or {}).get("realtime_factor")
        report["average_compute_keeps_up"] = factor is not None and factor <= 1
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["metrics_complete"] = False
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["exit_code"] = exit_code
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
