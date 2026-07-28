import asyncio
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

try:
    from .orchestrator import EarningsOrchestrator
    from .collectors.news.finnhub_news_job import (
        get_finnhub_news_interval_minutes,
        run_finnhub_news_once,
    )
except ImportError:  # Allows `python data_pipeline/main.py`.
    from orchestrator import EarningsOrchestrator
    from collectors.news.finnhub_news_job import (
        get_finnhub_news_interval_minutes,
        run_finnhub_news_once,
    )

async def start_scheduling():
    scheduler = AsyncIOScheduler()
    orch = EarningsOrchestrator()

    # ==========================================================
    # [PART 1] 데이터 동기화 작전 (정식 스케줄)
    # ==========================================================
    
    # [Step 1] 매일 새벽 04:00 - S&P 500 종목 리스트 갱신
    scheduler.add_job(orch.sync_stock_master, 'cron', hour=4, minute=0)

    # [Step 0] 매일 새벽 04:10 - 종목별 정적 지표(Cache) 계산
    scheduler.add_job(orch.sync_daily_indicators, 'cron', hour=4, minute=10)

    # [Step 2] 매일 새벽 04:30 - 어닝 일정 병렬 수집 (병렬 쓰레드 10개)
    scheduler.add_job(orch.update_all_schedules, 'cron', hour=4, minute=30, args=[10])

    # [Step 2.5] 매일 새벽 04:50 - 가까운 일정의 공식 시작 시각 검증
    scheduler.add_job(orch.enrich_schedule_times, 'cron', hour=4, minute=50, args=[20])

    # [Step 4] Daily 05:00 - quarterly financial statements
    scheduler.add_job(orch.sync_financial_statements, 'cron', hour=5, minute=0, args=['m7', 5])

    # 매일 06:00 - transcript 보관 기간을 넘긴 청크 정리
    scheduler.add_job(
        orch.maintain_transcript_archive,
        'cron',
        hour=6,
        minute=0,
        id='transcript_archive_retention',
        name='Purge expired transcript segments',
        max_instances=1,
        coalesce=True,
    )

    # 매일 운영 결과를 한 번에 검토할 수 있도록 JSON/Markdown 리포트 생성
    scheduler.add_job(
        orch.write_operations_report,
        'cron',
        hour=int(os.getenv("OPERATIONS_REPORT_HOUR", "23")),
        minute=int(os.getenv("OPERATIONS_REPORT_MINUTE", "55")),
        id='operations_daily_report',
        name='Write daily webcast operations report',
        max_instances=1,
        coalesce=True,
    )

    # [Step 3] 매 1시간마다 - 최근 7일간의 주가 데이터 동기화
    scheduler.add_job(orch.sync_stock_prices, 'interval', hours=1, args=[7])
    
    # 매 10분마다 - Finnhub 뉴스 수집 및 ai-engine 전달
    scheduler.add_job(run_finnhub_news_once, "interval", minutes=get_finnhub_news_interval_minutes(), id="finnhub_company_news", name="Collect Finnhub company news", max_instances=1, coalesce=True, replace_existing=True)

    # ==========================================================
    # [PART 2] 실시간 어닝콜 대응 (미래 확장 구간)
    # ==========================================================
    """
    [Phase 4] 어닝콜 실시간 모니터링 및 STT 워커 실행 로직
    이 부분은 Orchestrator에 관련 함수(예: monitor_and_trigger_stt)가 
    구현되는 대로 아래 주석을 해제하여 활성화하면 됩니다.
    """
    if os.getenv("ENABLE_STT_MONITOR", "false").lower() == "true":
        # 1분마다 DB를 조회하여 현재 시각에 시작하는 어닝콜이 있는지 확인
        scheduler.add_job(
            orch.monitor_and_trigger_stt,
            'interval',
            minutes=1,
            id='stt_call_monitor',
            name='Monitor imminent earnings calls',
            max_instances=1,
            coalesce=True,
        )

    if os.getenv("ENABLE_DATE_STREAM_WATCH", "false").lower() == "true":
        scheduler.add_job(
            orch.monitor_date_based_streams,
            'interval',
            minutes=int(os.getenv("DATE_STREAM_WATCH_INTERVAL_MINUTES", "10")),
            id='date_stream_watch',
            name='Probe date-based earnings webcast candidates',
            max_instances=1,
            coalesce=True,
        )

    # 스케줄러 시작
    scheduler.start()
    
    print(f"[{datetime.now()}] 🛰️ Earning Whisperer 관제 시작")
    print("⏰ 모든 정기 업데이트 작업이 예약되었습니다.")
    if os.getenv("ENABLE_STT_MONITOR", "false").lower() == "true":
        print("📢 Phase 4(STT 모니터링)가 활성화되었습니다.")
    else:
        print("📢 Phase 4(STT 모니터링)는 ENABLE_STT_MONITOR=true 설정 전까지 대기 중입니다.")

    # 비동기 루프 유지 (서버 상주)
    while True:
        await asyncio.sleep(1)


def main():
    asyncio.run(start_scheduling())


if __name__ == "__main__":
    main()
