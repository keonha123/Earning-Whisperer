import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from collectors.news.finnhub_news_job import (
    get_finnhub_news_interval_minutes,
    run_finnhub_news_once,
)
from orchestrator import EarningsOrchestrator


async def start_scheduling():
    scheduler = AsyncIOScheduler()
    orch = EarningsOrchestrator()

    # PART 1: Regular data synchronization
    scheduler.add_job(orch.sync_stock_master, "cron", hour=4, minute=0)
    scheduler.add_job(orch.sync_daily_indicators, "cron", hour=4, minute=10)
    scheduler.add_job(orch.update_all_schedules, "cron", hour=4, minute=30, args=[10])
    scheduler.add_job(orch.sync_stock_prices, "interval", hours=1, args=[7])
    scheduler.add_job(run_finnhub_news_once, "interval", minutes=get_finnhub_news_interval_minutes(), id="finnhub_company_news", name="Collect Finnhub company news", max_instances=1, coalesce=True, replace_existing=True)

    # PART 2: Real-time earnings call handling, enabled after implementation
    # scheduler.add_job(orch.monitor_and_trigger_stt, "interval", minutes=5)

    scheduler.start()

    print(f"[{datetime.now()}] Earning Whisperer scheduler started")
    print("All regular update jobs are scheduled.")
    print("Phase 4(STT monitoring) is waiting for implementation.")

    while True:
        await asyncio.sleep(1)


def main():
    asyncio.run(start_scheduling())


if __name__ == "__main__":
    main()
