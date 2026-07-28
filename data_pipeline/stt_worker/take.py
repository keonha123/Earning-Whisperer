from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
from dotenv import load_dotenv
from faster_whisper import WhisperModel


load_dotenv()


InputKind = Literal["device", "file", "url"]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class SttConfig:
    ticker: str
    call_id: str
    input_kind: InputKind
    input_source: str
    input_format: str
    ffmpeg_bin: str
    model_name: str
    device: str
    compute_type: str
    cpu_threads: int
    beam_size: int
    language: str
    vad_filter: bool
    read_bytes: int
    reads_per_emit: int
    max_chunks: int | None
    ai_engine_url: str
    backend_url: str
    internal_secret: str
    send_to_ai_engine: bool
    send_to_backend: bool
    archive_transcripts: bool
    http_timeout_seconds: float
    resolve_media_url: bool


class TranscriptEmitter:
    def __init__(self, config: SttConfig) -> None:
        self.config = config
        self.sequence = 0
        self.session_started_monotonic = time.monotonic()
        self.last_emit_ms = 0
        self._archive_retry_after = 0.0
        self._archive_schema_ready = False

    def _post_json(
        self,
        client: httpx.Client,
        label: str,
        url: str,
        payload: dict,
        headers: dict | None = None,
    ) -> None:
        try:
            response = client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.config.http_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                print(f"[{label}] sent status={response.status_code}", flush=True)
                return
            print(
                f"[{label}] send failed status={response.status_code} body={response.text[:300]}",
                flush=True,
            )
        except httpx.RequestError as exc:
            print(f"[{label}] send error: {exc}", flush=True)

    def _build_transcript_payload(
        self,
        analysis_payload: dict,
        start_ms: int,
        end_ms: int,
    ) -> dict:
        return {
            "ticker": analysis_payload["ticker"],
            "call_id": self.config.call_id,
            "sequence": analysis_payload["sequence"],
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": analysis_payload["text_chunk"],
            "speaker": None,
            "timestamp": analysis_payload["timestamp"],
            "is_session_end": analysis_payload["is_final"],
        }

    def _archive_segment(self, payload: dict) -> None:
        """Archive text opportunistically; a DB outage must not stop live STT."""
        if not self.config.archive_transcripts or time.monotonic() < self._archive_retry_after:
            return
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if not self._archive_schema_ready:
                database.ensure_transcript_archive_schema()
                self._archive_schema_ready = True
            database.archive_transcript_segment(payload, ensure_schema=False)
        except Exception as exc:
            # Retry later instead of logging once per audio chunk during a DB outage.
            self._archive_retry_after = time.monotonic() + 30
            print(f"[Transcript Archive] unavailable; live delivery continues: {exc}", flush=True)

    def emit_chunk(self, client: httpx.Client, text: str, is_final: bool = False) -> None:
        clean_text = text.strip()
        if not clean_text:
            return

        now_ms = int((time.monotonic() - self.session_started_monotonic) * 1000)
        end_ms = max(now_ms, self.last_emit_ms)
        start_ms = self.last_emit_ms

        analysis_payload = {
            "ticker": self.config.ticker,
            "text_chunk": clean_text,
            "sequence": self.sequence,
            "timestamp": int(time.time()),
            "is_final": is_final,
        }

        print("\n" + "-" * 20 + " [SEND PAYLOAD] " + "-" * 20)
        print(json.dumps(analysis_payload, indent=4, ensure_ascii=False))
        print("-" * 55 + "\n", flush=True)

        if self.config.send_to_ai_engine:
            self._post_json(
                client,
                "AI Engine",
                f"{self.config.ai_engine_url}/api/v1/analyze",
                analysis_payload,
            )

        if self.config.send_to_backend:
            if not self.config.internal_secret:
                print("[Backend Transcript] INTERNAL_SECRET missing; skipped", flush=True)
            else:
                self._post_json(
                    client,
                    "Backend Transcript",
                    f"{self.config.backend_url}/api/v1/internal/transcript-segment",
                    self._build_transcript_payload(analysis_payload, start_ms, end_ms),
                    headers={"X-Internal-Secret": self.config.internal_secret},
                )

        self._archive_segment(self._build_transcript_payload(analysis_payload, start_ms, end_ms))

        self.sequence += 1
        self.last_emit_ms = end_ms


def _default_call_id(ticker: str) -> str:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{ticker}-{suffix}"


