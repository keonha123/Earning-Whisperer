import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.exc import SQLAlchemyError

try:
    from .config import load_project_env
except ImportError:
    from config import load_project_env


load_project_env()

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

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value) if minimum is not None else value


def _scheduler_timezone() -> ZoneInfo:
    value = os.getenv("SCHEDULER_TIMEZONE", "Asia/Seoul").strip()
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        print(
            f"[Scheduler] unknown timezone={value}; falling back to Asia/Seoul",
            flush=True,
        )
        return ZoneInfo("Asia/Seoul")


async def _refresh_live_schedule_on_startup_with_retry(
    orch: EarningsOrchestrator,
) -> bool:
    """Retry the full startup refresh while MySQL is still coming online."""
    max_attempts = _env_int("SCHEDULE_STARTUP_REFRESH_MAX_ATTEMPTS", 6, 1)
    base_delay_seconds = _env_int("SCHEDULE_STARTUP_REFRESH_RETRY_SECONDS", 15, 1)

    for attempt in range(1, max_attempts + 1):
        try:
            await asyncio.to_thread(orch.refresh_live_schedule_data)
        except SQLAlchemyError as exc:
            if attempt >= max_attempts:
                print(
                    "[Scheduler] startup schedule refresh abandoned after "
                    f"{attempt}/{max_attempts} database attempts: {exc}",
                    flush=True,
                )
                return False

            delay_seconds = base_delay_seconds * attempt
            print(
                "[Scheduler] startup schedule refresh waiting for database "
                f"attempt={attempt}/{max_attempts} retry_in={delay_seconds}s: {exc}",
                flush=True,
            )
            await asyncio.sleep(delay_seconds)
        except Exception as exc:
            print(
                "[Scheduler] startup schedule refresh failed without a database "
                f"retry: {exc}",
                flush=True,
            )
            return False
        else:
            print(
                f"[Scheduler] startup schedule refresh completed attempt={attempt}/{max_attempts}",
                flush=True,
            )
            return True

    return False


