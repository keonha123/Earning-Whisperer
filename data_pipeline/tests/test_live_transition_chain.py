"""Continuous watch transition with real discovery, Chromium, and PulseAudio.

The capture smoke test replaces storage with an in-memory lease repository and
the final STT launch with a recorder. Discovery, event proof, waiting detection,
candidate retry, browser playback, and virtual-audio checks are production code.
It requires RUN_LOCAL_CAPTURE_SMOKE=1 inside the browser-webcast image. No model,
external website, production database, or backend is contacted.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import wave

from data_pipeline.application.live_watch import LiveWatchService
from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.navigation import make_target_proof
from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.storage.policies import stream_probe_retry_policy


class MemoryLeaseRepository:
    """Advance only the repository's clock, preserving the real retry policy."""
    def __init__(self, call):
        self.call = call
        self.clock = 0
        self.retry_at = 0
        self.claimed = False
        self.running = False
        self.results = []
        self.claims = 0

    def get_date_based_stream_candidates(self, **kwargs):
        if self.claimed or self.running or self.clock < self.retry_at:
            return []
        return [dict(self.call)]

    def claim_stream_probe(self, call_id, **kwargs):
        if not self.get_date_based_stream_candidates():
            return False
        self.claimed = True
        self.claims += 1
        return True

    def record_stream_probe(self, call_id, *, stream_ready, error, watch_state, **kwargs):
        self.claimed = False
        policy = stream_probe_retry_policy(error, watch_state=watch_state)
        self.retry_at = self.clock if stream_ready else self.clock + policy["retry_delay_minutes"] * 60
        self.results.append({"ready": stream_ready, "error": error, "policy": policy})
        return policy

    def mark_call_running(self, call_id, **kwargs):
        self.running = True
        return True

    def requeue_failed_call_capture(self, call_id, **kwargs):
        self.running = False
        return True


class MemoryHealth:
    def __init__(self):
        self.events = []

    def record_event(self, event_type, **kwargs):
        self.events.append({"event_type": event_type, **kwargs})

    def database_recovered(self, *args):
        pass

    def database_unavailable(self, *args):
        raise AssertionError("Test must not access a database")


def _tone_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(32000)))
    return output.getvalue()