def _default_ffmpeg_bin() -> str:
    env_value = os.getenv("FFMPEG_BIN")
    if env_value:
        return env_value
    sibling = Path(sys.executable).with_name("ffmpeg")
    if sibling.exists():
        return str(sibling)
    return "ffmpeg"


def _resolve_youtube_or_media_url(source: str) -> str:
    if not source.startswith(("http://", "https://")):
        return source

    try:
        import yt_dlp
    except ImportError:
        return source

    options = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(source, download=False)
    if isinstance(info, dict) and info.get("url"):
        return str(info["url"])
    return source


def build_ffmpeg_command(config: SttConfig) -> list[str]:
    source = config.input_source
    if config.input_kind == "url" and config.resolve_media_url:
        source = _resolve_youtube_or_media_url(source)

    command = [config.ffmpeg_bin, "-hide_banner", "-loglevel", "warning"]
    if config.input_kind == "device":
        command.extend(["-f", config.input_format, "-i", source])
    elif config.input_kind in {"file", "url"}:
        command.extend(["-i", source])
    else:
        raise ValueError(f"Unsupported input kind: {config.input_kind}")

    command.extend(["-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"])
    return command


def ffmpeg_exit_is_expected(returncode: int | None, *, stopped_by_limit: bool) -> bool:
    if returncode in {0, None, -15}:
        return True
    # FFmpeg commonly reports 255 when its live PulseAudio input is terminated
    # after the requested number of transcript chunks has been collected.
    return stopped_by_limit and returncode == 255


