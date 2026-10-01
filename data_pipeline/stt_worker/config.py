"""STT config: independent of Whisper model loading."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from ..config import load_project_env


load_project_env()

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
    overlap_bytes: int
    reads_per_emit: int
    max_chunks: int | None
    max_session_seconds: int | None
    no_chunk_timeout_seconds: float
    no_text_timeout_seconds: int | None
    ai_engine_url: str
    backend_url: str
    internal_secret: str
    send_to_ai_engine: bool
    send_to_backend: bool
    archive_transcripts: bool
    http_timeout_seconds: float
    resolve_media_url: bool
    preflight_audio_file: str | None
    preflight_report_file: str | None
    preflight_required: bool
    preflight_keep_audio: bool
    target_identity_verified: bool
    live_capture: bool = False
    supervised_live: bool = False
    initial_speech_timeout_seconds: int | None = 3600
    live_termination_file: str | None = None
    capture_session_id: str = ""
    live_run_id: str = ""
    live_run_started_at: float = 0.0
    target_event_date: str = ""
    live_drain_timeout_seconds: float = 30.0


def _default_call_id(ticker: str) -> str:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{ticker}-{suffix}"


def _default_ffmpeg_bin() -> str:
    env_value = os.getenv("FFMPEG_BIN")
    if env_value:
        return env_value
    sibling = Path(sys.executable).with_name("ffmpeg")
    if sibling.exists() and _ffmpeg_supports_pulse(sibling):
        return str(sibling)
    system = Path("/usr/bin/ffmpeg")
    if system.exists() and _ffmpeg_supports_pulse(system):
        return str(system)
    if sibling.exists():
        return str(sibling)
    return "ffmpeg"


def _ffmpeg_supports_pulse(path: Path) -> bool:
    try:
        result = subprocess.run(
            [str(path), "-hide_banner", "-muxers"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "pulse" in f"{result.stdout}\n{result.stderr}".lower()


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
    parser.add_argument("--read-bytes", type=int, default=_int_env("STT_READ_BYTES", 640000))
    parser.add_argument(
        "--overlap-bytes",
        type=int,
        default=_int_env("STT_OVERLAP_BYTES", 64000),
    )
    parser.add_argument("--reads-per-emit", type=int, default=_int_env("STT_READS_PER_EMIT", 1))
    parser.add_argument("--max-chunks", type=int, default=_int_env("STT_MAX_CHUNKS", 0) or None)
    parser.add_argument(
        "--max-session-seconds",
        type=int,
        default=_int_env("STT_MAX_SESSION_SECONDS", _default_session_seconds()) or None,
    )
    parser.add_argument(
        "--no-chunk-timeout-seconds",
        type=float,
        default=_float_env("STT_NO_CHUNK_TIMEOUT_SECONDS", 45),
    )
    parser.add_argument(
        "--no-text-timeout-seconds",
        type=int,
        default=_int_env("STT_NO_TEXT_TIMEOUT_SECONDS", 600) or None,
    )
    parser.add_argument(
        "--initial-speech-timeout-seconds",
        type=int,
        default=_int_env("STT_INITIAL_SPEECH_TIMEOUT_SECONDS", 3600) or None,
        help="Live waiting-room allowance before the first speech; never marks a call complete.",
    )
    parser.add_argument(
        "--live-drain-timeout-seconds",
        type=float,
        default=_float_env("STT_LIVE_DRAIN_TIMEOUT_SECONDS", 30.0),
        help="Time allowed for a supervised live input to stop after its terminal signal.",
    )
    parser.add_argument(
        "--preflight-audio-file",
        default=os.getenv("STT_AUDIO_PREFLIGHT_FILE", ""),
        help="Short mono PCM WAV captured before live STT.",
    )
    parser.add_argument(
        "--preflight-report-file",
        default=os.getenv("STT_AUDIO_PREFLIGHT_REPORT_FILE", ""),
        help="JSON evidence path for the short audio preflight.",
    )
    parser.add_argument(
        "--require-preflight-speech",
        action="store_true",
        help="Stop before live STT unless the preflight sample contains speech.",
    )
    parser.add_argument(
        "--keep-preflight-audio",
        action="store_true",
        help="Keep the temporary preflight WAV for a manual diagnostic only.",
    )
    parser.add_argument(
        "--audio-preflight-only",
        action="store_true",
        help="Classify the short preflight WAV without opening the live input.",
    )
    parser.add_argument("--print-ffmpeg-command", action="store_true")
    parser.add_argument("--no-ai-engine", action="store_true")
    parser.add_argument("--no-backend", action="store_true")
    parser.add_argument("--no-transcript-archive", action="store_true")
    return parser.parse_args(argv)


def _default_session_seconds() -> int:
    return 14400 if os.getenv("WEBCAST_LIFECYCLE", "").strip().lower() == "live" else 3900


def config_from_args(args: argparse.Namespace) -> SttConfig:
    ticker = args.ticker.strip().upper()
    input_source = args.input_source
    if not input_source:
        if args.input_kind == "device":
            input_source = os.getenv("STT_INPUT_DEVICE", "default")
        else:
            raise ValueError(f"--input-source is required for input kind: {args.input_kind}")

    read_bytes = max(32000, args.read_bytes)
    overlap_bytes = max(
        0,
        min(
            read_bytes - 32000,
            int(getattr(args, "overlap_bytes", _int_env("STT_OVERLAP_BYTES", 64000))),
        ),
    )
    lifecycle = os.getenv("WEBCAST_LIFECYCLE", "unknown").strip().lower()
    require_live_identity = _bool_env("WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION", True)
    live_identity_verified = _bool_env("WEBCAST_LIVE_ENTRYPOINT_VERIFIED", False)
    target_identity_default = (
        lifecycle != "live"
        or not require_live_identity
        or live_identity_verified
    )

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
        read_bytes=read_bytes,
        overlap_bytes=overlap_bytes,
        reads_per_emit=max(1, args.reads_per_emit),
        max_chunks=args.max_chunks,
        max_session_seconds=(
            max(0, int(getattr(args, "max_session_seconds", _int_env("STT_MAX_SESSION_SECONDS", _default_session_seconds())) or 0))
            or None
        ),
        no_chunk_timeout_seconds=max(
            1.0,
            float(
                getattr(
                    args,
                    "no_chunk_timeout_seconds",
                    _float_env("STT_NO_CHUNK_TIMEOUT_SECONDS", 45),
                )
            ),
        ),
        no_text_timeout_seconds=(
            max(0, int(getattr(args, "no_text_timeout_seconds", _int_env("STT_NO_TEXT_TIMEOUT_SECONDS", 600)) or 0))
            or None
        ),
        ai_engine_url=os.getenv("AI_ENGINE_URL", "http://localhost:8000").rstrip("/"),
        backend_url=os.getenv("BACKEND_URL", "http://localhost:8082").rstrip("/"),
        internal_secret=os.getenv("INTERNAL_SECRET", os.getenv("BACKEND_INTERNAL_SECRET", "")).strip(),
        send_to_ai_engine=_bool_env("SEND_TO_AI_ENGINE", True) and not args.no_ai_engine,
        send_to_backend=_bool_env("SEND_TO_BACKEND", True) and not args.no_backend,
        archive_transcripts=_bool_env("TRANSCRIPT_ARCHIVE_ENABLED", True)
        and not getattr(args, "no_transcript_archive", False),
        http_timeout_seconds=_float_env("STT_HTTP_TIMEOUT_SECONDS", 10),
        resolve_media_url=_bool_env("STT_RESOLVE_MEDIA_URL", True),
        preflight_audio_file=str(
            getattr(args, "preflight_audio_file", "") or ""
        ).strip() or None,
        preflight_report_file=str(
            getattr(args, "preflight_report_file", "") or ""
        ).strip() or None,
        preflight_required=(
            bool(getattr(args, "require_preflight_speech", False))
            or _bool_env("STT_AUDIO_PREFLIGHT_REQUIRED", False)
        ),
        preflight_keep_audio=(
            bool(getattr(args, "keep_preflight_audio", False))
            or _bool_env("STT_AUDIO_PREFLIGHT_KEEP", False)
        ),
        target_identity_verified=_bool_env(
            "STT_TARGET_IDENTITY_VERIFIED",
            target_identity_default,
        ),
        live_capture=lifecycle == "live",
        supervised_live=lifecycle == "live" and _bool_env("WEBCAST_SUPERVISED_LIVE", False),
        initial_speech_timeout_seconds=(
            max(0, int(getattr(args, "initial_speech_timeout_seconds", _int_env("STT_INITIAL_SPEECH_TIMEOUT_SECONDS", 3600)) or 0))
            or None
        ),
        live_termination_file=os.getenv("WEBCAST_LIVE_TERMINATION_FILE", "").strip() or None,
        capture_session_id=os.getenv("STT_CAPTURE_SESSION_ID", "").strip(),
        live_run_id=os.getenv("WEBCAST_LIVE_RUN_ID", "").strip(),
        live_run_started_at=_float_env("WEBCAST_LIVE_RUN_STARTED_AT", 0.0),
        target_event_date=os.getenv("WEBCAST_TARGET_DATE", "").strip(),
        live_drain_timeout_seconds=max(1.0, float(getattr(args, "live_drain_timeout_seconds", _float_env("STT_LIVE_DRAIN_TIMEOUT_SECONDS", 30.0)))),
    )
