import asyncio
from datetime import date, datetime, timezone
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from data_pipeline.application.live_watch import LiveWatchService
from data_pipeline.collectors.schedules.event_routes import route_proof
from data_pipeline.stt_worker.manager import STTWorkerManager


def call(number):
    return {'id':number, 'ticker':f'TEST{number}', 'earning_at':'2026-09-17',
            'ir_url':f'https://issuer{number}.invalid/events'}


def discovery_result(item):
    return {'target_identity_verified':True, 'discovered_url':item['ir_url']+'/live',
            'identity_proof':{'verified':True,'call_ticker':item['ticker'],
                'target_date':'2026-09-17','source_url':item['ir_url'],
                'target_url':item['ir_url']+'/live','evidence':'target date earnings card',
                'observed_at':datetime.now(timezone.utc).isoformat()}}


class LiveWatchCapacityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'DATE_STREAM_DISCOVERY_ENABLED':'true',
            'DATE_STREAM_CAPTURE_CONCURRENCY':'1', 'DATE_STREAM_DISCOVERY_CONCURRENCY':'2',
            'DATE_STREAM_WATCH_CONCURRENCY':'1','DATE_STREAM_AUTO_CAPTURE_ENABLED':'true',
            'DATE_STREAM_MAINTENANCE_START':'','DATE_STREAM_MAINTENANCE_END':''})
        self.env.start(); self.addCleanup(self.env.stop)
        self.repo=Mock()
        self.repo.claim_stream_probe.return_value=True
        self.repo.mark_call_running.return_value=True
        self.manager=STTWorkerManager()
        self.manager.discover_date_based_call=AsyncMock(side_effect=discovery_result)
        self.manager.probe_date_based_call=AsyncMock(return_value=(True,None))
        self.manager.discard_promotable_probe=AsyncMock()
        async def launch(item, **kwargs):
            self.manager._active_processes[self.manager._build_call_id(item)]=SimpleNamespace(returncode=None)
        self.manager.launch_date_based_audio_capture=AsyncMock(side_effect=launch)
        self.service=LiveWatchService(self.repo,self.manager,AsyncMock(),Mock())

    async def test_recording_a_does_not_prevent_discovering_b(self):
        first,second=call(1),call(2)
        settings=self.service._date_stream_settings()
        await self.service._probe_and_launch_date_stream_call(first,settings)
        self.repo.get_date_based_stream_candidates.return_value=[second]
        self.assertEqual(await self.service.dispatch_date_based_streams(),1)
        await asyncio.gather(*list(self.service._date_stream_background_tasks.values()))
        self.assertEqual(self.manager.discover_date_based_call.await_count,2)
        self.assertEqual(self.manager.probe_date_based_call.await_count,1)
        self.assertIn('CAPACITY_WAIT',self.repo.record_stream_probe.call_args.kwargs['error'])
        self.manager._active_processes.clear()
        await self.service._probe_and_launch_date_stream_call(second,settings)
        self.assertEqual(self.manager.launch_date_based_audio_capture.await_count,2)
        self.assertEqual(self.service._capture_reservations,set())

    async def test_two_ready_discoveries_cannot_overbook_one_capture_slot(self):
        entered=asyncio.Event(); release=asyncio.Event()
        async def probe(*args,**kwargs):
            entered.set(); await release.wait(); return True,None
        self.manager.probe_date_based_call.side_effect=probe
        settings=self.service._date_stream_settings()
        first=asyncio.create_task(self.service._probe_and_launch_date_stream_call(call(1),settings))
        await asyncio.wait_for(entered.wait(),1)
        await self.service._probe_and_launch_date_stream_call(call(2),settings)
        self.assertEqual(len(self.service._capture_reservations),1)
        self.assertEqual(self.manager.probe_date_based_call.await_count,1)
        release.set(); await first
        self.assertEqual(self.service._capture_reservations,set())
        self.assertEqual(self.manager.active_capture_count(),1)

    async def test_cancelled_preparation_releases_reservation_and_probe_lease(self):
        entered=asyncio.Event()
        async def probe(*args,**kwargs):
            entered.set(); await asyncio.Event().wait()
        self.manager.probe_date_based_call.side_effect=probe
        task=asyncio.create_task(self.service._probe_and_launch_date_stream_call(call(1),self.service._date_stream_settings()))
        await asyncio.wait_for(entered.wait(),1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(self.service._capture_reservations)
        self.assertFalse(self.service._preparing_call_ids)
        self.manager.discard_promotable_probe.assert_awaited_once()
        self.assertIn('interrupted',self.repo.record_stream_probe.call_args.kwargs['error'])

    async def test_schedule_change_discards_held_browser(self):
        self.repo.mark_call_running.return_value=False
        await self.service._probe_and_launch_date_stream_call(call(1),self.service._date_stream_settings())
        self.manager.launch_date_based_audio_capture.assert_not_awaited()
        self.manager.discard_promotable_probe.assert_awaited_once()
        self.assertFalse(self.service._capture_reservations)

    async def test_preparation_does_not_occupy_discovery_budget(self):
        entered=asyncio.Event(); release=asyncio.Event()
        async def probe(*args,**kwargs):
            entered.set(); await release.wait(); return False,'not live yet'
        self.manager.probe_date_based_call.side_effect=probe
        self.repo.get_date_based_stream_candidates.return_value=[call(1)]
        await self.service.dispatch_date_based_streams()
        await asyncio.wait_for(entered.wait(),1)
        self.repo.get_date_based_stream_candidates.return_value=[call(2)]
        self.assertEqual(await self.service.dispatch_date_based_streams(),1)
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(*list(self.service._date_stream_background_tasks.values()))
        self.assertEqual(self.manager.discover_date_based_call.await_count,2)
        self.assertEqual(self.manager.probe_date_based_call.await_count,1)

    async def test_three_preparations_block_fourth_then_reuse_finished_slot(self):
        settings = {**self.service._date_stream_settings(), "capture_concurrency": 3}
        all_entered = asyncio.Event()
        release = asyncio.Event()
        entered_ids = set()

        async def probe(item, **kwargs):
            entered_ids.add(item["id"])
            if len(entered_ids) == 3:
                all_entered.set()
            await release.wait()
            return True, None

        self.manager.probe_date_based_call.side_effect = probe
        tasks = [asyncio.create_task(self.service._probe_and_launch_date_stream_call(call(i), settings))
                 for i in range(1, 4)]
        try:
            await asyncio.wait_for(all_entered.wait(), 1)
            snapshot = self.service._capacity_snapshot(settings)
            self.assertEqual(snapshot["preparing_captures"], 3)
            self.assertEqual(snapshot["occupied_capture_slots"], 3)
            self.assertEqual(snapshot["available_capture_slots"], 0)
            await self.service._probe_and_launch_date_stream_call(call(4), settings)
            self.assertEqual(entered_ids, {1, 2, 3})
            self.assertIn("occupied=3/3", self.repo.record_stream_probe.call_args.kwargs["error"])
        finally:
            release.set()
            await asyncio.gather(*tasks)
        self.assertEqual(self.manager.active_capture_count(), 3)
        self.assertFalse(self.service._capture_reservations)
        self.manager._active_processes[self.manager._build_call_id(call(2))].returncode = 0
        await self.service._probe_and_launch_date_stream_call(call(4), settings)
        self.assertEqual(self.manager.active_capture_count(), 3)
        self.assertEqual(self.manager.launch_date_based_audio_capture.await_count, 4)
        self.assertEqual(self.service._capacity_snapshot(settings)["occupied_capture_slots"], 3)

    async def test_one_failed_preparation_leaves_two_captures_and_releases_one_slot(self):
        settings = {**self.service._date_stream_settings(), "capture_concurrency": 3}
        all_entered = asyncio.Event()
        release = asyncio.Event()
        entered = 0

        async def probe(item, **kwargs):
            nonlocal entered
            entered += 1
            if entered == 3:
                all_entered.set()
            await release.wait()
            if item["id"] == 2:
                raise RuntimeError("simulated registration failure")
            return True, None

        self.manager.probe_date_based_call.side_effect = probe
        tasks = [asyncio.create_task(self.service._probe_and_launch_date_stream_call(call(i), settings))
                 for i in range(1, 4)]
        try:
            await asyncio.wait_for(all_entered.wait(), 1)
        finally:
            release.set()
            await asyncio.gather(*tasks)
        expected = {self.manager._build_call_id(call(i)) for i in (1, 3)}
        self.assertEqual(self.manager.occupied_capture_keys(), expected)
        self.assertEqual(self.service._capacity_snapshot(settings)["available_capture_slots"], 1)
        self.assertFalse(self.service._capture_reservations)
        self.assertFalse(self.service._preparing_call_ids)
        await self.service._probe_and_launch_date_stream_call(call(4), settings)
        self.assertEqual(self.manager.active_capture_count(), 3)
        self.assertTrue(expected.issubset(self.manager.occupied_capture_keys()))

    async def test_background_dispatch_deduplicates_call_during_preparation_and_capture(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def probe(item, **kwargs):
            entered.set()
            await release.wait()
            return True, None

        self.manager.probe_date_based_call.side_effect = probe
        self.repo.get_date_based_stream_candidates.return_value = [call(1)]
        with patch.dict(os.environ, {"DATE_STREAM_CAPTURE_CONCURRENCY": "3",
                                    "DATE_STREAM_DISCOVERY_CONCURRENCY": "3"}):
            self.assertEqual(await self.service.dispatch_date_based_streams(), 1)
            pending = list(self.service._date_stream_background_tasks.values())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                self.assertEqual(await self.service.dispatch_date_based_streams(), 0)
                self.assertEqual(self.manager.probe_date_based_call.await_count, 1)
            finally:
                release.set()
                await asyncio.gather(*pending)
            # Even if a stale candidate query returns the now-running call, its
            # active key prevents a second audio preparation and capture.
            await self.service.dispatch_date_based_streams()
            await asyncio.gather(*list(self.service._date_stream_background_tasks.values()))
        self.assertEqual(self.manager.probe_date_based_call.await_count, 1)
        self.assertEqual(self.manager.launch_date_based_audio_capture.await_count, 1)

    def test_capacity_snapshot_deduplicates_preparing_held_and_active_transitions(self):
        settings = {**self.service._date_stream_settings(), "capture_concurrency": 3,
                    "discovery_concurrency": 2, "concurrency": 1}
        keys = [self.manager._build_call_id(call(i)) for i in range(1, 4)]
        self.manager._active_processes[keys[0]] = SimpleNamespace(returncode=None)
        self.manager._promotable_probes[keys[0]] = SimpleNamespace(process=SimpleNamespace(returncode=None))
        self.manager._promotable_probes[keys[1]] = SimpleNamespace(process=SimpleNamespace(returncode=None))
        self.service._capture_reservations.update(keys)
        self.service._preparing_call_ids.update({1, 2, 3})
        self.service._date_stream_background_tasks.update({
            i: SimpleNamespace(done=lambda: False) for i in range(1, 5)
        })
        snapshot = self.service._capacity_snapshot(settings)
        self.assertEqual(snapshot, {
            "capture_limit": 3, "discovery_limit": 2, "active_discoveries": 1,
            "active_captures": 1, "held_captures": 1, "preparing_captures": 1,
            "capture_reservations": 3, "occupied_capture_slots": 3,
            "available_capture_slots": 0,
        })
        self.assertFalse(self.service._reserve_capture(call(4), settings))
        self.assertFalse(self.service._reserve_capture(call(1), settings))

    def test_capacity_snapshot_accepts_minimal_capture_settings(self):
        # Direct probe callers supply only these settings; evaluating a missing
        # legacy concurrency default must not turn logging into a capture error.
        snapshot = self.service._capacity_snapshot({"cooldown_minutes": 1, "capture_concurrency": 3})
        self.assertEqual(snapshot["capture_limit"], 3)
        self.assertEqual(snapshot["discovery_limit"], 2)
        self.assertEqual(snapshot["occupied_capture_slots"], 0)
        self.assertEqual(snapshot["available_capture_slots"], 3)

    async def test_watch_log_reports_capture_limit_independently_of_legacy_watch_limit(self):
        self.repo.get_date_based_stream_candidates.return_value = []
        with patch.dict(os.environ, {"DATE_STREAM_CAPTURE_CONCURRENCY": "3",
                                    "DATE_STREAM_DISCOVERY_CONCURRENCY": "2",
                                    "DATE_STREAM_WATCH_CONCURRENCY": "1"}):
            await self.service.dispatch_date_based_streams()
        entries = [entry.kwargs for entry in self.service.health.record_event.call_args_list
                   if entry.args == ("watch_cycle",)]
        self.assertEqual(entries[-1]["capture_limit"], 3)
        self.assertEqual(entries[-1]["discovery_limit"], 2)
        self.assertEqual(entries[-1]["available_capture_slots"], 3)

    def test_allowlist_is_forwarded_before_repository_limit(self):
        with patch.dict(os.environ,{'DATE_STREAM_WATCH_TICKERS':'BRK.B, AAPL'}):
            self.service._date_stream_candidates(self.service._date_stream_settings())
        self.assertEqual(self.repo.get_date_based_stream_candidates.call_args.kwargs['tickers'],['AAPL','BRK-B'])


class DiscoveryProofTest(unittest.TestCase):
    def test_proof_rejects_other_date_other_url_and_stale_timestamp(self):
        item=call(1); result=discovery_result(item); proof=result['identity_proof'];url=result['discovered_url']
        self.assertTrue(STTWorkerManager._fresh_discovery_proof(item,url,proof))
        for change in ({'target_date':'2026-09-16'},{'target_url':url+'?event=old'},
                       {'call_ticker':'OTHER'},{'observed_at':'2020-01-01T00:00:00+00:00'}):
            self.assertFalse(STTWorkerManager._fresh_discovery_proof(item,url,{**proof,**change}))

    def test_only_fresh_date_linked_official_route_can_skip_ir_rediscovery(self):
        item={**call(1),'webcast_url':'https://provider.invalid/live?event=1',
              'schedule_source':'official_ir_discovery','schedule_discovery_fingerprint':'abc',
              'schedule_discovery_checked_at':datetime.now(timezone.utc)}
        item['schedule_evidence'] = route_proof(ticker=item['ticker'], day=date(2026, 9, 17),
            issuer_url=item['ir_url'], event_url=None, webcast_url=item['webcast_url'])
        self.assertEqual(STTWorkerManager._stored_target_proof(item)['target_url'],item['webcast_url'])
        for change in ({'schedule_source':'calendar'}, {'schedule_evidence':'published time only'},
                       {'schedule_discovery_checked_at':'2020-01-01T00:00:00+00:00'},
                       {'schedule_evidence':'[target-linked:webcast_url=2026-09-16] earnings call'}):
            self.assertIsNone(STTWorkerManager._stored_target_proof({**item,**change}))


class PromotionOwnershipTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_promotion_signal_reaps_held_browser(self):
        import tempfile
        from pathlib import Path
        manager=STTWorkerManager()
        item={'ticker':'TEST'}
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/'not-a-directory';parent.write_text('occupied')
            held=SimpleNamespace(process=SimpleNamespace(returncode=None),runtime_environment={},
                                 promote_file=str(parent/'promote'),abort_file=str(parent/'abort'))
            manager._promotable_probes['TEST']=held
            manager._stop_promotable_probe=AsyncMock()
            with self.assertRaises(OSError):
                await manager.launch_date_based_audio_capture(item)
        manager._stop_promotable_probe.assert_awaited_once_with(held)
        self.assertFalse(manager.occupied_capture_keys())

    async def test_old_process_completion_cannot_remove_replacement(self):
        manager=STTWorkerManager()
        old=SimpleNamespace(wait=AsyncMock(return_value=0),returncode=0)
        new=SimpleNamespace(returncode=None)
        manager._active_processes['TEST']=new
        await manager._watch_process({'ticker':'TEST'},'TEST',old)
        self.assertIs(manager._active_processes['TEST'],new)
