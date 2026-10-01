"""Shared transcript spool keeps payload and progress identities per capture."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from data_pipeline.live_telemetry import emit_live_event
from data_pipeline.stt_worker.delivery import TranscriptEmitter


def segment(session, sequence):
    return {"kind": "segment", "payload": {
        "call_id": session, "ticker": session.split("-")[0],
        "sequence": sequence, "text": f"{session} text {sequence}",
        "is_session_end": False,
    }}


def terminal(session, sequence):
    return {"kind": "session_end", "call_id": session, "sequence": sequence,
            "termination_reason": "event_ended", "success_eligible": True,
            "target_identity_verified": True}


class ConcurrentTranscriptDeliveryTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.spool = self.root / "shared-spool.jsonl"
        self.progress = self.root / "attempt-A"
        environment = patch.dict(os.environ, {
            "TRANSCRIPT_ARCHIVE_SPOOL_PATH": str(self.spool),
            "WEBCAST_PROGRESS_DIR": str(self.progress),
            "WEBCAST_CALL_DB_ID": "11", "TICKER": "AAA",
            "STT_CAPTURE_SESSION_ID": "AAA-capture-11",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def replay(self, session):
        emitter = TranscriptEmitter(SimpleNamespace(call_id=session))
        with (
            patch("data_pipeline.database.ensure_transcript_archive_schema"),
            patch("data_pipeline.database.archive_transcript_segment") as archive,
            patch("data_pipeline.database.mark_transcript_session_end", return_value=True) as mark_end,
        ):
            replay = emitter._replay_local_archive_spool()
        return replay, archive, mark_end

    def write_records(self, records):
        self.spool.write_text("".join(json.dumps(record) + "\n" for record in records))

    def test_shared_replay_commits_all_sessions_but_reports_only_own_sequence(self):
        self.write_records([
            segment("AAA-capture-11", 2), segment("BBB-capture-22", 97),
            terminal("BBB-capture-22", 97), segment("CCC-capture-33", 151),
        ])
        replay, archive, mark_end = self.replay("AAA-capture-11")
        self.assertEqual(replay.archived_segments, {
            ("AAA-capture-11", 2), ("BBB-capture-22", 97), ("CCC-capture-33", 151),
        })
        self.assertEqual(archive.call_count, 3)
        self.assertEqual(replay.terminal_sessions, {"BBB-capture-22"})
        mark_end.assert_called_once_with("BBB-capture-22", 97,
            termination_reason="event_ended", success_eligible=True,
            target_identity_verified=True, ensure_schema=False)
        progress = json.loads((self.progress / "archive.json").read_text())
        self.assertEqual(progress["capture_session_id"], "AAA-capture-11")
        self.assertEqual(progress["transcript_call_id"], "AAA-capture-11")
        self.assertEqual(progress["db_committed_sequence"], 2)
        self.assertFalse(self.spool.exists())

    def test_other_sessions_do_not_overwrite_existing_progress(self):
        emit_live_event("archive", "segment_db_committed", status="saved", progress=True,
                        transcript_call_id="AAA-capture-11", db_committed_sequence=7)
        before = (self.progress / "archive.json").read_bytes()
        self.write_records([segment("BBB-capture-22", 15), segment("CCC-capture-33", 81)])
        replay, archive, _ = self.replay("AAA-capture-11")
        self.assertEqual(archive.call_count, 2)
        self.assertEqual(len(replay.archived_segments), 2)
        self.assertEqual((self.progress / "archive.json").read_bytes(), before)

    def test_scheduler_replay_has_no_call_progress_side_effect(self):
        self.write_records([segment("BBB-capture-22", 15), terminal("BBB-capture-22", 15)])
        replay, archive, mark_end = self.replay(None)
        self.assertEqual(archive.call_count, 1)
        self.assertEqual(mark_end.call_count, 1)
        self.assertEqual(replay.terminal_sessions, {"BBB-capture-22"})
        self.assertFalse(self.progress.exists())

    def test_three_writers_keep_same_sequence_numbers_and_terminal_sessions_separate(self):
        sessions = ["AAA-capture-11", "BBB-capture-22", "CCC-capture-33"]
        # flock serializes the real append operations; all records retain their
        # session key even when every worker starts sequence numbering at zero.
        def write_session(session):
            emitter = TranscriptEmitter(SimpleNamespace(call_id=session))
            for sequence in range(20):
                self.assertTrue(emitter._append_archive_spool(segment(session, sequence)))
            self.assertTrue(emitter._append_archive_spool(terminal(session, 19)))

        with patch.dict(os.environ, {"WEBCAST_PROGRESS_DIR": ""}):
            with ThreadPoolExecutor(max_workers=3) as workers:
                list(workers.map(write_session, sessions))
        records = [json.loads(line) for line in self.spool.read_text().splitlines()]
        self.assertEqual(len(records), 63)
        expected = {(session, sequence) for session in sessions for sequence in range(20)}
        actual = {(row["payload"]["call_id"], row["payload"]["sequence"])
                  for row in records if row["kind"] == "segment"}
        self.assertEqual(actual, expected)
        replay, archive, mark_end = self.replay("AAA-capture-11")
        self.assertEqual(replay.archived_segments, expected)
        self.assertEqual(replay.terminal_sessions, set(sessions))
        self.assertEqual(archive.call_count, 60)
        self.assertEqual(mark_end.call_count, 3)
        self.assertEqual({entry.args[:2] for entry in mark_end.call_args_list},
                         {(session, 19) for session in sessions})
        for entry in archive.call_args_list:
            payload = entry.args[0]
            self.assertEqual(payload["text"], f"{payload['call_id']} text {payload['sequence']}")
        self.assertFalse(self.spool.exists())


if __name__ == "__main__":
    unittest.main()
