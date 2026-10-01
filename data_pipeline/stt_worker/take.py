from __future__ import annotations

from data_pipeline.stt_worker.config import (
    InputKind,
    SttConfig,
    _bool_env,
    _default_call_id,
    _default_ffmpeg_bin,
    _ffmpeg_supports_pulse,
    _float_env,
    _int_env,
    _parse_args,
    config_from_args,
)
from data_pipeline.live_telemetry import emit_live_event
from data_pipeline.live_end import TranscriptEndObserver, publish_operator_end
from data_pipeline.stt_worker.model_supervisor import ModelStalled, SupervisedWhisperModel
from data_pipeline.stt_worker.audio_rescue import _write_private_json
from data_pipeline.stt_worker.speech_evidence import SpeechEvidenceTracker
from data_pipeline.stt_worker.delivery import (
    ArchiveSpoolReplay,
    TranscriptEmitter,
    retry_transcript_outbox_once,
)


import fcntl
import json
import math
import os
import queue
import re
import select
import subprocess
import sys
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from faster_whisper import WhisperModel


try:
    from ..config import load_project_env
except ImportError:
    from data_pipeline.config import load_project_env


load_project_env()


@dataclass(frozen=True)
class AudioPreflightResult:
    """Non-sensitive evidence from a short audio sample before live STT."""

    sample_path: str
    duration_seconds: float
    sample_rate: int
    sample_count: int
    rms_dbfs: float | None
    peak_dbfs: float | None
    audible_frame_ratio: float
    vad_segment_count: int
    vad_text_characters: int
    no_vad_segment_count: int
    no_vad_text_characters: int
    speech_detected: bool
    vad_suppressed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_path": self.sample_path,
            "duration_seconds": round(self.duration_seconds, 3),
            "sample_rate": self.sample_rate,
            "sample_count": self.sample_count,
            "rms_dbfs": self.rms_dbfs,
            "peak_dbfs": self.peak_dbfs,
            "audible_frame_ratio": round(self.audible_frame_ratio, 4),
            "vad_segment_count": self.vad_segment_count,
            "vad_text_characters": self.vad_text_characters,
            "no_vad_segment_count": self.no_vad_segment_count,
            "no_vad_text_characters": self.no_vad_text_characters,
            "speech_detected": self.speech_detected,
            "vad_suppressed": self.vad_suppressed,
        }


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
    handoff = os.getenv("STT_PCM_HANDOFF_FILE", "").strip()
    if config.input_kind == "device" and handoff:
        command = [sys.executable, "-m", "data_pipeline.stt_worker.pcm_handoff",
                   "--follow", handoff, "--idle-timeout", str(config.no_chunk_timeout_seconds)]
        if os.getenv("STT_PCM_HANDOFF_PID"):
            command.extend(["--producer-pid", os.environ["STT_PCM_HANDOFF_PID"]])
        return command
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


STT_EXIT_NO_CHUNKS = 70


STT_EXIT_NO_TEXT = 71


STT_EXIT_ARCHIVE_INCOMPLETE = 72


STT_EXIT_TARGET_UNVERIFIED = 73


STT_EXIT_AUDIO_BACKPRESSURE = 74


STT_EXIT_INTERRUPTED = 130


STT_EXIT_LIVE_INCOMPLETE = 76
STT_EXIT_LIVE_SOURCE_LOST = 77
STT_EXIT_LIVE_GUARD = 78
STT_EXIT_MODEL_STALLED = 79


def _read_live_termination(config: SttConfig) -> dict[str, object] | None:
    """Accept only a structured signal bound to this supervisor invocation.

    A marker can legitimately precede STT startup when a short call ends during
    promotion. Freshness therefore uses the shell run, not model startup time.
    """
    if (not config.live_capture or not config.supervised_live
            or not config.live_termination_file or not config.live_run_id
            or not math.isfinite(config.live_run_started_at) or config.live_run_started_at <= 0):
        return None
    try:
        path = Path(config.live_termination_file)
        stat = path.stat()
        if stat.st_size <= 0 or stat.st_size > 65536 or stat.st_mtime < config.live_run_started_at - 1:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None
        created_at = float(value.get("created_at", 0))
        if (value.get("version") != 1 or value.get("call_id") != config.call_id
                or value.get("capture_session_id") != (config.capture_session_id or config.call_id)
                or value.get("run_id") != config.live_run_id
                or not math.isfinite(created_at)
                or not config.live_run_started_at - 1 <= created_at <= time.time() + 5):
            return None
        if value.get("reason") == "source_lost":
            return value
        proof = value.get("event_identity")
        if (value.get("reason") != "event_ended" or value.get("target_identity_verified") is not True
                or not isinstance(proof, dict) or proof.get("verified") is not True
                or proof.get("call_ticker") != config.ticker
                or not str(value.get("url") or "").strip()
                or not str(value.get("evidence") or "").strip()
                or (config.target_event_date and proof.get("target_date") != config.target_event_date)):
            return None
        return value
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def _handoff_producer_finished(path_value: str) -> bool:
    """Distinguish a stopped spool producer from its still-draining consumer.

    The consumer can remain blocked by the preserved STT backlog long after
    recording stopped. Do not apply the producer-stop deadline to that backlog.
    """
    if not path_value:
        return False
    try:
        path = Path(path_value)
        done = json.loads(Path(path_value + ".done").read_text(encoding="utf-8"))
        return (isinstance(done, dict)
                and type(done.get("exit_code")) is int
                and type(done.get("bytes")) is int
                and done["bytes"] >= 0
                and done["bytes"] == path.stat().st_size)
    except (OSError, ValueError, TypeError):
        return False


