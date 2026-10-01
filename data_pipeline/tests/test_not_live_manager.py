"""A confirmed waiting room is retried without selecting historical alternatives."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from data_pipeline.stt_worker.manager import STTWorkerManager, WebcastProbeResult
from data_pipeline.storage.policies import stream_probe_retry_policy


class NotLiveManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = STTWorkerManager()
        self.manager._probe_heartbeat_loop = AsyncMock()
        self.call = {
            "id": 797, "ticker": "LEN", "earning_at": "2026-09-17",
            "webcast_url": "https://app.webinar.net/target-event",
            "event_url": "https://issuer.invalid/older-event",
            "ir_url": "https://issuer.invalid/ir",
        }
        self.verified = {"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "true"}
        self.env = patch.dict(os.environ, {"DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS": "0"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_confirmed_wait_keeps_route_and_next_watch_can_capture(self):
        error = "NOT_LIVE_YET The webinar has not quite started"
        self.manager.probe_webcast_url_detailed = AsyncMock(side_effect=[
            WebcastProbeResult(False, error,
                               "webcast target opened: https://app.webinar.net/target-event/live", 1, self.verified),
            WebcastProbeResult(True, None, "AUDIO_DETECTED", 0, self.verified),
        ])
        with patch.object(self.manager, "_write_capture_manifest", return_value=None):
            ready, detail = await self.manager.probe_date_based_call(self.call)
            self.assertFalse(ready)
            self.assertIn("NOT_LIVE_YET", detail)
            self.assertEqual(self.manager.probe_webcast_url_detailed.await_count, 1)
            self.assertEqual(self.manager._entrypoint_retry_not_before, {})
            self.assertEqual(stream_probe_retry_policy(detail, watch_state="event_window")["retry_delay_minutes"], 1)
            ready, detail = await self.manager.probe_date_based_call(self.call)
        self.assertTrue(ready, detail)
        attempts = self.manager.probe_webcast_url_detailed.await_args_list
        self.assertEqual([a.args[0]["_live_entrypoint_kind"] for a in attempts], ["webcast_url", "webcast_url"])
        self.assertEqual(attempts[1].kwargs["capture_env"]["WEBCAST_LIVE_EXCLUDED_URLS"], "")

    async def test_unverified_wait_does_not_suppress_other_routes(self):
        self.manager.probe_webcast_url_detailed = AsyncMock(side_effect=[
            WebcastProbeResult(False, "NOT_LIVE_YET unrelated event", "", 1,
                               {"WEBCAST_LIVE_ENTRYPOINT_VERIFIED": "false"}),
            WebcastProbeResult(True, None, "AUDIO_DETECTED", 0, self.verified),
        ])
        with patch.object(self.manager, "_write_capture_manifest", return_value=None):
            ready, detail = await self.manager.probe_date_based_call(self.call)
        self.assertTrue(ready, detail)
        self.assertEqual(self.manager.probe_webcast_url_detailed.await_count, 2)
        self.assertEqual(self.manager.probe_webcast_url_detailed.await_args.args[0]["_live_entrypoint_kind"], "event_url")

    async def test_wait_marker_survives_truncated_error_tail(self):
        self.manager.probe_webcast_url_detailed = AsyncMock(return_value=WebcastProbeResult(
            False, "audio probe failed (exit=1): browser exited", "[LEN] NOT_LIVE_YET correct event is waiting\ncleanup", 1, self.verified,
        ))
        ready, detail = await self.manager.probe_date_based_call(self.call)
        self.assertFalse(ready)
        self.assertIn("NOT_LIVE_YET", detail)
        self.assertEqual(self.manager.probe_webcast_url_detailed.await_count, 1)