@unittest.skipUnless(os.getenv("RUN_LOCAL_CAPTURE_SMOKE") == "1", "requires Chromium, PulseAudio, and FFmpeg")
class LiveTransitionChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.phase = "absent"
        self.requests = []
        self.today = datetime.now(timezone.utc).date()
        day = self.today.strftime("%B %d, %Y")
        old_day = (self.today - timedelta(days=90)).strftime("%B %d, %Y")
        tone = _tone_wav()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append((owner.phase, self.path))
                if self.path == "/audio.wav":
                    content, kind = tone, "audio/wav"
                else:
                    if self.path == "/events":
                        link = '<a href="/player/current">Watch earnings webcast</a>' if owner.phase != "absent" else '<span>Webcast link available soon</span>'
                        body = (f'<h1>Investor Events</h1><article><h2>CONT earnings call {day}</h2>{link}</article>'
                                f'<article><p>{old_day} prior earnings call</p><a href="/player/old">Watch webcast</a></article>')
                    elif self.path == "/player/current":
                        body = f'<h1>CONT quarterly earnings call {day}</h1>'
                        if owner.phase.startswith("waiting"):
                            body += f'<div role="dialog">The webcast has not quite started. It is scheduled for {day}. Earnings call starts shortly.</div>'
                        else:
                            body += '''<button id="enter" onclick="document.querySelector('audio').play();fetch('/entered');this.remove()">Enter webcast</button>
                                <audio src="/audio.wav" loop controls></audio>'''
                    elif self.path == "/entered":
                        body = "entered"
                    else:
                        body = '<h1>Wrong historical event</h1>'
                    content, kind = body.encode(), "text/html"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {
            "WEBCAST_CAPTURE_RUNNER": "container", "WEBCAST_HEADED": "true",
            "WEBCAST_LIFECYCLE": "live", "WEBCAST_LIVE_DIAGNOSTICS": "false",
            "WEBCAST_GENERALIZED_LEARNING_ENABLED": "false", "WEBCAST_VISION_ENABLED": "false",
            "WEBCAST_ARTIFACTS_DIR": self.directory.name, "WEBCAST_SAVE_STORAGE_STATE": "",
            "WEBCAST_STORAGE_STATE": "", "WEBCAST_HOLD_SECONDS": "20",
            "WEBCAST_AUDIO_WARMUP_SECONDS": "0", "WEBCAST_SPEECH_PREFLIGHT_ENABLED": "false",
            "WEBCAST_POST_REGISTRATION_PLAYBACK_WAIT_SECONDS": "2", "WEBCAST_CONTROL_TIMEOUT_SECONDS": "5",
            "WEBCAST_PAGE_READY_TIMEOUT_SECONDS": "2", "WEBCAST_PROBE_PROMOTION_ENABLED": "true",
            "WEBCAST_HUMAN_LOOP_ENABLED": "false", "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "false",
            "WEBCAST_TARGET_IDENTITY_READY_FILE": "", "WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION": "true",
            "WEBCAST_DIRECT_TARGET_URL": "", "WEBCAST_LIVE_IDENTITY_PROOF": "",
            "DATE_STREAM_WATCH_TICKERS": "CONT", "DATE_STREAM_DISCOVERY_ENABLED": "true",
            "DATE_STREAM_DISCOVERY_HEADED": "true", "DATE_STREAM_DISCOVERY_TIMEOUT_SECONDS": "45",
            "DATE_STREAM_WATCH_CONCURRENCY": "1", "DATE_STREAM_CAPTURE_CONCURRENCY": "1",
            "DATE_STREAM_AUTO_CAPTURE_ENABLED": "true", "DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS": "0",
            "DATE_STREAM_CANDIDATE_ATTEMPTS": "1", "DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS": "65",
            "DATE_STREAM_AUDIO_WAIT_SECONDS": "6", "DATE_STREAM_AUDIO_PROBE_SECONDS": "1",
            "DATE_STREAM_MAINTENANCE_START": "", "DATE_STREAM_MAINTENANCE_END": "",
            "DB_URL": "sqlite:///:memory:", "SEND_TO_AI_ENGINE": "false", "SEND_TO_BACKEND": "false",
            "TRANSCRIPT_ARCHIVE_ENABLED": "false", "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.call = {"id": 919191, "ticker": "CONT", "earning_at": self.today.isoformat(),
                     "webcast_date": self.today, "scheduled_at_utc": datetime.now(timezone.utc),
                     "call_year": self.today.year, "quarter": "Q3", "ir_url": self.base + "/events"}
        self.repo = MemoryLeaseRepository(self.call)
        self.health = MemoryHealth()
        self.manager = STTWorkerManager()
        # This boundary only renews a DB lease, which the in-memory fixture owns.
        self.manager._probe_heartbeat_loop = AsyncMock()
        self.dispatches = []

        async def record_dispatch(call, *, capture_env):
            held = self.manager._promotable_probes.get(self.manager._build_call_id(call))
            self.assertIsNotNone(held, "Real PulseAudio probe must hold its existing browser")
            output = self.manager._probe_output_text(held.output_tail)
            self.assertIn("AUDIO_DETECTED", output)
            self.assertIn("PLAYBACK_READY_CONFIRMED", output)
            self.dispatches.append({"call": dict(call), "output": output,
                                    "ready_file": capture_env["WEBCAST_AUDIO_READY_FILE"]})
            # Test scope ends at dispatch; no Whisper or downstream side effects.
            await self.manager.discard_promotable_probe(call)

        self.manager.launch_date_based_audio_capture = record_dispatch
        self.addAsyncCleanup(self.manager.discard_promotable_probe, self.call)
        self.service = LiveWatchService(self.repo, self.manager, SimpleNamespace(), self.health)

    async def tick(self):
        dispatched = await self.service.dispatch_date_based_streams()
        tasks = list(self.service._date_stream_background_tasks.values())
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=90)
        return dispatched

    async def test_absent_waiting_twice_then_real_audio_dispatch_without_restart(self):
        scheduler_identity = id(self.service), id(self.manager)
        self.assertEqual(await self.tick(), 1)
        self.assertFalse(self.repo.results[-1]["ready"])
        self.assertEqual(self.dispatches, [])
        self.assertFalse(any(path == "/player/current" for _, path in self.requests))

        for phase in ("waiting_first", "waiting_second"):
            self.phase = phase
            self.assertEqual(await self.tick(), 0, "Cooldown must actually prevent an early retry")
            self.repo.clock = self.repo.retry_at
            self.assertEqual(await self.tick(), 1)
            self.assertIn("NOT_LIVE_YET", self.repo.results[-1]["error"])
            self.assertFalse(self.repo.results[-1]["ready"])
            self.assertEqual(self.repo.results[-1]["policy"]["retry_delay_minutes"], 1)
            self.assertEqual(self.dispatches, [])
            self.assertEqual(self.manager._entrypoint_retry_not_before, {})
            self.assertEqual(sum(p == phase and path == "/player/current"
                                 for p, path in self.requests), 1,
                             "A confirmed waiting event must not be reopened through alternate entrypoints")
            self.assertFalse(self.repo.claimed)
            self.assertEqual(self.service._capture_reservations, set())
            self.assertFalse(self.manager.occupied_capture_keys())

        self.phase = "live"
        self.repo.clock = self.repo.retry_at
        self.assertEqual(await self.tick(), 1)
        self.assertEqual((id(self.service), id(self.manager)), scheduler_identity)
        self.assertEqual(self.repo.claims, 4)
        self.assertEqual(len(self.dispatches), 1)
        self.assertTrue(self.repo.results[-1]["ready"])
        self.assertTrue(self.repo.running)
        self.assertIn(("live", "/entered"), self.requests)
        self.assertFalse(any(path == "/player/old" for _, path in self.requests))
        self.assertFalse(any(path == "/entered" and phase != "live" for phase, path in self.requests))
        statuses = [event.get("status") for event in self.health.events if event["event_type"] == "discovery_result"]
        self.assertEqual(statuses, ["pending", "target_found", "target_found", "target_found"])
        self.assertEqual(sum(e["event_type"] == "capture_started" for e in self.health.events), 1)
        self.assertEqual(self.service._capture_reservations, set())
        print("LIVE_TRANSITION_CHAIN_RESULT=" + json.dumps({
            "phases": ["link_absent", "waiting_first", "waiting_second", "live"],
            "scheduler_restarts": 0, "probe_claims": self.repo.claims,
            "real_browser_and_pulse": True, "capture_dispatches": len(self.dispatches),
            "wrong_event_requests": sum(path == "/player/old" for _, path in self.requests),
            "stt_executed": False, "production_database_used": False,
        }, sort_keys=True), flush=True)


