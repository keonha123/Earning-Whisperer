"""A previous failed capture must not freeze the regular schedule refresher."""
from datetime import datetime, timedelta
import unittest
from sqlalchemy import text
from data_pipeline.tests import test_schedule_evidence_retention as fixture
from data_pipeline.storage import schedules


class ReleasedCaptureScheduleRefreshTest(unittest.TestCase):
    setUp = fixture.ScheduleEvidenceRetentionTest.setUp
    row = fixture.ScheduleEvidenceRetentionTest.row
    update = fixture.ScheduleEvidenceRetentionTest.update
    run_pages = fixture.ScheduleEvidenceRetentionTest.run_pages
    weak_index = fixture.ScheduleEvidenceRetentionTest.weak_index
    def test_regular_refresh_updates_clock_after_failed_capture_without_erasing_lineage(self):
        self.update(capture_session_id='CCL-capture-previous', capture_attempts=1,
                    capture_manifest_path='/saved/attempt.json',
                    capture_lease_owner=None, capture_lease_until=None)
        with self.engine.raw.begin() as conn:
            conn.execute(text("INSERT INTO transcript_segments(call_id,text_chunk) VALUES('CCL-capture-previous','Preserved earlier speech')"))
        self.assertIsNotNone(self.run_pages())
        row=self.row()
        self.assertEqual(row['scheduled_at_utc'],'2026-09-29 14:00:00')
        self.assertEqual(row['capture_session_id'],'CCL-capture-previous')
        self.assertEqual(row['capture_attempts'],1)
        self.assertEqual(row['capture_manifest_path'],'/saved/attempt.json')
        with self.engine.raw.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT text_chunk FROM transcript_segments')).scalar_one(),'Preserved earlier speech')
        good=row
        self.now+=timedelta(minutes=10)
        self.assertIsNotNone(self.run_pages())
        self.assertEqual(self.row()['schedule_revision'],good['schedule_revision'])

    def test_expired_lease_is_not_active_but_future_lease_and_unknown_owner_are_protected(self):
        self.update(capture_session_id='historical',capture_lease_owner='expired-worker',
                    capture_lease_until=datetime.utcnow()-timedelta(seconds=10))
        self.assertIsNotNone(self.run_pages())
        good=self.row();self.now+=timedelta(minutes=1)
        for values in ({'capture_lease_until':datetime.utcnow()+timedelta(seconds=90)},
                       {'capture_lease_owner':'worker-with-missing-expiry','capture_lease_until':None}):
            self.update(**good);self.update(**values)
            self.assertIsNone(self.run_pages())
            self.assertEqual(self.row()['schedule_revision'],good['schedule_revision'])

    def test_failed_capture_can_be_cancelled_without_rewriting_old_transcript(self):
        self.run_pages();self.now+=timedelta(minutes=1)
        self.update(capture_session_id='CCL-capture-previous',capture_attempts=1)
        from data_pipeline.tests.test_schedule_evidence_retention import DETAIL, INDEX
        self.assertIsNone(self.run_pages({DETAIL:'<article><h2>Q3 2026 Earnings Call</h2><p>September 29, 2026 cancelled.</p></article>',INDEX:''}))
        self.assertEqual(self.row()['schedule_revalidation_status'],'cancelled')
        self.assertEqual(self.row()['capture_session_id'],'CCL-capture-previous')

    def test_stale_revision_still_rejects_after_failed_capture(self):
        self.run_pages();good=self.row();self.now+=timedelta(minutes=1)
        self.update(capture_session_id='historical')
        self.assertIsNone(schedules.update_verified_schedule_time(1,{
            'scheduled_at_utc':datetime(2026,9,29,15),'expected_revision':good['schedule_revision']-1,
            'observed_at':self.now}))
        self.assertEqual(self.row()['scheduled_at_utc'],good['scheduled_at_utc'])
