"""Capacity regressions: preserve active/legacy audio and reserve before producers."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from data_pipeline.stt_worker import audio_rescue as rescue
from data_pipeline.failure_reasons import classify_live_failure
from data_pipeline.storage.policies import stream_probe_retry_policy, capture_retry_policy


class RescueBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'STT_AUDIO_RESCUE_DIR': str(self.root),
            'STT_PCM_HANDOFF_MAX_BYTES': '32', 'STT_AUDIO_RESCUE_TOTAL_MAX_BYTES': '96',
            'STT_AUDIO_RESCUE_QUARANTINE_MAX_BYTES': '192',
            'WEBCAST_PROGRESS_DIR': ''})
        env.start(); self.addCleanup(env.stop)

    def orphan(self, name='old', size=96):
        p = self.root / (name + '.pcm'); p.write_bytes(b'a' * size)
        rescue._write_private_json(Path(str(p)+'.owner.json'), {
            'pcm_name': p.name, 'pid': 99999999, 'process_start': '1', 'created_at': time.time()})
        rescue._write_private_json(Path(str(p)+'.done'), {'exit_code': 74, 'bytes': size})
        return p

    def test_recent_finished_legacy_orphan_quarantines_bytes_and_metadata(self):
        p = self.orphan()
        with patch.object(rescue, '_legacy_runtime_quiescent', return_value=True), patch.object(rescue, '_has_reader', return_value=False):
            new = rescue.allocate_pcm()
        self.assertFalse(p.exists()); self.assertFalse(new.exists())
        recovered = self.root / 'quarantine' / 'old' / p.name
        self.assertEqual(recovered.read_bytes(), b'a' * 96)
        record = json.loads((recovered.parent/'recovery.json').read_text())
        self.assertEqual(record['pcm_bytes'], 96)
        self.assertEqual(rescue.rescue_health_snapshot()['reserved_bytes'], 32)

    def test_killed_modern_capture_recovers_without_done_while_other_calls_run(self):
        p = self.orphan()
        Path(str(p)+'.done').unlink()
        rescue._write_private_json(Path(str(p)+'.reservation.json'), {
            'supervisor': {'pid':99999998,'process_start':'1'},'reserved_bytes':96})
        with patch.object(rescue, '_legacy_runtime_quiescent', side_effect=AssertionError('modern ownership needs no global idle')), patch.object(rescue, '_has_reader', return_value=False):
            rescue.allocate_pcm()
        self.assertEqual((self.root/'quarantine'/'old'/p.name).read_bytes(), b'a'*96)

    def test_legacy_unknown_runtime_never_reclaims(self):
        p = self.orphan()
        with patch.object(rescue, '_legacy_runtime_quiescent', return_value=False), patch.object(rescue, '_has_reader', return_value=False):
            with self.assertRaisesRegex(OSError, 'BUDGET_UNAVAILABLE'):
                rescue.allocate_pcm()
        self.assertTrue(p.exists())

    def test_active_reader_or_supervisor_never_reclaimed(self):
        p = self.orphan()
        with patch.object(rescue, '_has_reader', return_value=True), patch.object(rescue, '_legacy_runtime_quiescent', return_value=True):
            with self.assertRaises(OSError): rescue.allocate_pcm()
        rescue._write_private_json(Path(str(p)+'.reservation.json'), {
            'supervisor': rescue.process_identity(os.getpid()), 'reserved_bytes':96})
        with patch.object(rescue, '_has_reader', return_value=False):
            with self.assertRaises(OSError): rescue.allocate_pcm()
        self.assertTrue(p.exists())

    def test_failed_supervisor_protects_real_open_consumer(self):
        p = self.orphan()
        with p.open('rb'):
            self.assertTrue(rescue._has_reader(p))

    def test_simultaneous_allocators_reserve_before_pcm_creation(self):
        def allocate(_):
            try: return rescue.allocate_pcm()
            except OSError: return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            values = list(executor.map(allocate, range(8)))
        self.assertEqual(sum(v is not None for v in values), 3)
        self.assertEqual(rescue.rescue_health_snapshot()['reserved_bytes'], 96)
        self.assertFalse(rescue.rescue_health_snapshot()['available_for_next_recording'])

    def test_independent_cli_processes_do_not_overbook(self):
        command=[sys.executable,'-B','-m','data_pipeline.stt_worker.audio_rescue','--allocate','--supervisor-pid',str(os.getpid())]
        processes=[subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(6)]
        outcomes=[(p.communicate(timeout=10),p.returncode) for p in processes]
        self.assertEqual(sum(code==0 for _,code in outcomes),3)
        self.assertTrue(all(code in (0,73) for _,code in outcomes))
        self.assertEqual(rescue.rescue_health_snapshot()['reserved_bytes'],96)

    def test_finalize_and_missing_dead_reservation_release_capacity(self):
        p = rescue.allocate_pcm(); p.write_bytes(b'1'*16)
        self.assertEqual(rescue.rescue_health_snapshot()['reserved_bytes'], 16)
        rescue.finalize_pcm(p, 1)
        self.assertEqual(rescue.rescue_health_snapshot()['reserved_bytes'], 0)
        orphan = self.root/'never-started.pcm.reservation.json'
        rescue._write_private_json(orphan, {'supervisor': {'pid':99999999,'process_start':'1'},'reserved_bytes':80})
        rescue.prune_rescue(self.root)
        self.assertFalse(orphan.exists())
        self.assertTrue(rescue.rescue_health_snapshot()['available_for_next_recording'])

    def test_quarantine_full_does_not_destroy_unexpired_audio(self):
        p = self.orphan(size=96)
        with patch.dict(os.environ, {'STT_AUDIO_RESCUE_QUARANTINE_MAX_BYTES':'32'}), patch.object(rescue, '_has_reader', return_value=False), patch.object(rescue, '_legacy_runtime_quiescent', return_value=True):
            with self.assertRaises(OSError): rescue.allocate_pcm()
        self.assertEqual(p.stat().st_size,96)

    def test_health_is_readonly_and_missing_directory_is_healthy(self):
        p = self.root/'missing'
        result = rescue.rescue_health_snapshot(p)
        self.assertTrue(result['available_for_next_recording']); self.assertFalse(p.exists())

    def test_pid_reuse_and_boot_change_do_not_look_alive(self):
        record = rescue.process_identity(os.getpid())
        self.assertTrue(rescue._alive(record))
        self.assertFalse(rescue._alive({**record,'process_start':'0'}))
        self.assertFalse(rescue._alive({**record,'boot_id':'other-boot'}))
        self.assertTrue(rescue._alive({}))

    def test_disk_capacity_counts_unwritten_reservations(self):
        from types import SimpleNamespace
        with patch.object(rescue.shutil, 'disk_usage', return_value=SimpleNamespace(free=48)):
            rescue.allocate_pcm()
            self.assertEqual(rescue.rescue_health_snapshot()['available_bytes'],16)
            with self.assertRaises(OSError): rescue.allocate_pcm()

    def test_dead_supervisor_before_owner_write_preserves_partial_file(self):
        p = self.root/'partial.pcm'; p.write_bytes(b'partial')
        rescue._write_private_json(Path(str(p)+'.reservation.json'), {
            'supervisor': {'pid':99999999,'process_start':'1'},'reserved_bytes':96})
        with patch.object(rescue, '_has_reader', return_value=False):
            rescue.prune_rescue(self.root)
        self.assertEqual((self.root/'quarantine'/'partial'/'partial.pcm').read_bytes(),b'partial')

    def test_budget_failure_has_resource_retry_without_schedule_refresh(self):
        result = classify_live_failure('AUDIO_RESCUE_BUDGET_UNAVAILABLE')
        self.assertEqual(result['reason'],'resource_capacity')
        self.assertEqual(result['stage'],'audio_storage')
        retry=stream_probe_retry_policy(result['error_code'],watch_state='event_window')
        self.assertEqual(retry['retry_delay_minutes'],1)
        self.assertFalse(retry['requires_schedule_refresh'])
        self.assertEqual(capture_retry_policy(result['error_code'],attempts=2)['reason'],'resource_capacity')

    def test_internal_fallback_guard_keeps_explicit_wait_but_not_date_conflict(self):
        pending = 'NOT_LIVE_YET scheduled event date is in the future: December 9, 2026 | MEDIA_FALLBACK_BLOCKED target_identity_unconfirmed'
        self.assertEqual(classify_live_failure(pending)['category'], 'not_live_yet')
        self.assertEqual(classify_live_failure(pending + ' TARGET_EVENT_MISMATCH')['reason'], 'schedule_mismatch')

    def test_cli_reports_typed_failure_and_no_path_on_stdout(self):
        (self.root/'unknown.pcm').write_bytes(b'0'*96)
        result=subprocess.run([sys.executable,'-B','-m','data_pipeline.stt_worker.audio_rescue','--allocate'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,73)
        self.assertEqual(result.stdout,'')
        self.assertIn('AUDIO_RESCUE_BUDGET_UNAVAILABLE',result.stderr)

if __name__=='__main__': unittest.main()