def _read_available_audio(
    process: subprocess.Popen[bytes],
    max_bytes: int,
    timeout_seconds: float,
) -> bytes | None:
    """Read only data already available from ffmpeg, avoiding an indefinite pipe read."""
    if process.stdout is None:
        raise RuntimeError("ffmpeg stdout pipe was not created")
    readable, _, _ = select.select([process.stdout.fileno()], [], [], timeout_seconds)
    if not readable:
        return None
    return os.read(process.stdout.fileno(), max(1, max_bytes))


def _drain_stderr_tail(
    stream: object | None,
    chunks: deque[bytes],
) -> None:
    """Drain ffmpeg stderr continuously while retaining only a bounded tail."""
    if stream is None or not hasattr(stream, "read"):
        return
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            chunks.append(bytes(chunk))
    except (OSError, ValueError):
        return


@dataclass
class _AudioReaderState:
    finished: threading.Event
    stop_requested: threading.Event
    last_audio_at: float
    bytes_read: int = 0
    dropped_bytes: int = 0
    error: str | None = None


def _read_audio_continuously(
    process: subprocess.Popen[bytes],
    audio_queue: queue.Queue[bytes],
    state: _AudioReaderState,
    *,
    chunk_bytes: int,
    preserve_backlog: bool = False,
) -> None:
    """Drain FFmpeg independently so Whisper inference cannot block live input."""
    try:
        while not state.stop_requested.is_set():
            raw_audio = _read_available_audio(process, chunk_bytes, 0.5)
            if raw_audio is None:
                if process.poll() is not None:
                    break
                continue
            if not raw_audio:
                break
            state.last_audio_at = time.monotonic()
            state.bytes_read += len(raw_audio)
            if preserve_backlog:
                # This input is already safely spooled. Let the pipe apply
                # backpressure so cold model loading cannot discard its prefix.
                while not state.stop_requested.is_set():
                    try:
                        audio_queue.put(raw_audio, timeout=.1)
                        break
                    except queue.Full:
                        continue
                continue
            try:
                audio_queue.put_nowait(raw_audio)
            except queue.Full:
                try:
                    stale = audio_queue.get_nowait()
                    state.dropped_bytes += len(stale)
                except queue.Empty:
                    pass
                try:
                    audio_queue.put_nowait(raw_audio)
                except queue.Full:
                    state.dropped_bytes += len(raw_audio)
    except Exception as exc:
        state.error = f"{exc.__class__.__name__}: {exc}"[:400]
    finally:
        state.finished.set()


def _deduplicate_transcript_fragment(
    text: str,
    recent_words: list[str],
    *,
    max_overlap_words: int = 48,
) -> str:
    """Remove only an exact word overlap introduced by rolling audio windows."""
    words = text.strip().split()
    if not words:
        return ""

    def normalized(word: str) -> str:
        return re.sub(r"[^\w']+", "", word.casefold())

    previous = [normalized(word) for word in recent_words]
    current = [normalized(word) for word in words]
    overlap = 0
    for size in range(min(len(previous), len(current), max_overlap_words), 0, -1):
        if previous[-size:] == current[:size]:
            overlap = size
            break
    unique_words = words[overlap:]
    recent_words.extend(unique_words)
    del recent_words[:-max_overlap_words]
    return " ".join(unique_words)


def load_whisper_model(config: SttConfig) -> WhisperModel:
    if _bool_env("STT_ISOLATED_MODEL", False):
        return SupervisedWhisperModel(config)
    return _load_whisper_model_direct(config)


def _load_whisper_model_direct(config: SttConfig) -> WhisperModel:
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


def _dbfs(value: float) -> float | None:
    """Return a compact dBFS value without emitting raw audio samples."""
    if value <= 0:
        return None
    return round(float(20.0 * np.log10(value / 32768.0)), 2)


