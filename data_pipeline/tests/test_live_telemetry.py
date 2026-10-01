import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from data_pipeline.live_telemetry import emit_live_event, read_progress_snapshot, archive_spool_health


class LiveTelemetryTest(unittest.TestCase):
    def test_disabled_and_io_failure_never_raise(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(emit_live_event('audio', 'tick'))
            self.assertEqual(read_progress_snapshot(), {})
        with tempfile.NamedTemporaryFile() as occupied:
            self.assertIsNone(emit_live_event('audio', 'tick', directory=occupied.name))
            self.assertEqual(read_progress_snapshot(occupied.name), {})

    def test_merge_preserves_counters_and_progress_only_advances_on_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            first = emit_live_event('stt', 'chunk', status='running', progress=True, directory=directory,
                                    context={'call_id': 42, 'ticker': 'TEST', 'attempt_id': 'try1'},
                                    consumed_audio_bytes=16000, committed_segments=1)
            second = emit_live_event('stt', 'inference_started', directory=directory, inference_sequence=2)
            self.assertEqual(second['consumed_audio_bytes'], 16000)
            self.assertEqual(second['status'], 'running')
            self.assertEqual(second['last_progress_at'], first['last_progress_at'])
            third = emit_live_event('stt', 'inference_completed', progress=True, directory=directory)
            self.assertGreaterEqual(third['last_progress_at'], first['last_progress_at'])
            self.assertEqual(read_progress_snapshot(directory)['stt']['committed_segments'], 1)
            self.assertEqual(first['probe_attempt_id'], 'try1')
            self.assertEqual(first['call_id'], 42)

    def test_explicit_context_isolated_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'TICKER':'WRONG', 'OPENAI_API_KEY':'example-secret-key'}):
            result = emit_live_event('browser','navigation',directory=directory,
                context={'ticker':'TEST','call_id':2,'attempt_id':'try2'},
                url='https://user:pw@example.test/play?eventid=123&token=hidden-token',
                error='example-secret-key email me@example.test',
                fields={'password':'hidden-password','email':'hidden-email','required':True})
            raw = (Path(directory)/'events.jsonl').read_text()
            for forbidden in ['example-secret-key','me@example.test','hidden-token','hidden-password','hidden-email','user:pw']:
                self.assertNotIn(forbidden,raw)
            self.assertIn('eventid=123',raw)
            self.assertEqual(result['ticker'],'TEST')
            self.assertTrue(result['fields']['required'])

    def test_threads_and_processes_merge_without_partial_json(self):
        with tempfile.TemporaryDirectory() as directory:
            def emit(i):
                return emit_live_event('audio','tick',directory=directory,**{f'count_{i}':i})
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertTrue(all(pool.map(emit,range(32))))
            code = "from data_pipeline.live_telemetry import emit_live_event; import sys; assert emit_live_event('audio','tick',directory=sys.argv[1],**{sys.argv[2]:1})"
            children = [subprocess.Popen([sys.executable,'-c',code,directory,f'process_{i}']) for i in range(4)]
            self.assertEqual([child.wait(timeout=5) for child in children],[0]*4)
            snapshot = read_progress_snapshot(directory)['audio']
            self.assertTrue(all(snapshot[f'count_{i}']==i for i in range(32)))
            self.assertTrue(all(snapshot[f'process_{i}']==1 for i in range(4)))
            lines=(Path(directory)/'events.jsonl').read_text().splitlines()
            self.assertEqual(len(lines),36)
            self.assertTrue(all(json.loads(line)['stage']=='audio' for line in lines))

    def test_logs_and_snapshots_are_bounded_and_invalid_payload_is_harmless(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'WEBCAST_PROGRESS_MAX_BYTES':'16384'}):
            for i in range(30):
                self.assertIsNotNone(emit_live_event('audio','tick',directory=directory,number=i,dom='x'*100000))
            for name in ('events.jsonl','events.previous.jsonl'):
                path=Path(directory)/name
                self.assertLessEqual(path.stat().st_size,16384)
                self.assertTrue(all(json.loads(line) for line in path.read_text().splitlines()))
            self.assertIsNone(emit_live_event('audio','tick',directory=directory,bad=float('nan')))
            self.assertEqual(read_progress_snapshot(directory)['audio']['number'],29)
            self.assertIsNotNone(emit_live_event('audio','tick',directory=directory,**{f'large_{i}':'x'*10000 for i in range(100)}))
            self.assertLessEqual((Path(directory)/'audio.json').stat().st_size,64000)
            self.assertEqual(read_progress_snapshot(directory)['audio']['stage'],'audio')

    def test_archive_spool_health_is_bounded_and_distinct_from_outbox(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.jsonl"
            self.assertEqual(archive_spool_health(path)["archive_spool_records"], 0)
            path.write_text('{"sequence":1}\n' * 2000)
            result = archive_spool_health(path)
            self.assertEqual(result["archive_spool_records"], 1000)
            self.assertEqual(result["archive_spool_count_capped"], 1)
            self.assertEqual(result["archive_spool_bytes"], path.stat().st_size)
            self.assertEqual(archive_spool_health(directory)["archive_spool_read_error"], 1)


if __name__ == '__main__':
    unittest.main()
