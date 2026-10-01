"""Cross-component contracts after splitting the pipeline's implementations."""

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from data_pipeline import database
from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
from data_pipeline.collectors.streams.browser.stages import BrowserStages
from data_pipeline.orchestrator import EarningsOrchestrator
from data_pipeline.storage import connection, live_calls, transcripts


ROOT = Path(__file__).resolve().parents[2]


class ComponentWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_pending_probe_then_ready_capture_use_same_injected_parts(self):
        call = {"id": 7, "ticker": "EWTEST", "ir_url": "https://example.test/events"}
        repository = mock.Mock()
        repository.get_date_based_stream_candidates.return_value = [call]
        repository.claim_stream_probe.return_value = True
        repository.record_stream_probe.return_value = {}
        repository.mark_call_running.return_value = True
        worker = mock.Mock()
        worker.discover_date_based_call = None
        worker.occupied_capture_keys.return_value = set()
        worker.active_capture_count.return_value = 0
        worker.build_isolated_capture_environment.return_value = {"WEBCAST_LIFECYCLE": "live"}
        worker.probe_date_based_call = mock.AsyncMock(side_effect=[(False, "not live yet"), (True, None)])
        worker.launch_date_based_audio_capture = mock.AsyncMock()
        pipeline = EarningsOrchestrator(repository=repository, worker_manager=worker)
        with mock.patch.dict(os.environ, {
            "DATE_STREAM_MAINTENANCE_START": "",
            "DATE_STREAM_MAINTENANCE_END": "",
            "DATE_STREAM_WATCH_TICKERS": "",
            "DATE_STREAM_WATCH_CONCURRENCY": "1",
            "DATE_STREAM_AUTO_CAPTURE_ENABLED": "true",
        }), mock.patch.object(pipeline.health, "record_event"):
            self.assertEqual(await pipeline.dispatch_date_based_streams(), 1)
            await asyncio.gather(*list(pipeline.live_watch._date_stream_background_tasks.values()))
            worker.launch_date_based_audio_capture.assert_not_called()
            repository.mark_call_running.assert_not_called()

            self.assertEqual(await pipeline.dispatch_date_based_streams(), 1)
            await asyncio.gather(*list(pipeline.live_watch._date_stream_background_tasks.values()))
            worker.launch_date_based_audio_capture.assert_awaited_once()
            session_id = repository.mark_call_running.call_args.kwargs["capture_session_id"]
            launched = worker.launch_date_based_audio_capture.call_args.args[0]
            self.assertEqual(launched["_capture_session_id"], session_id)
            self.assertIs(pipeline.schedules, pipeline.live_watch.schedules)
            self.assertIs(pipeline.health, pipeline.housekeeping.health)

    async def test_player_component_can_be_replaced_without_changing_agent(self):
        activate = mock.AsyncMock(return_value=True)
        stages = replace(BrowserStages(), playback=SimpleNamespace(trigger_media_playback=activate))
        agent = BrowserWebcastAgent("EWTEST", "https://example.test/events", stages=stages)
        page = object()
        self.assertTrue(await agent.trigger_media_playback(page))
        activate.assert_awaited_once_with(
            agent,
            page,
            allow_control_scan=True,
            page_scope_only=False,
            require_active_confirmation=False,
        )

    def test_database_facade_exports_canonical_storage_functions(self):
        self.assertIs(database.engine, connection.engine)
        self.assertIs(database.archive_transcript_segment, transcripts.archive_transcript_segment)
        self.assertIs(database.complete_call_capture_from_transcript, live_calls.complete_call_capture_from_transcript)

    def test_server_and_delivery_imports_do_not_load_whisper(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import sys; import data_pipeline.orchestrator; import data_pipeline.stt_worker.delivery; assert 'faster_whisper' not in sys.modules; assert 'data_pipeline.stt_worker.take' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_file_entrypoint_imports_share_the_same_database_pool(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import sys; sys.path.insert(0, 'data_pipeline'); import database, orchestrator, scheduler; from data_pipeline.storage import connection; assert database.engine is connection.engine; assert orchestrator.EarningsOrchestrator().worker_manager is not None"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_browser_and_stt_cli_arguments_still_parse(self):
        for module in ("data_pipeline.collectors.streams.browser_webcast", "data_pipeline.stt_worker.take"):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-B", "-m", module, "--help"],
                    cwd=ROOT, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--ticker", result.stdout)
