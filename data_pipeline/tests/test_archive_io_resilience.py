"""Database stalls must not hold the durable speech writers' file lock."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from data_pipeline.storage.connection import engine_options
from data_pipeline.stt_worker.delivery import TranscriptEmitter


def segment(session, sequence):
    return {"kind": "segment", "payload": {
        "call_id": session, "ticker": "TEST", "sequence": sequence,
        "text": f"Statement {sequence}", "is_session_end": False,
    }}


class ArchiveIOResilienceTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.spool = Path(tmp.name) / "archive.jsonl"
        env = patch.dict(os.environ, {"TRANSCRIPT_ARCHIVE_SPOOL_PATH": str(self.spool),
                                    "WEBCAST_PROGRESS_DIR": ""})
        env.start()
        self.addCleanup(env.stop)
        self.ensure = patch("data_pipeline.database.ensure_transcript_archive_schema")
        self.ensure.start()
        self.addCleanup(self.ensure.stop)

    def emitter(self, session="A"):
        return TranscriptEmitter(SimpleNamespace(call_id=session))

    def records(self):
        return [json.loads(line) for line in self.spool.read_text().splitlines()] if self.spool.exists() else []

    def test_hung_database_does_not_block_other_durable_writers_or_drainers(self):
        owner, other = self.emitter(), self.emitter("B")
        owner._append_archive_spool(segment("A", 0))
        entered, release = threading.Event(), threading.Event()

        def slow_database(*args, **kwargs):
            entered.set()
            if not release.wait(4):
                raise TimeoutError("test release missing")

        with patch("data_pipeline.database.archive_transcript_segment", side_effect=slow_database):
            with ThreadPoolExecutor(max_workers=3) as workers:
                replay = workers.submit(owner._replay_local_archive_spool)
                try:
                    self.assertTrue(entered.wait(1))
                    # The old implementation hangs here behind the DB writer.
                    append = workers.submit(other._append_archive_spool, segment("B", 0))
                    self.assertTrue(append.result(timeout=1))
                    busy = workers.submit(other._replay_local_archive_spool).result(timeout=1)
                    self.assertEqual(busy.archived_segments, set())
                    self.assertEqual(len(self.records()), 2)
                finally:
                    release.set()
                self.assertEqual(replay.result(timeout=2).archived_segments, {("A", 0)})
        # Snapshot acknowledgement cannot delete text appended during DB I/O.
        self.assertEqual(self.records(), [segment("B", 0)])

    def test_commit_failure_preserves_order_and_concurrently_appended_text(self):
        owner, other = self.emitter(), self.emitter("B")
        terminal = {"kind": "session_end", "call_id": "A", "sequence": 1}
        for record in (segment("A", 0), segment("A", 1), terminal):
            owner._append_archive_spool(record)

        def archive(payload, **kwargs):
            if payload["sequence"] == 1:
                other._append_archive_spool(segment("B", 0))
                raise TimeoutError("no response")

        with patch("data_pipeline.database.archive_transcript_segment", side_effect=archive), patch(
            "data_pipeline.database.mark_transcript_session_end"
        ) as end:
            replay = owner._replay_local_archive_spool()
        self.assertEqual(replay.archived_segments, {("A", 0)})
        end.assert_not_called()
        self.assertEqual(self.records(), [segment("A", 1), terminal, segment("B", 0)])

    def test_crash_after_commit_before_ack_keeps_replayable_evidence(self):
        owner = self.emitter()
        owner._append_archive_spool(segment("A", 0))
        stored = {}
        def archive(payload, **kwargs):
            stored[(payload["call_id"], payload["sequence"])] = payload
        with patch("data_pipeline.database.archive_transcript_segment", side_effect=archive):
            with patch.object(owner, "_ack_archive_snapshot", side_effect=OSError("ack unavailable")):
                owner._replay_local_archive_spool()
            self.assertEqual(self.records(), [segment("A", 0)])
            owner._replay_local_archive_spool()
        self.assertEqual(len(stored), 1)
        self.assertFalse(self.spool.exists())

    def test_bounded_batch_does_not_let_end_marker_overtake_segments(self):
        owner = self.emitter()
        terminal = {"kind": "session_end", "call_id": "A", "sequence": 2}
        for record in (segment("A", 0), segment("A", 1), segment("A", 2), terminal):
            owner._append_archive_spool(record)
        with patch.dict(os.environ, {"TRANSCRIPT_ARCHIVE_REPLAY_LIMIT": "2"}), patch(
            "data_pipeline.database.archive_transcript_segment"
        ), patch("data_pipeline.database.mark_transcript_session_end", return_value=True) as end:
            first = owner._replay_local_archive_spool()
            self.assertEqual(first.archived_segments, {("A", 0), ("A", 1)})
            end.assert_not_called()
            self.assertEqual(self.records(), [segment("A", 2), terminal])
            second = owner._replay_local_archive_spool()
            self.assertEqual(second.terminal_sessions, {"A"})
        self.assertFalse(self.spool.exists())

    def test_schema_failure_keeps_spool_and_releases_both_locks(self):
        owner, other = self.emitter(), self.emitter("B")
        owner._append_archive_spool(segment("A", 0))
        with patch("data_pipeline.database.ensure_transcript_archive_schema", side_effect=TimeoutError):
            replay = owner._replay_local_archive_spool()
        self.assertFalse(replay.archived_segments)
        self.assertTrue(other._append_archive_spool(segment("B", 0)))
        with patch("data_pipeline.database.archive_transcript_segment"):
            self.assertEqual(other._replay_local_archive_spool().archived_segments, {("A", 0), ("B", 0)})

    def test_unexpected_snapshot_change_never_deletes_new_evidence(self):
        owner = self.emitter()
        original = json.dumps(segment("A", 0))
        self.spool.write_text(json.dumps(segment("B", 9)) + "\n")
        owner._ack_archive_snapshot([original], [])
        self.assertEqual(self.records(), [segment("B", 9)])


class MySQLTimeoutTest(unittest.TestCase):
    def test_mysql_receives_positive_bounded_socket_and_pool_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            options = engine_options("mysql+pymysql://localhost/test")
        self.assertEqual(options["connect_args"], {"connect_timeout": 5, "read_timeout": 5, "write_timeout": 5})
        self.assertEqual(options["pool_timeout"], 5)
        self.assertNotIn("connect_args", engine_options("sqlite://"))

    def test_malformed_or_zero_timeouts_cannot_disable_network_limits(self):
        with patch.dict(os.environ, {"DB_READ_TIMEOUT_SECONDS": "broken", "DB_WRITE_TIMEOUT_SECONDS": "0"}):
            args = engine_options("mysql+pymysql://localhost/test")["connect_args"]
        self.assertEqual(args["read_timeout"], 5)
        self.assertEqual(args["write_timeout"], 1)

    def test_real_pymysql_read_of_nonresponsive_socket_times_out(self):
        # Isolated loopback TCP peer accepts connection but never sends MySQL
        # packets. No credentials or production database/network are involved.
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        release = threading.Event()
        def peer():
            conn, _ = server.accept()
            with conn:
                release.wait(4)
        worker = threading.Thread(target=peer, daemon=True)
        worker.start()
        url = f"mysql+pymysql://test:test@127.0.0.1:{server.getsockname()[1]}/test"
        with patch.dict(os.environ, {"DB_READ_TIMEOUT_SECONDS": "1"}):
            engine = create_engine(url, **engine_options(url))
        start = time.monotonic()
        try:
            with self.assertRaises(OperationalError):
                engine.connect()
            self.assertLess(time.monotonic() - start, 3)
        finally:
            release.set()
            worker.join(timeout=2)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