def _read_pcm16_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read the short supervisor-created mono PCM sample for preflight only."""
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())
    if channels != 1 or sample_width != 2:
        raise ValueError("preflight audio must be mono 16-bit PCM WAV")
    if sample_rate != 16_000:
        raise ValueError(f"preflight audio sample rate must be 16000Hz, got {sample_rate}")
    return np.frombuffer(frames, dtype=np.int16), sample_rate


def _preflight_transcript_stats(
    model: WhisperModel,
    audio_data: np.ndarray,
    config: SttConfig,
    *,
    vad_filter: bool,
) -> tuple[int, int]:
    """Compare VAD modes while retaining only counts, never preflight text."""
    segments, _ = model.transcribe(
        audio_data,
        beam_size=config.beam_size,
        language=config.language,
        vad_filter=vad_filter,
    )
    texts = [segment.text.strip() for segment in segments if segment.text.strip()]
    return len(texts), sum(len(text) for text in texts)


def inspect_audio_preflight(
    config: SttConfig,
    model: WhisperModel,
) -> AudioPreflightResult | None:
    """Inspect one short WAV before live STT without persisting its contents."""
    raw_path = str(config.preflight_audio_file or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("preflight audio sample was not created")

    pcm_samples, sample_rate = _read_pcm16_wav(path)
    if pcm_samples.size == 0:
        raise ValueError("preflight audio sample is empty")
    duration_seconds = float(pcm_samples.size / sample_rate)
    normalized = pcm_samples.astype(np.float32) / 32768.0
    peak = float(np.max(np.abs(pcm_samples)))
    rms = float(np.sqrt(np.mean(np.square(pcm_samples.astype(np.float64)))))

    frame_size = max(1, int(sample_rate * 0.25))
    frame_count = int(np.ceil(pcm_samples.size / frame_size))
    audible_frames = 0
    for frame_index in range(frame_count):
        frame = pcm_samples[frame_index * frame_size:(frame_index + 1) * frame_size]
        if not frame.size:
            continue
        frame_rms = float(np.sqrt(np.mean(np.square(frame.astype(np.float64)))))
        if (_dbfs(frame_rms) or -120.0) > -45.0:
            audible_frames += 1

    vad_segments, vad_characters = _preflight_transcript_stats(
        model,
        normalized,
        config,
        vad_filter=True,
    )
    no_vad_segments, no_vad_characters = _preflight_transcript_stats(
        model,
        normalized,
        config,
        vad_filter=False,
    )
    speech_detected = bool(vad_segments or no_vad_segments)
    return AudioPreflightResult(
        sample_path=str(path),
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        sample_count=int(pcm_samples.size),
        rms_dbfs=_dbfs(rms),
        peak_dbfs=_dbfs(peak),
        audible_frame_ratio=audible_frames / max(1, frame_count),
        vad_segment_count=vad_segments,
        vad_text_characters=vad_characters,
        no_vad_segment_count=no_vad_segments,
        no_vad_text_characters=no_vad_characters,
        speech_detected=speech_detected,
        vad_suppressed=not bool(vad_segments) and bool(no_vad_segments),
    )


def _write_audio_preflight_report(
    config: SttConfig,
    payload: dict[str, object],
) -> None:
    path_value = str(config.preflight_report_file or "").strip()
    if not path_value:
        return
    path = Path(path_value)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        print(f"[{config.ticker}] STT preflight report skipped: {exc}", flush=True)


def run_audio_preflight(
    config: SttConfig,
    model: WhisperModel,
) -> AudioPreflightResult | None:
    """Record a privacy-minimised VAD comparison for the current audio route."""
    raw_path = str(config.preflight_audio_file or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        result = inspect_audio_preflight(config, model)
        if result is None:
            return None
        _write_audio_preflight_report(config, {"status": "ok", **result.as_dict()})
        print(
            f"[{config.ticker}] STT_PREFLIGHT duration={result.duration_seconds:.1f}s "
            f"rms={result.rms_dbfs}dBFS peak={result.peak_dbfs}dBFS "
            f"audible_ratio={result.audible_frame_ratio:.2f}",
            flush=True,
        )
        print(
            f"[{config.ticker}] STT_PREFLIGHT_VAD vad_segments={result.vad_segment_count} "
            f"no_vad_segments={result.no_vad_segment_count} "
            f"speech_detected={str(result.speech_detected).lower()}",
            flush=True,
        )
        if result.vad_suppressed:
            print(
                f"[{config.ticker}] STT_PREFLIGHT_VAD_SUPPRESSED; "
                "disabling VAD for this capture",
                flush=True,
            )
        elif not result.speech_detected:
            print(f"[{config.ticker}] STT_PREFLIGHT_NO_SPEECH", flush=True)
        return result
    except ModelStalled:
        raise
    except Exception as exc:
        safe_error = f"{exc.__class__.__name__}: {exc}"[:400]
        _write_audio_preflight_report(config, {"status": "failed", "error": safe_error})
        print(f"[{config.ticker}] STT_PREFLIGHT_FAILED {safe_error}", flush=True)
        if config.preflight_required:
            raise RuntimeError("required audio preflight failed") from exc
        return None
    finally:
        if raw_path and not config.preflight_keep_audio:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def run_audio_preflight_only(config: SttConfig) -> int:
    """Classify one supervisor-captured WAV without opening a live input."""
    print(f"[{config.ticker}] loading STT preflight model: {config.model_name}", flush=True)
    model = load_whisper_model(config)
    try:
        result = run_audio_preflight(config, model)
    finally:
        if isinstance(model, SupervisedWhisperModel):
            model.close()
    if result is not None and result.speech_detected:
        print(
            f"[{config.ticker}] SPEECH_DETECTED "
            f"vad_suppressed={str(result.vad_suppressed).lower()}",
            flush=True,
        )
        return 0
    print(f"[{config.ticker}] SPEECH_NOT_DETECTED", flush=True)
    return STT_EXIT_NO_TEXT


def run_transcription(config: SttConfig) -> int:
    model: WhisperModel | None = None
    preflight: AudioPreflightResult | None = None
    if config.preflight_required:
        print(f"[{config.ticker}] loading STT model: {config.model_name}", flush=True)
        model = load_whisper_model(config)
        preflight = run_audio_preflight(config, model)
        if preflight is None or not preflight.speech_detected:
            print(
                f"[{config.ticker}] STT capture skipped: required speech preflight failed",
                flush=True,
            )
            if isinstance(model, SupervisedWhisperModel):
                model.close()
            return STT_EXIT_NO_TEXT

    command = build_ffmpeg_command(config)
    print(f"[{config.ticker}] ffmpeg input: {config.input_kind}:{config.input_source}", flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stderr_tail: deque[bytes] = deque(maxlen=8)
    stderr_thread = threading.Thread(
        target=_drain_stderr_tail,
        args=(process.stderr, stderr_tail),
        name=f"ffmpeg-stderr-{config.ticker}",
        daemon=True,
    )
    stderr_thread.start()

    reader_chunk_bytes = max(3200, _int_env("STT_AUDIO_READER_CHUNK_BYTES", 32000))
    queue_seconds = max(10.0, _float_env("STT_AUDIO_QUEUE_SECONDS", 180.0))
    queue_capacity = max(
        2,
        int((queue_seconds * 32000 + reader_chunk_bytes - 1) // reader_chunk_bytes),
    )
    audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=queue_capacity)
    session_started = time.monotonic()
    try:
        handoff_to_stt_seconds = max(0.0, time.time() - float(os.environ["STT_PCM_HANDOFF_STARTED_AT"]))
    except (KeyError, ValueError):
        handoff_to_stt_seconds = None
    reader_state = _AudioReaderState(
        finished=threading.Event(),
        stop_requested=threading.Event(),
        last_audio_at=session_started,
    )
    reader_thread = threading.Thread(
        target=_read_audio_continuously,
        args=(process, audio_queue, reader_state),
        kwargs={"chunk_bytes": reader_chunk_bytes,
                "preserve_backlog": bool(os.getenv("STT_PCM_HANDOFF_FILE", "")) and config.input_kind == "device"},
        name=f"ffmpeg-audio-{config.ticker}",
        daemon=True,
    )
    reader_thread.start()

    emitter = TranscriptEmitter(config)
    accumulated_text = ""
    chunk_count = 0
    emitted_chunks = 0
    stopped_by_limit = False
    stop_reason: str | None = None
    input_drained = False
    live_termination: dict[str, object] | None = None
    live_termination_seen_at: float | None = None
    direct_stop_requested = False
    handoff_input = os.getenv("STT_PCM_HANDOFF_FILE", "").strip() if config.input_kind == "device" else ""
    watchdog_exit: int | None = None
    interrupted = False
    buffered_audio = bytearray()
    rolling_step_bytes = max(32000, config.read_bytes - config.overlap_bytes)
    processed_window = False
    recent_transcript_words: list[str] = []
    speech_seen = False
    speech_evidence = SpeechEvidenceTracker() if config.live_capture else None
    last_text_at = time.monotonic()
    last_speech_at = last_text_at
    speech_evidence_reason = "no_text"
    first_speech_seconds = None
    backpressure_reported = False
    effective_vad_filter = config.vad_filter
    model_load_seconds = 0.0
    inference_seconds = 0.0
    new_audio_seconds = 0.0
    window_count = 0
    maximum_pending_seconds = 0.0
    first_text_seconds = None
    last_inference_at = None
    progress_stopped = threading.Event()
    closing_observer = TranscriptEndObserver(
        settle_seconds=max(30, _float_env('STT_LIVE_CLOSING_CONFIRM_SECONDS', 60)),
    ) if config.live_capture and config.supervised_live else None
    closing_published = False

    def consumer_progress() -> None:
        while not progress_stopped.wait(10):
            now = time.monotonic()
            try:
                recorded = Path(handoff_input).stat().st_size if handoff_input else reader_state.bytes_read
            except OSError:
                recorded = reader_state.bytes_read
            emit_live_event("stt", "consumer_heartbeat", progress=False,
                            consumer_alive=True, recorded_audio_bytes=recorded,
                            processed_audio_bytes=int(new_audio_seconds * 32000),
                            backlog_seconds=round(max(0, recorded / 32000 - new_audio_seconds), 3),
                            inference_age_seconds=round(now - last_inference_at, 3) if last_inference_at else None,
                            last_text_age_seconds=round(now - last_text_at, 3),
                            speech_seen=speech_seen, window_count=window_count,
                            speech_evidence_reason=speech_evidence_reason,
                            last_speech_age_seconds=round(now - last_speech_at, 3),
                            realtime_factor=round(inference_seconds / new_audio_seconds, 4) if new_audio_seconds else None,
                            generated_sequence=getattr(emitter, "_last_emitted_sequence", None),
                            fsynced_sequence=getattr(emitter, "_last_durable_sequence", None),
                            db_committed_sequence=getattr(emitter, "_last_archived_sequence", None))

    progress_thread = threading.Thread(target=consumer_progress, name="stt-live-progress", daemon=True)
    progress_thread.start()

    print(f"[{config.ticker}] STT worker started call_id={config.call_id}", flush=True)
    print(f"[{config.ticker}] AI Engine: {config.ai_engine_url}/api/v1/analyze", flush=True)
    print(
        f"[{config.ticker}] Backend Transcript: "
        f"{config.backend_url}/api/v1/internal/transcript-segment",
        flush=True,
    )

    def transcribe_audio(client: httpx.Client, raw_audio: bytes) -> None:
        nonlocal accumulated_text, chunk_count, emitted_chunks, last_text_at, speech_seen
        nonlocal last_speech_at, speech_evidence_reason, first_speech_seconds
        nonlocal inference_seconds, new_audio_seconds, window_count, maximum_pending_seconds, first_text_seconds, last_inference_at
        nonlocal closing_published
        if not raw_audio:
            return
        if model is None:
            raise RuntimeError("STT model was not initialized")
        audio_data = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
        inference_started = time.monotonic()
        segments, _ = model.transcribe(
            audio_data,
            beam_size=config.beam_size,
            language=config.language,
            vad_filter=effective_vad_filter,
        )

        text_found = False
        # Preserve original model evidence before overlap de-duplication. This
        # gate controls the watchdog, never which transcript text is archived.
        segments = list(segments)
        for segment in segments:
            text = _deduplicate_transcript_fragment(
                segment.text,
                recent_transcript_words,
            )
            if text:
                text_found = True
                accumulated_text += " " + text
                sys.stdout.write(f"\r[transcribing] {text}")
                sys.stdout.flush()
        last_inference_at = time.monotonic()
        inference_seconds += last_inference_at - inference_started
        new_audio_seconds += max(0, len(raw_audio) - (config.overlap_bytes if window_count else 0)) / 32000
        window_count += 1
        with audio_queue.mutex:
            pending_bytes = sum(len(item) for item in audio_queue.queue) + len(buffered_audio)
        handoff_path = os.getenv("STT_PCM_HANDOFF_FILE", "")
        if handoff_path:
            try:
                pending_bytes += max(0, Path(handoff_path).stat().st_size - reader_state.bytes_read)
            except OSError:
                pass
        maximum_pending_seconds = max(maximum_pending_seconds, pending_bytes / 32000)
        if text_found:
            if first_text_seconds is None:
                first_text_seconds = time.monotonic() - session_started
            last_text_at = time.monotonic()
        if speech_evidence is not None:
            evidence = speech_evidence.observe(segments, audio_seconds=new_audio_seconds)
            speech_evidence_reason = evidence.reason
            if evidence.confirmed and evidence.credible_window:
                last_speech_at = time.monotonic()
                if not speech_seen:
                    first_speech_seconds = last_speech_at - session_started
                    emit_live_event("stt", "speech_continuity_confirmed", status="transcribing",
                                    progress=True, candidate_windows=evidence.candidate_windows,
                                    processed_audio_seconds=round(new_audio_seconds, 3))
                speech_seen = True
        elif text_found:
            speech_seen = True
            last_speech_at = last_text_at

        chunk_count += 1
        if chunk_count >= config.reads_per_emit and accumulated_text.strip():
            emitter.emit_chunk(client, accumulated_text, is_final=False)
            emitted_chunks += 1
            accumulated_text = ""
            chunk_count = 0
        emit_live_event("stt", "window_processed",
                        status="transcribing" if (text_found and (speech_seen or not config.live_capture)) else "waiting_for_speech",
                        progress=True, speech_seen=speech_seen, window_count=window_count,
                        text_found=text_found, processed_audio_bytes=int(new_audio_seconds * 32000),
                        speech_evidence_reason=speech_evidence_reason,
                        last_speech_age_seconds=round(time.monotonic() - last_speech_at, 3),
                        last_text_age_seconds=round(time.monotonic() - last_text_at, 3),
                        backlog_seconds=round(pending_bytes / 32000, 3),
                        realtime_factor=round(inference_seconds / new_audio_seconds, 4) if new_audio_seconds else None)
        if closing_observer is not None and not closing_published:
            previous_candidate = bool(closing_observer.candidate)
            previous_closing_audio = (closing_observer.candidate or {}).get('closing_audio_seconds')
            # Archive overlap removal does not prove silence. A repeated spoken
            # sign-off must still postpone confirmation until quiet audio follows.
            closing = closing_observer.observe(' '.join(str(segment.text) for segment in segments),
                audio_seconds=new_audio_seconds, backlog_seconds=pending_bytes / 32000)
            if bool(closing_observer.candidate) != previous_candidate:
                emit_live_event('stt', 'operator_closing_candidate',
                    status='observing' if closing_observer.candidate else 'cancelled',
                    processed_audio_seconds=round(new_audio_seconds, 3),
                    speech_windows=closing_observer.speech_windows)
            elif (closing_observer.candidate and
                  closing_observer.candidate.get('closing_audio_seconds') != previous_closing_audio):
                emit_live_event('stt', 'operator_closing_candidate', status='extended',
                    processed_audio_seconds=round(new_audio_seconds, 3),
                    reason='operator_closing_followup', speech_windows=closing_observer.speech_windows)
            if closing and emitter.sequence >= 2 and not _read_live_termination(config):
                marker = publish_operator_end(config, closing)
                if marker:
                    closing_published = True
                    emit_live_event('stt', 'operator_closing_confirmed', status='event_ended',
                        progress=True, post_close_audio_seconds=closing['post_close_audio_seconds'],
                        quiet_windows=closing['quiet_windows'])
                else:
                    emit_live_event('stt', 'operator_closing_unverified', status='warning',
                        reason='current_run_target_proof_unavailable')
        if handoff_input:
            try:
                _write_private_json(Path(handoff_input + ".state.json"), {
                    "version": 1, "capture_session_id": config.capture_session_id,
                    "processed_audio_bytes": int(new_audio_seconds * 32000),
                    "generated_sequence": getattr(emitter, "_last_emitted_sequence", None),
                    "fsynced_sequence": getattr(emitter, "_last_durable_sequence", None),
                    "db_committed_sequence": getattr(emitter, "_last_archived_sequence", None),
                    "automatic_consumer_resume": False,
                })
            except OSError:
                emit_live_event("stt", "consumer_checkpoint_failed", status="warning")

    try:
        if model is None:
            # FFmpeg is already being drained by reader_thread while a cold model
            # loads, so the beginning of a live call is retained in the queue.
            print(f"[{config.ticker}] loading STT model: {config.model_name}", flush=True)
            model_load_started = time.monotonic()
            model = load_whisper_model(config)
            model_load_seconds = time.monotonic() - model_load_started
            preflight = run_audio_preflight(config, model)
        effective_vad_filter = config.vad_filter and not bool(
            preflight and preflight.vad_suppressed
        )
        with httpx.Client() as client:
            while True:
                now = time.monotonic()
                live_termination = _read_live_termination(config)
                draining_live_end = live_termination is not None
                if draining_live_end:
                    if live_termination_seen_at is None:
                        live_termination_seen_at = now
                    if not handoff_input and not direct_stop_requested:
                        # A direct Pulse input never reaches EOF on its own.
                        # Stop only that recorder; killing a spool follower
                        # here would throw away its already-recorded tail.
                        direct_stop_requested = True
                        if process.poll() is None:
                            try:
                                process.terminate()
                            except ProcessLookupError:
                                pass
                    input_stopped = (reader_state.finished.is_set() or process.poll() is not None
                                     or _handoff_producer_finished(handoff_input))
                    if not input_stopped and now - live_termination_seen_at >= config.live_drain_timeout_seconds:
                        stopped_by_limit = True
                        stop_reason = "live_drain_timeout"
                        print(f"[{config.ticker}] STT live input did not stop after terminal signal", flush=True)
                        break
                if (
                    not draining_live_end
                    and
                    config.max_session_seconds is not None
                    and now - session_started >= config.max_session_seconds
                ):
                    print(
                        f"[{config.ticker}] STT max session reached "
                        f"seconds={config.max_session_seconds}",
                        flush=True,
                    )
                    stopped_by_limit = True
                    stop_reason = "live_session_guard" if config.live_capture else "bounded_capture_complete"
                    break
                if not draining_live_end and config.max_chunks is not None and emitted_chunks >= config.max_chunks:
                    stopped_by_limit = True
                    stop_reason = "live_chunk_limit" if config.live_capture else "bounded_capture_complete"
                    break

                if reader_state.dropped_bytes and not backpressure_reported:
                    print(
                        f"[{config.ticker}] STT_AUDIO_BACKPRESSURE "
                        f"dropped_bytes={reader_state.dropped_bytes} "
                        f"queue_seconds={queue_seconds:g}",
                        flush=True,
                    )
                    backpressure_reported = True

                read_timeout = min(0.5, config.no_chunk_timeout_seconds)
                try:
                    raw_audio = audio_queue.get(timeout=read_timeout)
                except queue.Empty:
                    raw_audio = None
                now = time.monotonic()
                if raw_audio is None:
                    if reader_state.finished.is_set() and audio_queue.empty():
                        input_drained = True
                        break
                    if now - reader_state.last_audio_at >= config.no_chunk_timeout_seconds:
                        watchdog_exit = STT_EXIT_NO_CHUNKS
                        print(
                            f"[{config.ticker}] STT watchdog: no audio chunks for "
                            f"{config.no_chunk_timeout_seconds:g}s",
                            flush=True,
                        )
                        break
                    text_timeout = config.initial_speech_timeout_seconds if config.live_capture and not speech_seen else config.no_text_timeout_seconds
                    if not draining_live_end and text_timeout is not None and now - last_speech_at >= text_timeout:
                        print(
                            f"[{config.ticker}] STT watchdog: no confirmed speech progress for "
                            f"{text_timeout}s",
                            flush=True,
                        )
                        if config.live_capture:
                            stopped_by_limit = True
                            stop_reason = "live_speech_idle_timeout" if speech_seen else "live_initial_speech_timeout"
                        elif speech_seen:
                            stopped_by_limit = True
                            stop_reason = "speech_idle_timeout"
                        else:
                            watchdog_exit = STT_EXIT_NO_TEXT
                        break
                    continue
                if not raw_audio:
                    continue

                buffered_audio.extend(raw_audio)
                while len(buffered_audio) >= config.read_bytes:
                    block = bytes(buffered_audio[:config.read_bytes])
                    del buffered_audio[:rolling_step_bytes]
                    transcribe_audio(client, block)
                    processed_window = True
                    if not draining_live_end and config.max_chunks is not None and emitted_chunks >= config.max_chunks:
                        stopped_by_limit = True
                        stop_reason = "live_chunk_limit" if config.live_capture else "bounded_capture_complete"
                        break
                if stopped_by_limit:
                    break
                text_timeout = config.initial_speech_timeout_seconds if config.live_capture and not speech_seen else config.no_text_timeout_seconds
                if not draining_live_end and text_timeout is not None and time.monotonic() - last_speech_at >= text_timeout:
                    print(
                        f"[{config.ticker}] STT watchdog: no confirmed speech progress for "
                        f"{text_timeout}s",
                        flush=True,
                    )
                    if config.live_capture:
                        stopped_by_limit = True
                        stop_reason = "live_speech_idle_timeout" if speech_seen else "live_initial_speech_timeout"
                    elif speech_seen:
                        stopped_by_limit = True
                        stop_reason = "speech_idle_timeout"
                    else:
                        watchdog_exit = STT_EXIT_NO_TEXT
                    break

            if buffered_audio and (
                not processed_window or len(buffered_audio) > config.overlap_bytes
            ):
                transcribe_audio(client, bytes(buffered_audio))
            if accumulated_text.strip():
                emitter.emit_chunk(client, accumulated_text, is_final=False)
                emitted_chunks += 1

    except ModelStalled as exc:
        watchdog_exit = STT_EXIT_MODEL_STALLED
        emit_live_event("stt", "consumer_model_failed", status="error", reason=str(exc), pcm_preserved=bool(handoff_input))
        if accumulated_text.strip():
            with httpx.Client() as recovery_client:
                emitter.emit_chunk(recovery_client, accumulated_text, is_final=False)
    except KeyboardInterrupt:
        interrupted = True
        print("\nSTT worker interrupted", flush=True)
    finally:
        progress_stopped.set()
        progress_thread.join(timeout=1)
        if isinstance(model, SupervisedWhisperModel):
            model.close()
        reader_state.stop_requested.set()
        if process.poll() is None:
            if not direct_stop_requested:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader_thread.join(timeout=2)
        stderr_thread.join(timeout=1)

    print(
        f"[{config.ticker}] STT_AUDIO_READER bytes={reader_state.bytes_read} "
        f"dropped_bytes={reader_state.dropped_bytes} queue_capacity={queue_capacity}",
        flush=True,
    )

    metrics = {
        "model": config.model_name, "model_load_seconds": round(model_load_seconds, 3),
        "inference_seconds": round(inference_seconds, 3),
        "new_audio_seconds": round(new_audio_seconds, 3),
        "realtime_factor": round(inference_seconds / new_audio_seconds, 4) if new_audio_seconds else None,
        "maximum_pending_audio_seconds": round(maximum_pending_seconds, 3),
        "first_text_seconds": round(first_text_seconds, 3) if first_text_seconds is not None else None,
        "first_confirmed_speech_seconds": round(first_speech_seconds, 3) if first_speech_seconds is not None else None,
        "dropped_bytes": reader_state.dropped_bytes,
        "handoff_to_stt_seconds": round(handoff_to_stt_seconds, 3) if handoff_to_stt_seconds is not None else None,
        "handoff_to_first_text_seconds": round(handoff_to_stt_seconds + first_text_seconds, 3)
            if handoff_to_stt_seconds is not None and first_text_seconds is not None else None,
    }
    print(f"[{config.ticker}] STT_PERFORMANCE " + json.dumps(metrics, sort_keys=True), flush=True)
    stderr_text = b"".join(stderr_tail).decode(errors="replace")
    expected_ffmpeg_exit = ffmpeg_exit_is_expected(
        process.returncode,
        stopped_by_limit=stopped_by_limit,
    )
    live_termination = _read_live_termination(config)
    confirmed_live_end = bool(live_termination and live_termination.get("reason") == "event_ended" and input_drained)
    if confirmed_live_end and process.returncode in {130, 143, 255}:
        expected_ffmpeg_exit = True
    if interrupted:
        exit_code = STT_EXIT_INTERRUPTED
        termination_reason = "interrupted"
    elif reader_state.dropped_bytes:
        exit_code = STT_EXIT_AUDIO_BACKPRESSURE
        termination_reason = "audio_backpressure_dropped"
    elif reader_state.error:
        exit_code = int(process.returncode or 1)
        termination_reason = "audio_reader_error"
    elif watchdog_exit == STT_EXIT_MODEL_STALLED:
        exit_code = STT_EXIT_MODEL_STALLED
        termination_reason = "model_stalled_recovery_exhausted"
    elif watchdog_exit == STT_EXIT_NO_CHUNKS:
        exit_code = STT_EXIT_NO_CHUNKS
        termination_reason = "no_audio_chunks_watchdog"
    elif watchdog_exit == STT_EXIT_NO_TEXT:
        exit_code = STT_EXIT_NO_TEXT
        termination_reason = "no_transcript_text_watchdog"
    elif (config.live_capture and live_termination and live_termination.get("reason") == "source_lost"
          and stop_reason != "live_drain_timeout"):
        exit_code = STT_EXIT_LIVE_SOURCE_LOST
        termination_reason = "live_source_lost"
    elif config.live_capture and stopped_by_limit:
        exit_code = STT_EXIT_LIVE_GUARD
        termination_reason = stop_reason or "live_session_guard"
    elif not emitter.sequence:
        exit_code = STT_EXIT_NO_TEXT
        termination_reason = "no_transcript_segments"
    elif config.live_capture and input_drained and not confirmed_live_end:
        # The consumer may propagate a producer's 130/143/255 on EOF. Without
        # this run's explicit end proof it is still an incomplete live input,
        # not a user interrupt or a successfully finished recording.
        exit_code = STT_EXIT_LIVE_INCOMPLETE
        termination_reason = "live_input_ended_without_event_end"
    elif not expected_ffmpeg_exit:
        exit_code = int(process.returncode or 1)
        termination_reason = "ffmpeg_error"
    elif not config.target_identity_verified:
        exit_code = STT_EXIT_TARGET_UNVERIFIED
        termination_reason = "target_identity_unverified"
    elif config.live_capture and not confirmed_live_end:
        exit_code = STT_EXIT_LIVE_INCOMPLETE
        termination_reason = "live_input_ended_without_event_end"
    else:
        exit_code = 0
        termination_reason = (
            "event_ended" if config.live_capture
            else stop_reason or "input_ended"
        )

    print(f"[{config.ticker}] STT_TERMINATION reason={termination_reason} exit_code={exit_code} input_drained={str(input_drained).lower()}", flush=True)
    if config.live_capture and exit_code != 0:
        print(f"[{config.ticker}] STT_LIVE_INCOMPLETE reason={termination_reason} exit_code={exit_code}", flush=True)

    terminal_marker_written = False
    if emitter.sequence:
        terminal_marker_written = emitter.finish_session(
            termination_reason=termination_reason,
            success_eligible=exit_code == 0,
            target_identity_verified=config.target_identity_verified,
        )

    if exit_code == STT_EXIT_NO_TEXT and not emitter.sequence:
        print(f"[{config.ticker}] STT exited without transcript segments", flush=True)
    if exit_code == 0 and not terminal_marker_written:
        print(f"[{config.ticker}] STT archive terminal marker was not persisted", flush=True)
        return STT_EXIT_ARCHIVE_INCOMPLETE
    if exit_code != 0:
        if stderr_text:
            print(stderr_text[-4000:], file=sys.stderr, flush=True)
        return exit_code

    print(
        f"\n[{config.ticker}] STT worker stopped reason={termination_reason}",
        flush=True,
    )
    return 0


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
    try:
        if args.audio_preflight_only:
            return run_audio_preflight_only(config)
        return run_transcription(config)
    except ModelStalled as exc:
        emit_live_event("stt", "model_failed_before_consumer", status="error", reason=str(exc))
        return STT_EXIT_MODEL_STALLED


if __name__ == "__main__":
    raise SystemExit(main())