async def start_scheduling():
    scheduler_timezone = _scheduler_timezone()
    scheduler = AsyncIOScheduler(timezone=scheduler_timezone)
    orch = EarningsOrchestrator()

    # ==========================================================
    # [PART 1] 데이터 동기화 작전 (정식 스케줄)
    # ==========================================================

    # [Step 1] 매일 새벽 04:00 - S&P 500 종목 리스트 갱신
    scheduler.add_job(orch.sync_stock_master, 'cron', hour=4, minute=0)

    # [Step 0] 매일 새벽 04:10 - 종목별 정적 지표(Cache) 계산
    scheduler.add_job(orch.sync_daily_indicators, 'cron', hour=4, minute=10)

    # [Step 2] 매일 새벽 04:30 - Yahoo 날짜 갱신, Nasdaq 대조, IR 재검증
    scheduler.add_job(
        orch.refresh_live_schedule_data,
        'cron',
        hour=4,
        minute=30,
        id='daily_schedule_source_reconciliation',
        name='Refresh and reconcile near-term earnings schedules',
        max_instances=1,
        coalesce=True,
    )

    # [Step 2.5] 매일 새벽 04:50 - 공식 이벤트 URL 선확보 및 시작 시각 검증
    scheduler.add_job(orch.enrich_schedule_times, 'cron', hour=4, minute=50, args=[20])

    # Exact start times are not available from one complete, trustworthy source
    # for every issuer. Prefetch event/provider routes and recheck a bounded
    # near-term set throughout the day, then refresh once after a restart.
    schedule_time_refresh_minutes = _env_int(
        "SCHEDULE_TIME_REFRESH_INTERVAL_MINUTES",
        10,
        1,
    )
    scheduler.add_job(
        orch.enrich_schedule_times,
        "interval",
        minutes=schedule_time_refresh_minutes,
        args=[_env_int("SCHEDULE_TIME_REFRESH_LIMIT", 20, 1)],
        id="schedule_time_reverify",
        name="Reverify near-term earnings start times",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(scheduler_timezone) + timedelta(
            minutes=schedule_time_refresh_minutes
        ),
    )
    if _env_bool("LIVE_SCHEDULE_REFRESH_ON_STARTUP", True):
        scheduler.add_job(
            _refresh_live_schedule_on_startup_with_retry,
            "date",
            args=[orch],
            run_date=datetime.now(scheduler_timezone),
            id="live_schedule_refresh_on_startup",
            name="Refresh earnings dates and near-term start times on startup",
            max_instances=1,
            misfire_grace_time=300,
        )

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
    scheduler.add_job(
        orch.retry_transcript_outbox,
        "interval",
        seconds=_env_int("TRANSCRIPT_OUTBOX_RETRY_INTERVAL_SECONDS", 30, 10),
        id="transcript_outbox_retry",
        name="Retry transcript deliveries",
        max_instances=1,
        coalesce=True,
    )
    recovery_interval_seconds = _env_int(
        "DATE_STREAM_RECOVERY_INTERVAL_SECONDS", 60, 30
    )
    # On startup, reclaim only leases that can be proved to belong to a dead
    # process on this host. Remote workers still rely on their normal expiry.
    scheduler.add_job(
        orch.recover_stale_stream_operations,
        "date",
        kwargs={"recover_local_orphans": True},
        run_date=datetime.now(scheduler_timezone),
        id="date_stream_startup_recovery",
        name="Recover local webcast operations after restart",
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        orch.recover_stale_stream_operations,
        "interval",
        seconds=recovery_interval_seconds,
        id="date_stream_recovery",
        name="Recover stale webcast operations",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(scheduler_timezone) + timedelta(
            seconds=recovery_interval_seconds
        ),
    )
    scheduler.add_job(
        orch.check_operational_alerts,
        "interval",
        seconds=_env_int("OPERATIONS_ALERT_INTERVAL_SECONDS", 300, 60),
        id="operations_alerts",
        name="Check webcast operational alerts",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(scheduler_timezone),
    )
    # 매일 운영 결과를 한 번에 검토할 수 있도록 JSON/Markdown 리포트 생성
    scheduler.add_job(
        orch.write_operations_report,
        'cron',
        hour=_env_int("OPERATIONS_REPORT_HOUR", 23, 0),
        minute=_env_int("OPERATIONS_REPORT_MINUTE", 55, 0),
        id='operations_daily_report',
        name='Write daily webcast operations report',
        max_instances=1,
        coalesce=True,
    )

    # [Step 3] 매 1시간마다 - 최근 7일간의 주가 데이터 동기화
    scheduler.add_job(orch.sync_stock_prices, 'interval', hours=1, args=[7])

    # 매 10분마다 - Finnhub 뉴스 수집 및 ai-engine 전달
    # Local-only STT validation must not accidentally deliver unrelated news.
    if _env_bool("ENABLE_FINNHUB_NEWS_JOB", True):
        scheduler.add_job(
            run_finnhub_news_once,
            "interval",
            minutes=get_finnhub_news_interval_minutes(),
            id="finnhub_company_news",
            name="Collect Finnhub company news",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    else:
        print("[Scheduler] Finnhub news job disabled", flush=True)

    # ==========================================================
    # [PART 2] 실시간 어닝콜 감시
    # ==========================================================
    enable_legacy_monitor = _env_bool("ENABLE_STT_MONITOR")
    enable_date_stream_watch = _env_bool("ENABLE_DATE_STREAM_WATCH")
    if enable_legacy_monitor and enable_date_stream_watch:
        # Both jobs claim the same call rows. Keep one authoritative live path
        # so a single event cannot trigger duplicate browser probes/submissions.
        print(
            "[Scheduler] both live monitors enabled; using date-based watcher only",
            flush=True,
        )
        enable_legacy_monitor = False

    if enable_legacy_monitor:
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

    if enable_date_stream_watch:
        # This job only dispatches background browser probes. Keep its cadence
        # fixed at one minute so a long probe cannot postpone the next scan.
        date_stream_watch_interval = 1
        scheduler.add_job(
            orch.dispatch_date_based_streams,
            'interval',
            minutes=date_stream_watch_interval,
            id='date_stream_watch',
            name='Dispatch date-based earnings webcast probes',
            # Dispatch is deliberately short; leases prevent duplicate work.
            max_instances=1,
            coalesce=True,
            # Do not wait for the first interval after a restart; an event may
            # already be inside its live window when the container comes up.
            next_run_time=datetime.now(scheduler_timezone),
        )

    # 스케줄러 시작
    scheduler.start()

    print(
        f"[{datetime.now(scheduler_timezone)}] Earning Whisperer 관제 시작 "
        f"timezone={scheduler_timezone.key}",
        flush=True,
    )
    print("⏰ 모든 정기 업데이트 작업이 예약되었습니다.")
    if enable_legacy_monitor:
        print("📢 Phase 4(STT 모니터링)가 활성화되었습니다.")
    else:
        print("📢 구형 STT 모니터링은 비활성화되었습니다.")
    if enable_date_stream_watch:
        print(
            "📡 날짜 기반 라이브 감시 활성화 "
            f"interval={date_stream_watch_interval}m "
            f"auto_capture={_env_bool('DATE_STREAM_AUTO_CAPTURE_ENABLED', True)}",
            flush=True,
        )
    else:
        print("📡 날짜 기반 라이브 감시는 ENABLE_DATE_STREAM_WATCH=true 설정 전까지 대기 중입니다.")

    # 비동기 루프 유지 (서버 상주)
    while True:
        await asyncio.sleep(1)


def main():
    asyncio.run(start_scheduling())


if __name__ == "__main__":
    main()
