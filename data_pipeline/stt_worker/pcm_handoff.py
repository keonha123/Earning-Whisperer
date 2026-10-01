"""Bounded per-call PCM handoff across browser probe and STT promotion.

The producer writes 16 kHz mono s16le once. A later consumer follows from byte
zero, retaining speech during preflight/model startup. Files are private,
limited in size, and retained by the supervisor after incomplete captures.
"""
from __future__ import annotations
import argparse
from array import array
import math
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from data_pipeline.live_telemetry import emit_live_event
from data_pipeline.stt_worker.audio_rescue import _write_private_json, process_identity


def record_pcm(path: Path, command: list[str], *, max_bytes: int) -> int:
    done = Path(str(path) + '.done')
    path.parent.mkdir(parents=True, exist_ok=True)
    done.unlink(missing_ok=True)
    code, total = 1, 0
    process = None
    stopping = False
    drain_deadline = None
    last_report = time.monotonic()
    try:
        report_interval = max(.1, float(os.getenv("STT_AUDIO_PROGRESS_INTERVAL_SECONDS", "10")))
        if not math.isfinite(report_interval):
            report_interval = 10
    except ValueError:
        report_interval = 10
    last_signal = last_report
    previous_total = 0
    squares, peak, samples = 0, 0, 0
    def stop(_signal, _frame):
        nonlocal stopping, drain_deadline
        if stopping:
            return
        stopping = True
        drain_deadline = time.monotonic() + 5.0
        if process is not None and process.poll() is None:
            process.terminate()
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        # O_EXCL avoids following a stale/symlink path from another capture.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb', buffering=0) as output:
            try:
                _write_private_json(Path(str(path) + ".owner.json"), {
                    "pcm_name": path.name, **process_identity(os.getpid()),
                    "created_at": time.time(),
                })
            except (OSError, IndexError):
                pass
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=sys.stderr)
            # FFmpeg can flush final audio when asked to stop. Keep draining
            # its pipe before publishing .done, or the consumer's otherwise
            # correct EOF drain would still miss these final bytes.
            while True:
                if stopping and time.monotonic() >= drain_deadline:
                    code = 70
                    print('STT_PCM_DRAIN_TIMED_OUT', file=sys.stderr, flush=True)
                    break
                ready, _, _ = select.select([process.stdout], [], [], .25)
                now = time.monotonic()
                if now - last_report >= report_interval:
                    rms = math.sqrt(squares / samples) if samples else 0.0
                    emit_live_event("audio", "pcm_progress", status="warning" if now - last_signal >= 60 else "recording",
                                    progress=total > previous_total, pcm_bytes=total,
                                    bytes_per_second=round((total - previous_total) / (now - last_report), 2),
                                    rms_dbfs=round(20 * math.log10(rms / 32768), 2) if rms else None,
                                    peak_dbfs=round(20 * math.log10(peak / 32768), 2) if peak else None,
                                    signal_idle_seconds=round(now - last_signal, 2),
                                    audio_condition=("no_new_pcm" if not samples else "silent" if rms / 32768 <= 10 ** (-55 / 20) else "signal_present"),
                                    speech_classification="unknown", wrong_candidate=False)
                    os.fsync(output.fileno())
                    previous_total, last_report = total, now
                    squares, peak, samples = 0, 0, 0
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                chunk = os.read(process.stdout.fileno(), 32000)
                if not chunk:
                    break
                if total + len(chunk) > max_bytes:
                    code = 74
                    print('STT_PCM_SPOOL_LIMIT_REACHED', file=sys.stderr, flush=True)
                    break
                output.write(chunk)
                total += len(chunk)
                # Pulse produces bytes even during silence. Track signal
                # separately without assuming that music is speech/a wrong call.
                values = array("h", chunk[:len(chunk) - len(chunk) % 2])
                block_squares = sum(int(value) ** 2 for value in values)
                squares += block_squares
                samples += len(values)
                peak = max(peak, max((abs(value) for value in values), default=0))
                if values and math.sqrt(block_squares / len(values)) / 32768 > 10 ** (-55 / 20):
                    last_signal = time.monotonic()
            os.fsync(output.fileno())
            if code not in {70, 74}:
                code = 130 if stopping else process.wait(timeout=5)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        temporary = Path(str(done) + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as marker:
            json.dump({'exit_code': code, 'bytes': total}, marker)
        os.replace(temporary, done)
        emit_live_event('audio', 'pcm_closed', status='stopped', progress=True, pcm_bytes=total, exit_code=code)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return code


def follow_pcm(path: Path, output, *, producer_pid: int | None = None,
               idle_timeout: float = 45) -> int:
    done = Path(str(path) + '.done')
    last_data = time.monotonic()
    while not path.exists():
        if done.exists() or time.monotonic() - last_data > idle_timeout:
            return 70
        time.sleep(.05)
    with path.open('rb', buffering=0) as source:
        while True:
            chunk = source.read(32000)
            if chunk:
                output.write(chunk)
                output.flush()
                last_data = time.monotonic()
                continue
            if done.exists():
                # Read once more after observing producer completion, so its
                # last write cannot race the earlier EOF read.
                chunk = source.read(32000)
                if chunk:
                    output.write(chunk)
                    output.flush()
                    continue
                return int(json.loads(done.read_text())['exit_code'])
            if producer_pid:
                try:
                    os.kill(producer_pid, 0)
                except ProcessLookupError:
                    return 70
            if time.monotonic() - last_data > idle_timeout:
                return 70
            time.sleep(.05)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record')
    parser.add_argument('--follow')
    parser.add_argument('--producer-pid', type=int)
    parser.add_argument('--max-bytes', type=int, default=512 * 1024 * 1024)
    parser.add_argument('--idle-timeout', type=float, default=45)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.record:
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command or args.max_bytes < 32000:
            parser.error('record requires a command and max-bytes >= 32000')
        return record_pcm(Path(args.record), command, max_bytes=args.max_bytes)
    if args.follow:
        return follow_pcm(Path(args.follow), sys.stdout.buffer, producer_pid=args.producer_pid,
                          idle_timeout=args.idle_timeout)
    parser.error('choose --record or --follow')


if __name__ == '__main__':
    raise SystemExit(main())
