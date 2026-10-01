import unittest
from unittest import mock

from sqlalchemy.exc import OperationalError

from data_pipeline import scheduler


class SchedulerStartupRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_refresh_retries_database_unavailability_then_succeeds(self):
        orchestrator = mock.Mock()
        outage = OperationalError("SELECT 1", {}, RuntimeError("database is not ready"))

        with (
            mock.patch(
                "data_pipeline.scheduler.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                side_effect=[outage, None],
            ) as to_thread,
            mock.patch(
                "data_pipeline.scheduler.asyncio.sleep",
                new_callable=mock.AsyncMock,
            ) as sleep,
            mock.patch.dict(
                "os.environ",
                {
                    "SCHEDULE_STARTUP_REFRESH_MAX_ATTEMPTS": "3",
                    "SCHEDULE_STARTUP_REFRESH_RETRY_SECONDS": "2",
                },
                clear=False,
            ),
        ):
            completed = await scheduler._refresh_live_schedule_on_startup_with_retry(
                orchestrator
            )

        self.assertTrue(completed)
        self.assertEqual(to_thread.await_count, 2)
        self.assertEqual(
            to_thread.await_args_list,
            [
                mock.call(orchestrator.refresh_live_schedule_data),
                mock.call(orchestrator.refresh_live_schedule_data),
            ],
        )
        sleep.assert_awaited_once_with(2)

    async def test_startup_refresh_stops_after_the_configured_database_retry_limit(self):
        orchestrator = mock.Mock()
        outage = OperationalError("SELECT 1", {}, RuntimeError("database is not ready"))

        with (
            mock.patch(
                "data_pipeline.scheduler.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                side_effect=[outage, outage, outage],
            ) as to_thread,
            mock.patch(
                "data_pipeline.scheduler.asyncio.sleep",
                new_callable=mock.AsyncMock,
            ) as sleep,
            mock.patch.dict(
                "os.environ",
                {
                    "SCHEDULE_STARTUP_REFRESH_MAX_ATTEMPTS": "3",
                    "SCHEDULE_STARTUP_REFRESH_RETRY_SECONDS": "2",
                },
                clear=False,
            ),
        ):
            completed = await scheduler._refresh_live_schedule_on_startup_with_retry(
                orchestrator
            )

        self.assertFalse(completed)
        self.assertEqual(to_thread.await_count, 3)
        self.assertEqual(sleep.await_args_list, [mock.call(2), mock.call(4)])


if __name__ == "__main__":
    unittest.main()
