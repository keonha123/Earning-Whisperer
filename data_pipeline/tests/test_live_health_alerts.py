import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from data_pipeline.operations import check_operational_alerts
from data_pipeline.storage import health


class LiveHealthAlertTest(unittest.TestCase):
    def test_health_keeps_db_counters_and_adds_local_archive_backlog(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = Path(directory) / 'archive.jsonl'
            spool.write_text('{"sequence":1}\n{"sequence":2}\n')
            connection = MagicMock()
            connection.execute.return_value.mappings.return_value.one.return_value = {
                'stale_probe_count':0,'stale_capture_count':0,'due_outbox_count':0,
                'total_outbox_count':0,'failed_outbox_count':0,
            }
            with patch.dict(os.environ, {'TRANSCRIPT_ARCHIVE_SPOOL_PATH':str(spool)}), \
                 patch.object(health.schema,'ensure_schedule_time_schema'), \
                 patch.object(health.schema,'ensure_transcript_outbox_schema'), \
                 patch.object(health.connection.engine,'connect') as connect:
                connect.return_value.__enter__.return_value = connection
                result = health.get_operational_health_snapshot()
            self.assertEqual(result['archive_spool_records'],2)
            self.assertEqual(result['archive_spool_bytes'],spool.stat().st_size)
            self.assertEqual(result['due_outbox_count'],0)
            self.assertEqual(connection.execute.call_count,2)
            progress_sql = str(connection.execute.call_args.args[0])
            self.assertIn('t.call_id = c.capture_session_id', progress_sql)
            self.assertIn('MAX(t.created_at)', progress_sql)
            self.assertIn('c.schedule_superseded_by IS NULL', progress_sql)

    def test_local_archive_backlog_warns_when_outbox_and_leases_are_healthy(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'OPERATIONS_LOG_DIR':directory,
            'OPERATIONS_ALERT_STATE_FILE':str(Path(directory)/'alerts-state.json'),
            'OPERATIONS_ALERT_WEBHOOK_URL':'',
        }):
            alerts = check_operational_alerts({'archive_spool_records':2,'archive_spool_bytes':100})
            self.assertEqual([row['key'] for row in alerts],['transcript_archive_backlog'])
            self.assertEqual(check_operational_alerts({'archive_spool_records':2,'archive_spool_bytes':100}),[])
            check_operational_alerts({'archive_spool_records':0,'archive_spool_bytes':0})
            rows = [json.loads(line) for path in Path(directory).glob('events-*.jsonl') for line in path.read_text().splitlines()]
            self.assertTrue(any(row['event_type']=='operational_alert_recovered' for row in rows))


if __name__ == '__main__':
    unittest.main()
