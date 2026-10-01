"""Narrow duplicate-DDL handling plus opt-in real MySQL migration contention."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import unittest
from unittest import mock

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from data_pipeline.storage import connection, schema


def _error(code):
    return OperationalError('DDL', {}, Exception(code, 'test MySQL error'))


class ScheduleSchemaDDLTest(unittest.TestCase):
    def test_column_duplicate_is_accepted_only_when_column_now_exists(self):
        conn = mock.Mock()
        conn.execute.side_effect = [_error(1060), [('schedule_revision',)]]
        schema._execute_schedule_ddl(conn, 'ALTER TABLE calls ADD COLUMN schedule_revision INT',
                                     duplicate_code=1060, object_name='schedule_revision', object_kind='column')
        self.assertEqual(conn.execute.call_count, 2)

    def test_index_duplicate_is_rechecked(self):
        conn = mock.Mock()
        conn.execute.side_effect = [_error(1061), [('calls', 1, 'idx_calls_probe_retry')]]
        schema._execute_schedule_ddl(conn, 'CREATE INDEX idx_calls_probe_retry ON calls (status)',
                                     duplicate_code=1061, object_name='idx_calls_probe_retry', object_kind='index')
        self.assertEqual(conn.execute.call_count, 2)

    def test_duplicate_without_actual_object_is_not_swallowed(self):
        conn = mock.Mock()
        conn.execute.side_effect = [_error(1060), []]
        with self.assertRaises(OperationalError):
            schema._execute_schedule_ddl(conn, 'ALTER TABLE calls ADD COLUMN schedule_revision INT',
                                         duplicate_code=1060, object_name='schedule_revision', object_kind='column')

    def test_unrelated_mysql_error_propagates_without_recheck(self):
        conn = mock.Mock()
        conn.execute.side_effect = _error(1142)
        with self.assertRaises(OperationalError):
            schema._execute_schedule_ddl(conn, 'ALTER TABLE calls ADD COLUMN schedule_revision INT',
                                         duplicate_code=1060, object_name='schedule_revision', object_kind='column')
        self.assertEqual(conn.execute.call_count, 1)


@unittest.skipUnless(os.getenv('RUN_MYSQL_SCHEDULE_MIGRATION_SMOKE') == '1',
                     'requires explicitly isolated MySQL database')
class ConcurrentMySQLScheduleMigrationTest(unittest.TestCase):
    def test_concurrent_startup_migrations_preserve_rows_and_converge(self):
        self.assertEqual(connection.engine.url.database, 'ew_schedule_migration_test',
                         'this destructive fixture must only target its isolated test database')
        engine = connection.engine
        with engine.begin() as conn:
            self.assertEqual(list(conn.execute(text('SHOW TABLES'))), [], 'test database must be empty')
            conn.execute(text('''CREATE TABLE calls (
                id BIGINT PRIMARY KEY, ticker VARCHAR(20), earning_at DATETIME,
                call_year INT, quarter VARCHAR(8), status VARCHAR(32),
                preserved_text TEXT
            ) ENGINE=InnoDB'''))
            conn.execute(text("""INSERT INTO calls VALUES
                (1, 'ACN', '2026-10-01', 2026, 'Q4', 'upcoming', 'keep this existing row')"""))
        workers = 6
        barriers = {'columns': threading.Barrier(workers), 'indexes': threading.Barrier(workers)}
        observed = threading.local()
        duplicate_codes = []

        def synchronize_absent_reads(conn, cursor, statement, parameters, context, many):
            kind = {'SHOW COLUMNS FROM calls': 'columns', 'SHOW INDEX FROM calls': 'indexes'}.get(statement)
            if kind and not getattr(observed, kind, False):
                setattr(observed, kind, True)
                barriers[kind].wait(timeout=60)

        def record_duplicate(context):
            args = getattr(context.original_exception, 'args', ())
            if args and args[0] in {1060, 1061}:
                duplicate_codes.append(args[0])

        event.listen(engine, 'after_cursor_execute', synchronize_absent_reads)
        event.listen(engine, 'handle_error', record_duplicate)
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(schema.ensure_schedule_time_schema) for _ in range(workers)]
                for future in futures:
                    future.result(timeout=120)
        finally:
            event.remove(engine, 'after_cursor_execute', synchronize_absent_reads)
            event.remove(engine, 'handle_error', record_duplicate)
        self.assertIn(1060, duplicate_codes, 'the test must exercise a real concurrent column race')
        self.assertIn(1061, duplicate_codes, 'the test must exercise a real concurrent index race')
        schema.ensure_schedule_time_schema()
        with engine.connect() as conn:
            columns = {row[0] for row in conn.execute(text('SHOW COLUMNS FROM calls'))}
            self.assertTrue(set(schema.SCHEDULE_TIME_COLUMNS).issubset(columns))
            self.assertEqual(conn.execute(text('SELECT COUNT(*) FROM calls')).scalar(), 1)
            self.assertEqual(conn.execute(text('SELECT preserved_text FROM calls WHERE id=1')).scalar(),
                             'keep this existing row')
            tables = {row[0] for row in conn.execute(text('SHOW TABLES'))}
            self.assertTrue({'schedule_change_history', 'schedule_enrichment_circuits'}.issubset(tables))
        print('MYSQL_CONCURRENT_MIGRATION_RESULT', {'workers': workers,
              'column_duplicate_races': duplicate_codes.count(1060),
              'index_duplicate_races': duplicate_codes.count(1061),
              'existing_rows_preserved': True})


if __name__ == '__main__':
    unittest.main()