@unittest.skipUnless(os.getenv("RUN_LOCAL_BROWSER_SMOKE") == "1", "requires Chromium")
class UndatedWaitingModalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.addAsyncCleanup(self.pw.stop)
        self.browser = await self.pw.chromium.launch(headless=True, args=["--no-sandbox"])
        self.addAsyncCleanup(self.browser.close)
        self.context = await self.browser.new_context()
        await self.context.route("**/*", lambda route: route.fulfill(body="<body></body>", content_type="text/html"))
        self.page = await self.context.new_page()
        self.url = "https://app.webinar.net/currentEvent"
        await self.page.goto(self.url + "/live")
        with patch.dict(os.environ, {"WEBCAST_LIFECYCLE": "live", "WEBCAST_TARGET_DATE": "2026-09-17",
                "WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false", "WEBCAST_LIVE_DIAGNOSTICS": "false"}, clear=True):
            self.agent = BrowserWebcastAgent("CONT", self.url)
        self.agent.live_target_proof = make_target_proof(self.agent, "https://issuer.invalid/events", self.url,
                                                       "September 17, 2026 CONT earnings call")

    async def test_proven_explicit_undated_modal_waits_then_real_page_change_releases_it(self):
        await self.page.set_content('<h1>CONT earnings call</h1><div role="dialog">The webinar has not quite started.</div>')
        self.assertIsNotNone(await self.agent._detect_not_live_event(self.page))
        await self.page.set_content('<h1>CONT earnings call</h1><button>Enter webcast</button>')
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_generic_hidden_foreign_and_unproven_undated_text_cannot_delay(self):
        for body in (
            '<h1>CONT earnings call</h1><div>The webinar has not quite started.</div>',
            '<div role="dialog" style="display:none">The webinar has not quite started.</div>',
            '<h1>CONT earnings call September 18, 2026</h1><div role="dialog">The webinar has not quite started.</div>',
            '<div role="dialog">Investor day webinar has not quite started.</div>',
        ):
            with self.subTest(body=body):
                await self.page.set_content(body)
                self.assertIsNone(await self.agent._detect_not_live_event(self.page))
        await self.page.set_content('<div role="dialog">The webinar has not quite started.</div>')
        self.agent.live_target_proof = None
        self.assertIsNone(await self.agent._detect_not_live_event(self.page))

    async def test_undated_modal_cannot_override_explicit_ticker_or_period(self):
        self.agent.target_year = 2026
        self.agent.target_quarter = "Q3"
        for label in ("Ticker: MSFT earnings call", "CONT Q1 2027 earnings call"):
            with self.subTest(label=label):
                await self.page.set_content(
                    '<h1>CONT earnings call</h1><div role="dialog">'
                    + label + '. The webinar has not quite started.</div>'
                )
                self.assertIsNone(await self.agent._detect_not_live_event(self.page))
