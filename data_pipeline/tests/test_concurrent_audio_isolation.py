"""Independent audio sessions, including an opt-in real three-browser smoke.

RUN_CONCURRENT_AUDIO_SMOKE=1 runs Chromium, PulseAudio and FFmpeg against
three loopback-only players. No STT model, production DB or external service
is used. The production shell, browser agent and manager are exercised.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
import uuid
import wave

from data_pipeline.stt_worker.manager import STTWorkerManager


class ConcurrentAudioEnvironmentTests(unittest.TestCase):
    def test_cleanup_minimum_cannot_be_shortened_but_can_be_extended(self):
        for configured in ("1", "invalid", "nan", "inf"):
            with self.subTest(configured=configured), patch.dict(os.environ, {"WEBCAST_CLEANUP_GRACE_SECONDS": configured}):
                self.assertEqual(STTWorkerManager._cleanup_grace_seconds(10), 30)
        with patch.dict(os.environ, {"WEBCAST_CLEANUP_GRACE_SECONDS": "40"}):
            self.assertEqual(STTWorkerManager._cleanup_grace_seconds(10), 40)
            self.assertEqual(STTWorkerManager._cleanup_grace_seconds(50), 50)

    def environment(self, attempt="attemptone", route=1, **overrides):
        call = {"id": 81234, "ticker": "TEST", "ir_url": "https://example.test/events",
                "schedule_revision": 2, "_live_attempt_id": attempt,
                "_live_route_attempt": route, "_capture_session_id": "captureone"}
        with patch("data_pipeline.stt_worker.manager.live_runtime.prepare_attempt", return_value={}):
            return STTWorkerManager._probe_runtime_environment(call, overrides)

    def test_attempt_and_route_use_different_audio_without_losing_login(self):
        first = self.environment()
        replacement = self.environment(attempt="attempttwo")
        next_route = self.environment(route=2)
        self.assertEqual(len({e["WEBCAST_PULSE_SINK"] for e in (first, replacement, next_route)}), 3)
        for other in (replacement, next_route):
            self.assertEqual(first["WEBCAST_STORAGE_STATE"], other["WEBCAST_STORAGE_STATE"])
            self.assertNotEqual(first["WEBCAST_PLAYBACK_READY_FILE"], other["WEBCAST_PLAYBACK_READY_FILE"])

    def test_rebuilding_same_attempt_keeps_the_promotable_audio_session(self):
        first = self.environment()
        self.assertEqual(first["WEBCAST_PULSE_SINK"], self.environment(**first)["WEBCAST_PULSE_SINK"])

    def test_shared_daemon_and_fixed_viewer_overrides_are_disabled(self):
        overrides = {"WEBCAST_PULSE_RUNTIME_DIR": "/tmp/shared/pulse",
                     "WEBCAST_XDG_RUNTIME_DIR": "/tmp/shared",
                     "WEBCAST_VNC_ENABLED": "true", "WEBCAST_USE_HOST_DISPLAY": "true"}
        with patch.dict(os.environ, overrides):
            runtime = self.environment(**overrides)
            effective = {**os.environ, **runtime}
        self.assertEqual(effective["WEBCAST_PULSE_RUNTIME_DIR"], "")
        self.assertEqual(effective["WEBCAST_XDG_RUNTIME_DIR"], "")
        self.assertEqual(effective["WEBCAST_VNC_ENABLED"], "false")
        self.assertEqual(effective["WEBCAST_USE_HOST_DISPLAY"], "false")

    def test_term_during_exit_cleanup_does_not_leave_the_private_runtime(self):
        """Execute the production trap functions; no browser/audio dependency."""
        source = (Path(__file__).resolve().parents[1] / "scripts" / "run_webcast_audio_capture.sh").read_text()
        functions = source[source.index("terminate_child() {"):source.index("# Isolate PulseAudio per call.")]
        with tempfile.TemporaryDirectory(prefix="ew-cleanup-race-") as directory:
            runtime = Path(directory) / "runtime"
            runtime.mkdir()
            script = "set -euo pipefail\n" + functions + '''
PULSE_SINK_NAME=test_cleanup
PULSE_RUNTIME_DIR_OWNED=true
XDG_RUNTIME_DIR="$1"
# Model the bounded child drain inside the production EXIT cleanup.
terminate_child() { sleep 0.15; }
pulseaudio() { return 0; }
exit 75
'''
            process = subprocess.Popen(["bash", "-c", script, "cleanup-test", str(runtime)],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                # The first log is emitted only after cleanup masks TERM.
                first = process.stdout.readline().decode()
                self.assertIn("CAPTURE_CLEANUP_STARTED", first)
                os.kill(process.pid, signal.SIGTERM)
                output, _ = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 75, output.decode())
                self.assertIn("CAPTURE_CLEANUP_DONE", output.decode())
                self.assertFalse(runtime.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()


class CaptureCleanupDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_timed_out_probe_and_stopped_capture_share_cleanup_budget(self):
        wait_for = asyncio.wait_for
        timeouts = []

        async def observe(awaitable, timeout):
            timeouts.append(timeout)
            return await wait_for(awaitable, timeout)

        process = SimpleNamespace(pid=None, returncode=None, terminate=Mock(), kill=Mock(),
                                  wait=AsyncMock(return_value=75))
        communicate = asyncio.create_task(asyncio.sleep(0, result=(b"closed", b"")))
        with patch.dict(os.environ, {"WEBCAST_CLEANUP_GRACE_SECONDS": "35",
                                    "DATE_STREAM_PROBE_TERMINATE_GRACE_SECONDS": "1"}), \
                patch("data_pipeline.stt_worker.manager.asyncio.wait_for", side_effect=observe):
            self.assertEqual(await STTWorkerManager._terminate_probe_process(process, communicate),
                             (b"closed", b""))
            await STTWorkerManager._terminate_capture_process(process, grace_seconds=1)
        self.assertEqual(timeouts, [35, 35])
        process.kill.assert_not_called()

    async def test_unresponsive_abort_still_allows_complete_cleanup_after_term(self):
        wait_for = asyncio.wait_for
        timeouts = []

        async def observe(awaitable, timeout):
            timeouts.append(timeout)
            return await wait_for(awaitable, timeout)

        process = SimpleNamespace(pid=None, terminate=Mock(), kill=Mock(),
                                  wait=AsyncMock(side_effect=[TimeoutError, 75]))
        with tempfile.TemporaryDirectory() as directory:
            held = SimpleNamespace(abort_file=str(Path(directory) / "abort"), process=process,
                                   output_task=asyncio.create_task(asyncio.sleep(0)))
            with patch.dict(os.environ, {"WEBCAST_CLEANUP_GRACE_SECONDS": "30"}), \
                    patch("data_pipeline.stt_worker.manager.asyncio.wait_for", side_effect=observe):
                await STTWorkerManager()._stop_promotable_probe(held)
        self.assertEqual(timeouts, [30, 30, 2])
        process.terminate.assert_called_once()
        process.kill.assert_not_called()


def tone_wav(frequency: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"".join(struct.pack("<h", int(10000 * math.sin(
            2 * math.pi * frequency * sample / 16000))) for sample in range(32000)))
    return output.getvalue()


@unittest.skipUnless(os.getenv("RUN_CONCURRENT_AUDIO_SMOKE") == "1",
                     "requires Chromium, PulseAudio and FFmpeg")
class ThreeBrowserAudioIsolationSmoke(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ew-audio-isolation-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.frequencies = (440, 660, 880)
        self.tickers = ("TONEA", "TONEB", "TONEC")
        self.today = datetime.now(timezone.utc).date()
        day = self.today.strftime("%B %d, %Y")
        pages = {}
        for ticker, frequency in zip(self.tickers, self.frequencies):
            pages[f"/{ticker}.wav"] = (tone_wav(frequency), "audio/wav")
            pages[f"/{ticker}/player"] = ((
                f'<h1>{ticker} quarterly earnings call {day}</h1>'
                f'<audio src="/{ticker}.wav" controls loop></audio>'
                '<button onclick="document.querySelector(\'audio\').play();this.remove()">'
                'Play webcast</button>').encode(), "text/html")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                content, kind = pages.get(self.path, (b"missing", "text/plain"))
                self.send_response(200 if self.path in pages else 404)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.env = patch.dict(os.environ, {
            "WEBCAST_CAPTURE_RUNNER": "container", "WEBCAST_HEADED": "true",
            "WEBCAST_LIFECYCLE": "live", "WEBCAST_LIVE_DIAGNOSTICS": "false",
            "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false", "WEBCAST_VISION_ENABLED": "false",
            "WEBCAST_ARTIFACTS_DIR": str(self.directory), "WEBCAST_SAVE_STORAGE_STATE": "",
            "WEBCAST_STORAGE_STATE": "", "WEBCAST_HOLD_SECONDS": "120",
            "WEBCAST_AUDIO_WARMUP_SECONDS": "0", "WEBCAST_SPEECH_PREFLIGHT_ENABLED": "false",
            "WEBCAST_POST_REGISTRATION_PLAYBACK_WAIT_SECONDS": "2",
            "WEBCAST_PAGE_READY_TIMEOUT_SECONDS": "5", "WEBCAST_CONTROL_TIMEOUT_SECONDS": "5",
            "WEBCAST_PROBE_PROMOTION_ENABLED": "true", "WEBCAST_PROBE_PROMOTION_TIMEOUT_SECONDS": "150",
            "WEBCAST_HUMAN_LOOP_ENABLED": "false", "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "false",
            "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION": "true", "WEBCAST_DIRECT_TARGET_URL": "",
            "WEBCAST_TARGET_IDENTITY_READY_FILE": "", "WEBCAST_LIVE_IDENTITY_PROOF": "",
            "DATE_STREAM_AUDIO_WAIT_SECONDS": "10", "DATE_STREAM_AUDIO_PROBE_SECONDS": "1",
            "STT_PCM_HANDOFF_ENABLED": "false", "DB_URL": "sqlite:///:memory:",
            "SEND_TO_AI_ENGINE": "false", "SEND_TO_BACKEND": "false",
            "TRANSCRIPT_ARCHIVE_ENABLED": "false", "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.manager = STTWorkerManager()
        self.calls = []
        self.environments = {}
        for index, ticker in enumerate(self.tickers):
            route = f"{self.base}/{ticker}/player"
            call = {"id": 89100 + index, "ticker": ticker, "ir_url": route,
                    "webcast_date": self.today, "scheduled_at_utc": datetime.now(timezone.utc),
                    "_live_attempt_id": uuid.uuid4().hex, "_live_route_attempt": 1,
                    "_capture_session_id": f"{ticker}-{uuid.uuid4().hex[:12]}",
                    "_live_entrypoint_kind": "event_url", "_live_entrypoint_url": route,
                    "_live_discovery_proof": {"verified": True, "call_ticker": ticker,
                        "target_date": self.today.isoformat(), "source_url": self.base + "/events",
                        "target_url": route, "observed_at": datetime.now(timezone.utc).isoformat(),
                        "evidence": f"{ticker} quarterly earnings call {day}"}}
            self.calls.append(call)
            self.addAsyncCleanup(self.manager.discard_promotable_probe, call)

    async def record(self, call, seconds=3):
        env = self.environments[call["ticker"]]
        sink = env["WEBCAST_PULSE_SINK"]
        runtime = f"/tmp/ew-pulse-{os.getuid()}/{sink}"
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "pulse", "-i", env["STT_INPUT_SOURCE"], "-t", str(seconds),
            "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env, "XDG_RUNTIME_DIR": runtime,
                 "PULSE_RUNTIME_PATH": runtime + "/pulse", "PULSE_SERVER": "unix:" + runtime + "/pulse/native"})
        try:
            pcm, error = await asyncio.wait_for(process.communicate(), timeout=seconds + 15)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        self.assertEqual(process.returncode, 0, error.decode(errors="replace"))
        self.assertGreaterEqual(len(pcm), seconds * 16000 * 2 * .95)
        return pcm

    def check_tone(self, pcm, own_frequency):
        import numpy as np
        values = np.frombuffer(pcm, dtype="<i2").astype(float)
        # Drop startup buffer and window the remainder to bound spectral leakage.
        values = values[8000:]
        self.assertGreater(float(np.sqrt(np.mean(values ** 2))), 1000)
        spectrum = np.abs(np.fft.rfft(values * np.hanning(len(values))))
        frequencies = np.fft.rfftfreq(len(values), 1 / 16000)
        bands = {frequency: float(np.max(spectrum[np.abs(frequencies - frequency) <= 5]))
                 for frequency in self.frequencies}
        self.assertEqual(max(bands, key=bands.get), own_frequency)
        ratios = {frequency: magnitude / bands[own_frequency] for frequency, magnitude in bands.items()
                  if frequency != own_frequency}
        self.assertLess(max(ratios.values()), .03, f"cross-call audio detected: {ratios}")
        return {"frequency_hz": own_frequency, "other_tone_amplitude_ratios": ratios,
                "pcm_bytes": len(pcm)}

    async def test_three_real_browsers_do_not_mix_and_one_cleanup_preserves_two(self):
        settings = {name: value for name, value in os.environ.items()
                    if name.startswith(("WEBCAST_", "STT_", "DATE_STREAM_"))}
        results = await asyncio.gather(*(self.manager.probe_webcast_url_detailed(
            call, capture_env={**settings, "STT_CAPTURE_SESSION_ID": call["_capture_session_id"]},
            timeout_seconds=100) for call in self.calls))
        for call, result in zip(self.calls, results):
            self.assertTrue(result.audible, f"{call['ticker']}: {result.error}\n{result.output}")
            self.environments[call["ticker"]] = result.runtime_environment
        sinks = {env["WEBCAST_PULSE_SINK"] for env in self.environments.values()}
        self.assertEqual(len(sinks), 3)
        self.assertEqual(len(self.manager._promotable_probes), 3)
        before = [self.check_tone(pcm, frequency) for pcm, frequency in zip(
            await asyncio.gather(*(self.record(call) for call in self.calls)), self.frequencies)]
        stopped = self.calls[0]
        stopped_process = self.manager._promotable_probes[self.manager._build_call_id(stopped)].process
        stopped_held = self.manager._promotable_probes[self.manager._build_call_id(stopped)]
        await self.manager.discard_promotable_probe(stopped)
        self.assertIsNotNone(stopped_process.returncode)
        self.assertEqual(stopped_process.returncode, 75, self.manager._probe_output_text(stopped_held.output_tail))
        self.assertIn("CAPTURE_CLEANUP_DONE", self.manager._probe_output_text(stopped_held.output_tail))
        stopped_runtime = Path(f"/tmp/ew-pulse-{os.getuid()}") / self.environments[stopped["ticker"]]["WEBCAST_PULSE_SINK"]
        remaining = sorted(str(path.relative_to(stopped_runtime)) for path in stopped_runtime.rglob("*"))[:20]
        self.assertFalse(stopped_runtime.exists(), "Stopped call's private Pulse runtime was not removed: "
                         + json.dumps({"remaining_paths": remaining}) + "\n"
                         + self.manager._probe_output_text(stopped_held.output_tail)[-2000:])
        for call in self.calls[1:]:
            held = self.manager._promotable_probes[self.manager._build_call_id(call)]
            self.assertIsNone(held.process.returncode, "Another call's cleanup stopped this browser")
        after = [self.check_tone(pcm, frequency) for pcm, frequency in zip(
            await asyncio.gather(*(self.record(call) for call in self.calls[1:])), self.frequencies[1:])]
        print("CONCURRENT_AUDIO_ISOLATION_RESULT=" + json.dumps({
            "real_browser_count": 3, "distinct_pulse_servers": len(sinks),
            "before_one_call_stopped": before, "after_one_call_stopped": after,
            "stt_model_used": False, "external_services_used": False,
        }, sort_keys=True), flush=True)