def load_whisper_model(config: SttConfig) -> WhisperModel:
    """Serialize model initialization so concurrent workers do not race the HF cache."""
    lock_path = Path(
        os.getenv(
            "STT_MODEL_LOCK_PATH",
            "/tmp/earning-whisperer-whisper-model.lock",
        )
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_file:
        print(f"[{config.ticker}] waiting for STT model lock", flush=True)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            return WhisperModel(
                config.model_name,
                device=config.device,
                compute_type=config.compute_type,
                cpu_threads=config.cpu_threads,
            )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def run_transcription(config: SttConfig) -> int:
    print(f"[{config.ticker}] loading STT model: {config.model_name}", flush=True)
    model = load_whisper_model(config)

    command = build_ffmpeg_command(config)
    print(f"[{config.ticker}] ffmpeg input: {config.input_kind}:{config.input_source}", flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    emitter = TranscriptEmitter(config)
    accumulated_text = ""
    chunk_count = 0
    emitted_chunks = 0
    stopped_by_limit = False

    print(f"[{config.ticker}] STT worker started call_id={config.call_id}", flush=True)
    print(f"[{config.ticker}] AI Engine: {config.ai_engine_url}/api/v1/analyze", flush=True)
    print(
        f"[{config.ticker}] Backend Transcript: "
        f"{config.backend_url}/api/v1/internal/transcript-segment",
        flush=True,
    )

    try:
        with httpx.Client() as client:
            while True:
                if config.max_chunks is not None and emitted_chunks >= config.max_chunks:
                    stopped_by_limit = True
                    break

                if process.stdout is None:
                    raise RuntimeError("ffmpeg stdout pipe was not created")

                raw_audio = process.stdout.read(config.read_bytes)
                if not raw_audio:
                    break

                audio_data = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
                segments, _ = model.transcribe(
                    audio_data,
                    beam_size=config.beam_size,
                    language=config.language,
                    vad_filter=config.vad_filter,
                )

                for segment in segments:
                    text = segment.text.strip()
                    if text:
                        accumulated_text += " " + text
                        sys.stdout.write(f"\r[transcribing] {text}")
                        sys.stdout.flush()

                chunk_count += 1
                if chunk_count >= config.reads_per_emit and accumulated_text.strip():
                    emitter.emit_chunk(client, accumulated_text, is_final=False)
                    emitted_chunks += 1
                    accumulated_text = ""
                    chunk_count = 0

            if accumulated_text.strip():
                emitter.emit_chunk(client, accumulated_text, is_final=True)

    except KeyboardInterrupt:
        if accumulated_text.strip():
            with httpx.Client() as client:
                emitter.emit_chunk(client, accumulated_text, is_final=True)
        print("\nSTT worker interrupted", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    if not ffmpeg_exit_is_expected(
        process.returncode,
        stopped_by_limit=stopped_by_limit,
    ):
        stderr = b""
        if process.stderr is not None:
            stderr = process.stderr.read(4000)
        print(stderr.decode(errors="replace"), file=sys.stderr, flush=True)
        return int(process.returncode)

    print(f"\n[{config.ticker}] STT worker stopped", flush=True)
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Earning Whisperer STT worker.")
    parser.add_argument("--ticker", default=os.getenv("STT_TICKER", "FAST"))
    parser.add_argument("--call-id", default=os.getenv("STT_CALL_ID"))
    parser.add_argument(
        "--input-kind",
        choices=["device", "file", "url"],
        default=os.getenv("STT_INPUT_KIND", "device"),
    )
    parser.add_argument("--input-source", default=os.getenv("STT_INPUT_SOURCE"))
    parser.add_argument("--input-format", default=os.getenv("STT_INPUT_FORMAT", "alsa"))
    parser.add_argument("--ffmpeg-bin", default=_default_ffmpeg_bin())
    parser.add_argument("--model-name", default=os.getenv("STT_MODEL_NAME", "distil-large-v3"))
    parser.add_argument("--device", default=os.getenv("STT_DEVICE", "cpu"))
    parser.add_argument("--compute-type", default=os.getenv("STT_COMPUTE_TYPE", "int8"))
    parser.add_argument("--cpu-threads", type=int, default=_int_env("STT_CPU_THREADS", 8))
    parser.add_argument("--beam-size", type=int, default=_int_env("STT_BEAM_SIZE", 1))
    parser.add_argument("--language", default=os.getenv("STT_LANGUAGE", "en"))
    parser.add_argument("--read-bytes", type=int, default=_int_env("STT_READ_BYTES", 64000))
    parser.add_argument("--reads-per-emit", type=int, default=_int_env("STT_READS_PER_EMIT", 5))
    parser.add_argument("--max-chunks", type=int, default=_int_env("STT_MAX_CHUNKS", 0) or None)
    parser.add_argument("--print-ffmpeg-command", action="store_true")
    parser.add_argument("--no-ai-engine", action="store_true")
    parser.add_argument("--no-backend", action="store_true")
    parser.add_argument("--no-transcript-archive", action="store_true")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> SttConfig:
    ticker = args.ticker.strip().upper()
    input_source = args.input_source
    if not input_source:
        if args.input_kind == "device":
            input_source = os.getenv("STT_INPUT_DEVICE", "default")
        else:
            raise ValueError(f"--input-source is required for input kind: {args.input_kind}")

    return SttConfig(
        ticker=ticker,
        call_id=args.call_id or _default_call_id(ticker),
        input_kind=args.input_kind,
        input_source=input_source,
        input_format=args.input_format,
        ffmpeg_bin=args.ffmpeg_bin,
        model_name=args.model_name,
        device=args.device,
        compute_type=args.compute_type,
        cpu_threads=max(1, args.cpu_threads),
        beam_size=max(1, args.beam_size),
        language=args.language,
        vad_filter=_bool_env("STT_VAD_FILTER", True),
        read_bytes=max(32000, args.read_bytes),
        reads_per_emit=max(1, args.reads_per_emit),
        max_chunks=args.max_chunks,
        ai_engine_url=os.getenv("AI_ENGINE_URL", "http://localhost:8000").rstrip("/"),
        backend_url=os.getenv("BACKEND_URL", "http://localhost:8082").rstrip("/"),
        internal_secret=os.getenv("INTERNAL_SECRET", os.getenv("BACKEND_INTERNAL_SECRET", "")).strip(),
        send_to_ai_engine=_bool_env("SEND_TO_AI_ENGINE", True) and not args.no_ai_engine,
        send_to_backend=_bool_env("SEND_TO_BACKEND", True) and not args.no_backend,
        archive_transcripts=_bool_env("TRANSCRIPT_ARCHIVE_ENABLED", True)
        and not getattr(args, "no_transcript_archive", False),
        http_timeout_seconds=_float_env("STT_HTTP_TIMEOUT_SECONDS", 10),
        resolve_media_url=_bool_env("STT_RESOLVE_MEDIA_URL", True),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = config_from_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.print_ffmpeg_command:
        print(json.dumps(build_ffmpeg_command(config), ensure_ascii=False))
        return 0
    return run_transcription(config)


if __name__ == "__main__":
    raise SystemExit(main())
