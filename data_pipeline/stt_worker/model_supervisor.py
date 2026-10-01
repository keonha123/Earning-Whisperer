"""Bound native Whisper work without discarding the live browser or PCM input.

Only the model lives in the child. Complete window results cross the pipe
atomically; the parent owns transcript sequencing and overlap de-duplication.
A timed-out window can therefore be retried before any of its text is emitted.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
import multiprocessing
import os
from pathlib import Path
import time
from types import SimpleNamespace

from data_pipeline.live_telemetry import emit_live_event
from data_pipeline.stt_worker.speech_evidence import segment_evidence_payload


class ModelStalled(RuntimeError):
    pass


class ModelRestartRequested(ModelStalled):
    pass


def _finite_env(name: str, default: float, minimum: float = 1.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return max(minimum, value) if math.isfinite(value) else default
    except ValueError:
        return default


def _model_process(connection, config) -> None:
    try:
        from .take import _load_whisper_model_direct
        model = _load_whisper_model_direct(config)
        connection.send(("ready", None))
        while True:
            message = connection.recv()
            if message[0] == "close":
                return
            _, audio, options = message
            segments, _ = model.transcribe(audio, **options)
            # Do not send partial text: retrying a hung generator must not
            # duplicate already-published segments or advance the PCM offset.
            result = [segment_evidence_payload(segment) for segment in segments]
            connection.send(("result", result))
    except EOFError:
        return
    except BaseException as exc:
        try:
            connection.send(("error", type(exc).__name__))
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


def _request_timestamp(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


class SupervisedWhisperModel:
    def __init__(self, config, *, context=None, worker_target=None,
                 load_timeout=None, inference_timeout=None, max_restarts=None):
        self.config = config
        self.context = context or multiprocessing.get_context("spawn")
        self.worker_target = worker_target or _model_process
        self.load_timeout = load_timeout if load_timeout is not None else _finite_env("STT_MODEL_LOAD_TIMEOUT_SECONDS", 120)
        self.inference_timeout = inference_timeout if inference_timeout is not None else _finite_env("STT_INFERENCE_TIMEOUT_SECONDS", 90)
        self.max_restarts = max_restarts if max_restarts is not None else int(_finite_env("STT_MODEL_MAX_RESTARTS", 2, 0))
        self.restarts = 0
        self.process = None
        self.connection = None
        self.last_request = None
        self.started_at = time.monotonic()
        self._start_with_recovery()

    def _operator_restart_requested(self) -> bool:
        directory = os.getenv("WEBCAST_PROGRESS_DIR", "").strip()
        if not directory:
            return False
        path = Path(directory) / "stt-restart.json"
        try:
            stat = path.stat()
            if stat.st_size > 8192 or stat.st_mtime == self.last_request:
                return False
            self.last_request = stat.st_mtime
            request = json.loads(path.read_text())
            expected = {
                "call_id": os.getenv("WEBCAST_CALL_DB_ID", ""),
                "capture_session_id": os.getenv("STT_CAPTURE_SESSION_ID", self.config.capture_session_id),
                "schedule_revision": os.getenv("WEBCAST_SCHEDULE_REVISION", ""),
                "attempt_id": os.getenv("WEBCAST_ATTEMPT_ID", ""),
            }
            if (not all(str(request.get(key, "")) == str(value) for key, value in expected.items())
                    or not all(str(value) for value in expected.values())
                    or not 0 <= time.time() - _request_timestamp(request.get("requested_at")) <= 120):
                emit_live_event("stt", "restart_request_rejected", status="warning", reason="identity_or_freshness")
                return False
            emit_live_event("stt", "restart_request_accepted", status="recovering")
            return True
        except (OSError, ValueError, TypeError):
            return False

    def _receive(self, phase: str, timeout: float):
        started = time.monotonic()
        last_heartbeat = started
        while True:
            elapsed = time.monotonic() - started
            if self._operator_restart_requested():
                raise ModelRestartRequested("operator_requested_model_restart")
            # This deadline is checked in the supervisor, independently of
            # CTranslate2/native inference and the model child's Python GIL.
            if elapsed >= timeout:
                raise ModelStalled(f"{phase}_timeout")
            if self.config.max_session_seconds and time.monotonic() - self.started_at >= self.config.max_session_seconds:
                raise ModelStalled("live_session_guard")
            if self.connection.poll(min(0.25, max(0.001, timeout - elapsed))):
                try:
                    kind, payload = self.connection.recv()
                except EOFError as exc:
                    raise ModelStalled(f"{phase}_worker_exited") from exc
                if kind == "error":
                    raise ModelStalled(f"{phase}_worker_error:{payload}")
                return kind, payload
            if not self.process.is_alive():
                raise ModelStalled(f"{phase}_worker_exited")
            if time.monotonic() - last_heartbeat >= 10:
                emit_live_event("stt", f"{phase}_waiting", status="warning" if elapsed >= 30 else "busy", progress=False,
                                model_phase=phase, elapsed_seconds=round(elapsed, 2), timeout_seconds=timeout,
                                model_pid=self.process.pid, model_restarts=self.restarts)
                last_heartbeat = time.monotonic()

    def _start_once(self) -> None:
        self.close()
        self.connection, child = self.context.Pipe(duplex=True)
        self.process = self.context.Process(target=self.worker_target, args=(child, self.config), daemon=True)
        emit_live_event("stt", "model_load_started", status="loading", progress=False,
                        model_phase="model_load", timeout_seconds=self.load_timeout, model_restarts=self.restarts)
        self.process.start()
        child.close()
        kind, _ = self._receive("model_load", self.load_timeout)
        if kind != "ready":
            raise ModelStalled("model_load_protocol_error")
        emit_live_event("stt", "model_ready", status="ready", progress=True,
                        model_phase="ready", model_pid=self.process.pid, model_restarts=self.restarts)

    def _recover(self, failure: ModelStalled) -> None:
        self.close()
        if self.restarts >= self.max_restarts or str(failure) == "live_session_guard":
            emit_live_event("stt", "model_recovery_exhausted", status="error", reason=str(failure),
                            model_restarts=self.restarts, pcm_preserved=True)
            raise failure
        self.restarts += 1
        emit_live_event("stt", "model_restarting", status="recovering", reason=str(failure),
                        model_restarts=self.restarts, browser_preserved=True, window_replayed=True)

    def _start_with_recovery(self) -> None:
        while True:
            try:
                self._start_once()
                return
            except ModelStalled as exc:
                self._recover(exc)

    def transcribe(self, audio, **options):
        while True:
            try:
                emit_live_event("stt", "inference_started", status="busy", progress=False,
                                model_phase="inference", window_audio_seconds=round(len(audio) / 16000, 3),
                                timeout_seconds=self.inference_timeout)
                self.connection.send(("transcribe", audio, options))
                kind, texts = self._receive("inference", self.inference_timeout)
                if kind != "result":
                    raise ModelStalled("inference_protocol_error")
                emit_live_event("stt", "inference_completed", status="ready", progress=True,
                                model_phase="ready", segment_count=len(texts), text_characters=sum(
                                    len(str(value.get("text", ""))) if isinstance(value, dict) else len(str(value))
                                    for value in texts),
                                model_restarts=self.restarts)
                # Accept legacy text-only workers used by recovery/test adapters.
                return [SimpleNamespace(**value) if isinstance(value, dict)
                        else SimpleNamespace(text=str(value)) for value in texts], None
            except (BrokenPipeError, EOFError, OSError) as exc:
                self._recover(ModelStalled(f"inference_pipe_error:{type(exc).__name__}"))
                self._start_with_recovery()
            except ModelStalled as exc:
                self._recover(exc)
                self._start_with_recovery()

    def close(self) -> None:
        process = self.process
        if process is not None:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
            else:
                process.join(timeout=0.1)
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
