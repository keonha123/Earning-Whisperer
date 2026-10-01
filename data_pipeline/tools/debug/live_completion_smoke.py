"""Offline live-completion smoke: Chromium -> Pulse -> real Whisper -> local archive.

Run inside the browser-webcast image with network disabled, an existing tiny
CTranslate2 model, and a generated speech WAV. The production browser, shell,
PCM handoff, STT loop, and archive spool/replay run unchanged. Only three archive
database functions are replaced by a durable local JSONL destination in the STT
child. This verifies the lifecycle protocol, not production MySQL/backend writes.

Example:
  python -m data_pipeline.tools.debug.live_completion_smoke \
    --audio-file /fixtures/speech.wav --model /models/tiny --output /results/smoke
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
import wave


def _append_private_jsonl(path: Path, value: dict) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def archive_worker(argv: list[str]) -> int:
    """Test-only destination boundary; retain production transcription/spooling."""
    from data_pipeline import database
    from data_pipeline.stt_worker import take

    destination = Path(os.environ["EW_COMPLETION_SMOKE_ARCHIVE"])

    def archive(payload, **_kwargs):
        _append_private_jsonl(destination, {"kind": "segment", "payload": payload})

    def finish(call_id, sequence, **details):
        rows = [json.loads(line) for line in destination.read_text().splitlines()] if destination.exists() else []
        if not any(row.get("kind") == "segment" and row["payload"].get("call_id") == call_id
                   and row["payload"].get("sequence") == sequence for row in rows):
            return False
        details.pop("ensure_schema", None)
        _append_private_jsonl(destination, {"kind": "session_end", "call_id": call_id,
                                           "sequence": sequence, **details})
        return True

    database.ensure_transcript_archive_schema = lambda: None
    database.archive_transcript_segment = archive
    database.mark_transcript_session_end = finish
    return take.main(argv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio-file", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--read-bytes", type=int, default=320000)
    parser.add_argument("--overlap-bytes", type=int, default=32000)
    parser.add_argument("--session-id", default="completion-" + uuid.uuid4().hex[:12],
                        help="Unique identity for parallel offline captures.")
    args = parser.parse_args(argv)
    if not (args.model / "model.bin").is_file():
        parser.error("--model must be an existing local CTranslate2 model directory")
    if args.seconds < 20 or args.seconds > 90:
        parser.error("--seconds must be 20..90 and exceed the legacy browser hold")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", args.session_id):
        parser.error("--session-id must be 1..40 letters, digits, underscores or hyphens")
    if args.cpu_threads < 1:
        parser.error("--cpu-threads must be positive")
    if args.read_bytes < 32000 or not 0 <= args.overlap_bytes < args.read_bytes:
        parser.error("--read-bytes must be >= 32000 and overlap must be smaller")
    sink = "ew_smoke_" + args.session_id
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(output.iterdir()):
        parser.error("--output must be empty so prior evidence cannot pass this run")
    output.chmod(0o700)
    with wave.open(str(args.audio_file), "rb") as source:
        params = source.getparams()
        frames = source.readframes(args.seconds * source.getframerate())
    seconds = len(frames) / (params.framerate * params.nchannels * params.sampwidth)
    if seconds < 20:
        parser.error("speech fixture must contain at least 20 seconds")
    wav = io.BytesIO()
    with wave.open(wav, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)
    speech = wav.getvalue()
    observed = {"audio_requested": 0, "started_at": None, "ended_at": None}
    today = datetime.now(timezone.utc).date()
    date_text = today.strftime("%B %d, %Y")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/speech.wav":
                observed["audio_requested"] += 1
                content, kind = speech, "audio/wav"
            elif self.path in {"/started", "/ended"}:
                observed["started_at" if self.path == "/started" else "ended_at"] = time.monotonic()
                content, kind = b"ok", "text/plain"
            else:
                content = f'''<h1>TEST quarterly earnings call {date_text}</h1>
                  <button onclick="document.querySelector('audio').play();this.remove()">Enter webcast</button>
                  <audio controls src="/speech.wav" onplaying="fetch('/started')"
                    onended="document.querySelector('#status').textContent='The webinar has ended.';fetch('/ended')"></audio>
                  <div id="status" role="status"></div>'''.encode()
                kind = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/player/current"
    proof = {"verified": True, "call_ticker": "TEST", "target_date": today.isoformat(),
             "source_url": url, "target_url": url, "provider_event_id": None,
             "observed_at": datetime.now(timezone.utc).isoformat(),
             "evidence": f"TEST quarterly earnings call {date_text}"}
    # The wrapper intercepts only the STT module entrypoint; every other Python
    # invocation uses the same real interpreter without monkeypatches.
    binary = output / "bin"
    binary.mkdir(mode=0o700)
    wrapper = binary / "python"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[3])!r})\n"
        "if __name__ == '__main__':\n"
        " if sys.argv[1:3] == ['-m', 'data_pipeline.stt_worker.take']:\n"
        "  from data_pipeline.tools.debug.live_completion_smoke import archive_worker\n"
        "  raise SystemExit(archive_worker(sys.argv[3:]))\n"
        f" os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    archive_path = output / "archive.jsonl"
    termination_path = output / "termination.json"
    environment = {**os.environ,
        "PATH": str(binary) + os.pathsep + os.environ.get("PATH", ""),
        "WEBCAST_LIFECYCLE": "live", "WEBCAST_HEADED": "true",
        "WEBCAST_LIVE_IDENTITY_PROOF": json.dumps(proof), "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true",
        "WEBCAST_TARGET_DATE": today.isoformat(), "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION": "true",
        "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false", "WEBCAST_VISION_ENABLED": "false",
        "WEBCAST_LIVE_DIAGNOSTICS": "false", "WEBCAST_STORAGE_STATE": "",
        "WEBCAST_SAVE_STORAGE_STATE": str(output / "storage.json"),
        "WEBCAST_ARTIFACTS_DIR": str(output / "screens"),
        "WEBCAST_PULSE_SINK": sink, "STT_INPUT_SOURCE": sink + ".monitor",
        "WEBCAST_PULSE_RUNTIME_DIR": "", "WEBCAST_VNC_ENABLED": "false",
        "WEBCAST_HOLD_SECONDS": "1", "WEBCAST_AUDIO_WARMUP_SECONDS": "0",
        "WEBCAST_TARGET_NAVIGATION_TIMEOUT_SECONDS": "2", "WEBCAST_CONTROL_TIMEOUT_SECONDS": "5",
        "WEBCAST_PAGE_READY_TIMEOUT_SECONDS": "2", "WEBCAST_POST_REGISTRATION_PLAYBACK_WAIT_SECONDS": "2",
        "DATE_STREAM_AUDIO_WAIT_SECONDS": "1", "DATE_STREAM_AUDIO_PROBE_SECONDS": "1",
        "WEBCAST_SPEECH_PREFLIGHT_ENABLED": "false", "STT_AUDIO_PREFLIGHT_SECONDS": "0",
        "WEBCAST_LIVE_END_CONFIRM_SECONDS": "0.3", "WEBCAST_LIVE_END_POLL_SECONDS": "0.1",
        "WEBCAST_LIVE_TERMINATION_FILE": str(termination_path),
        "WEBCAST_PLAYBACK_READY_FILE": str(output / "playback-ready"),
        "WEBCAST_TARGET_IDENTITY_READY_FILE": str(output / "identity-ready"),
        "WEBCAST_ACTIVE_PLAYER_URL_FILE": str(output / "active-url"),
        "WEBCAST_LAST_TARGET_URL_FILE": str(output / "last-url"),
        "WEBCAST_MEDIA_CANDIDATES_FILE": str(output / "media.json"),
        "WEBCAST_RECIPE_CONTEXT_PATH": str(output / "recipe.json"),
        "CALL_ID": args.session_id, "STT_CAPTURE_SESSION_ID": args.session_id,
        "STT_MODEL_NAME": str(args.model.resolve()), "STT_DEVICE": "cpu", "STT_COMPUTE_TYPE": "int8",
        "STT_CPU_THREADS": str(args.cpu_threads), "STT_BEAM_SIZE": "1", "STT_LANGUAGE": "en",
        "STT_READ_BYTES": str(args.read_bytes), "STT_OVERLAP_BYTES": str(args.overlap_bytes),
        "STT_READS_PER_EMIT": "1",
        "STT_MAX_SESSION_SECONDS": "150", "STT_INITIAL_SPEECH_TIMEOUT_SECONDS": "120",
        "STT_NO_TEXT_TIMEOUT_SECONDS": "120", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "DB_URL": "sqlite:///:memory:", "SEND_TO_AI_ENGINE": "false", "SEND_TO_BACKEND": "false",
        "TRANSCRIPT_ARCHIVE_ENABLED": "true", "TRANSCRIPT_ARCHIVE_SPOOL_PATH": str(output / "spool.jsonl"),
        "EW_COMPLETION_SMOKE_ARCHIVE": str(archive_path), "PYTHONDONTWRITEBYTECODE": "1",
    }
    started = time.monotonic()
    try:
        with (output / "capture.log").open("w") as log:
            process = subprocess.run(["bash", "data_pipeline/scripts/run_webcast_audio_capture.sh", "TEST", url],
                                     env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    finally:
        server.shutdown()
        server.server_close()
    log = (output / "capture.log").read_text(errors="replace")
    rows = [json.loads(line) for line in archive_path.read_text().splitlines()] if archive_path.exists() else []
    segments = [row["payload"] for row in rows if row.get("kind") == "segment"]
    terminal = next((row for row in reversed(rows) if row.get("kind") == "session_end"), None)
    transcript = " ".join(str(row.get("text", "")) for row in segments)
    end_signal = json.loads(termination_path.read_text()) if termination_path.exists() else None
    metrics = next((json.loads(line.split("STT_PERFORMANCE ", 1)[1]) for line in log.splitlines()
                    if "STT_PERFORMANCE " in line), None)
    played = (observed["ended_at"] - observed["started_at"]
              if observed["ended_at"] is not None and observed["started_at"] is not None else None)
    fixture_words = {word for word in ("earnings", "revenue", "income", "distribution", "guidance",
                                       "inventory", "transportation", "customer", "quarter")
                     if word in transcript.lower()}
    checks = {
        "shell_exit_zero": process.returncode == 0,
        "actual_text": len(segments) >= 2 and len(transcript) >= 80 and len(fixture_words) >= 2,
        "actual_audio": "AUDIO_DETECTED" in log,
        "played_beyond_old_hold": played is not None and played > 15,
        "browser_explicit_event_end": bool(end_signal and end_signal.get("reason") == "event_ended"),
        "terminal_event_ended": bool(terminal and terminal.get("termination_reason") == "event_ended"
                                     and terminal.get("success_eligible") is True
                                     and terminal.get("target_identity_verified") is True),
        "stt_drained": "STT_TERMINATION reason=event_ended exit_code=0 input_drained=true" in log,
        "no_audio_drop": bool(metrics and metrics.get("dropped_bytes") == 0),
        "real_model_and_audio": bool(metrics and metrics.get("model") == str(args.model.resolve())
                                     and metrics.get("new_audio_seconds", 0) > 15),
        "only_current_session": bool(segments and all(
            row.get("call_id") == args.session_id for row in segments)),
    }
    report = {"passed": all(checks.values()), "checks": checks, "exit_code": process.returncode,
              "session_id": args.session_id, "cpu_threads": args.cpu_threads,
              "player_started_at": observed["started_at"], "player_ended_at": observed["ended_at"],
              "elapsed_seconds": round(time.monotonic() - started, 3), "fixture_audio_seconds": seconds,
              "played_seconds": round(played, 3) if played is not None else None,
              "text_segments": len(segments), "text_characters": len(transcript), "terminal": terminal,
              "matched_fixture_words": sorted(fixture_words),
              "metrics": metrics, "database_sink": "three-function durable local JSONL test double",
              "production_database_used": False, "backend_used": False, "external_network_used": False,
              "production_transcription_and_archive_spool": True}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
