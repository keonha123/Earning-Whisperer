"""Composition root: wire independently replaceable pipeline services."""

from datetime import datetime

if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_pipeline import database
from data_pipeline.config import load_project_env
from data_pipeline.application.health import RuntimeHealth
from data_pipeline.application.housekeeping import HousekeepingService
from data_pipeline.application.live_watch import LiveWatchService
from data_pipeline.application.market_data import MarketDataService
from data_pipeline.application.schedules import ScheduleService
from data_pipeline.application.settings import probe_window
from data_pipeline.stt_worker.manager import STTWorkerManager

load_project_env()


class EarningsOrchestrator:
    """Public scheduler API and the one place where pipeline parts are wired."""

    def __init__(self, *, repository=None, worker_manager=None):
        repository = database if repository is None else repository
        worker_manager = STTWorkerManager() if worker_manager is None else worker_manager
        self.health = RuntimeHealth()
        self.market_data = MarketDataService(repository, self.health)
        self.schedules = ScheduleService(repository, self.health)
        self.live_watch = LiveWatchService(repository, worker_manager, self.schedules, self.health)
        self.housekeeping = HousekeepingService(repository, self.health)

    @property
    def worker_manager(self):
        return self.live_watch.worker_manager

    @worker_manager.setter
    def worker_manager(self, value):
        self.live_watch.worker_manager = value

    _probe_window = staticmethod(probe_window)

    def sync_stock_master(self):
        return self.market_data.sync_stock_master()

    def sync_daily_indicators(self):
        return self.market_data.sync_daily_indicators()

    def sync_financial_statements(self, universe=None, max_workers=5):
        return self.market_data.sync_financial_statements(universe, max_workers)

    def sync_stock_prices(self, days_back=5):
        return self.market_data.sync_stock_prices(days_back)

    def update_all_schedules(self, max_workers=10):
        return self.schedules.update_all_schedules(max_workers)

    def reconcile_near_term_schedule_sources(
        self,
        *,
        yahoo_observed_at: datetime,
    ) -> dict[str, int]:
        return self.schedules.reconcile_near_term_schedule_sources(yahoo_observed_at=yahoo_observed_at)

    def enrich_schedule_times(self, limit: int = 20):
        return self.schedules.enrich_schedule_times(limit)

    def refresh_live_schedule_data(self):
        return self.schedules.refresh_live_schedule_data()

    def maintain_transcript_archive(self):
        return self.housekeeping.maintain_transcript_archive()

    def retry_transcript_outbox(self):
        return self.housekeeping.retry_transcript_outbox()

    def recover_stale_stream_operations(self, *, recover_local_orphans: bool = False):
        return self.housekeeping.recover_stale_stream_operations(recover_local_orphans=recover_local_orphans)

    def check_operational_alerts(self):
        return self.housekeeping.check_operational_alerts()

    def write_operations_report(self):
        return self.housekeeping.write_operations_report()

    async def monitor_and_trigger_stt(self):
        return await self.live_watch.monitor_and_trigger_stt()

    async def monitor_date_based_streams(self):
        return await self.live_watch.monitor_date_based_streams()

    async def dispatch_date_based_streams(self):
        return await self.live_watch.dispatch_date_based_streams()


if __name__ == "__main__":
    orchestrator = EarningsOrchestrator()

    print("🚀 Earning Whisperer 데이터 파이프라인 가동...")

    # 1. 마스터 리스트 업데이트
    orchestrator.sync_stock_master()

    orchestrator.sync_daily_indicators()

    # 2. 어닝 일정 전체 업데이트 (병렬)
    orchestrator.update_all_schedules(max_workers=10)

    # 3. 주가 데이터 업데이트 (새로 추가!)
    orchestrator.sync_stock_prices(days_back=7)

    # 4. Quarterly financial statements
    orchestrator.sync_financial_statements()

    print("\n✨ 모든 데이터 동기화가 완료되었습니다.")
