import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data_pipeline.orchestrator import EarningsOrchestrator 

async def start_scheduling():
    scheduler = AsyncIOScheduler()
    orch = EarningsOrchestrator()

    # ==========================================================
    # [PART 1] 데이터 동기화 작전 (새벽 정기 크론탭 기동망)
    # ==========================================================
    
    # [Step 1] 매일 새벽 04:00 - S&P 500 종목 리스트 갱신
    scheduler.add_job(orch.sync_stock_master, 'cron', hour=4, minute=0)

    # [Step 0] 매일 새벽 04:10 - 종목별 정적 지표(Cache) 계산
    scheduler.add_job(orch.sync_daily_indicators, 'cron', hour=4, minute=10)

    # [Step 2] 매일 새벽 04:30 - 어닝 일정 병렬 수집 (병렬 쓰레드 10개)
    scheduler.add_job(orch.update_all_schedules, 'cron', hour=4, minute=30, args=[10])

    # [Step 3] 매 1시간마다 - 최근 7일간의 주가 데이터 동기화
    scheduler.add_job(orch.sync_stock_prices, 'interval', hours=1, args=[7])

    # ==========================================================
    # [PART 2] 실시간 어닝콜 대응 (5분 주기 게릴라 정찰망 완전 개통)
    # ==========================================================
    
    # 🕵️ 시간을 모르므로, 5분마다 게릴라 정찰대를 파견해 문이 열렸는지 노크(Smart Polling)합니다.
    scheduler.add_job(orch.monitor_and_trigger_stt, 'interval', minutes=5)

    # 스케줄러 네트워크 시작
    scheduler.start()
    
    print(f"[{datetime.now()}] 🛰️ Earning Whisperer 관제 관제탑 기동")
    print("⏰ 새벽 마스터 체인 스케줄링 및 실시간 5분 주기 어닝 존 추적망 예약 완료.")

    # 비동기 상주 홀딩 루프
    while True:
        await asyncio.sleep(1)