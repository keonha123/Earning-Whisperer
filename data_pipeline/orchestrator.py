import asyncio
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

try:
    from .collectors import CollectorChain
    from .collectors.stocks import WikipediaStrategy
    from .collectors.schedules import YFinanceScheduleStrategy
    from .collectors.schedules.enricher import OfficialScheduleEnricher
    from .collectors.prices import YFinancePriceStrategy
    from .collectors.indicators import YFinanceIndicatorStrategy
    from .collectors.financial_statements import (
        YFinanceFinancialStatementStrategy,
        get_financial_statement_universe,
        get_m7_tickers,
    )
    from .stt_worker.manager import STTWorkerManager
    from . import database
except ImportError:  # Allows `python data_pipeline/orchestrator.py`.
    from collectors import CollectorChain
    from collectors.stocks import WikipediaStrategy
    from collectors.schedules import YFinanceScheduleStrategy
    from collectors.schedules.enricher import OfficialScheduleEnricher
    from collectors.prices import YFinancePriceStrategy
    from collectors.indicators import YFinanceIndicatorStrategy
    from collectors.financial_statements import (
        YFinanceFinancialStatementStrategy,
        get_financial_statement_universe,
        get_m7_tickers,
    )
    from stt_worker.manager import STTWorkerManager
    import database

load_dotenv()

class EarningsOrchestrator:
    def __init__(self):
        # 각 단계별 "체인" 정의 (합성함수 구조)
        self.stock_chain = CollectorChain([WikipediaStrategy()])
        self.schedule_chain = CollectorChain([YFinanceScheduleStrategy()])
        self.price_chain = CollectorChain([YFinancePriceStrategy()])
        self.indicator_chain = CollectorChain([YFinanceIndicatorStrategy()])
        self.financial_statement_chain = CollectorChain([YFinanceFinancialStatementStrategy()])
        self.worker_manager = STTWorkerManager()

    @staticmethod
    def _record_operation(event_type: str, **payload: Any) -> None:
        try:
            from .operations import record_event
        except ImportError:
            from operations import record_event
        try:
            record_event(event_type, **payload)
        except Exception as exc:
            print(f"[OperationsLog] write skipped: {str(exc)[:160]}")

    @staticmethod
    def _maintenance_window_active() -> bool:
        start_text = os.getenv("DATE_STREAM_MAINTENANCE_START", "").strip()
        end_text = os.getenv("DATE_STREAM_MAINTENANCE_END", "").strip()
        if not start_text or not end_text:
            return False
        try:
            start = datetime.strptime(start_text, "%H:%M").time()
            end = datetime.strptime(end_text, "%H:%M").time()
        except ValueError:
            return False
        current = datetime.now().time()
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    @staticmethod
    def _probe_window(call: dict[str, Any], base_cooldown_minutes: int) -> tuple[str, int]:
        """Return a watch state and cooldown, tightening probes around verified times."""
        scheduled = call.get("scheduled_at_utc")
        if not scheduled:
            return "date_only", max(1, base_cooldown_minutes)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        before_minutes = max(0, int(os.getenv("DATE_STREAM_NEAR_START_MINUTES", "20")))
        after_minutes = max(0, int(os.getenv("DATE_STREAM_NEAR_END_MINUTES", "180")))
        start = scheduled - timedelta(minutes=before_minutes)
        end = scheduled + timedelta(minutes=after_minutes)
        if now < start:
            return "scheduled", max(1, base_cooldown_minutes)
        if now <= end:
            return "event_window", max(1, int(os.getenv("DATE_STREAM_NEAR_INTERVAL_MINUTES", "1")))
        return "post_event", max(1, base_cooldown_minutes)

    def sync_stock_master(self):
        """[Phase 1] S&P 500 종목 리스트 동기화"""
        print("\n[Step 1] S&P 500 종목 리스트 동기화...")
        stocks = self.stock_chain.execute()
        if stocks:
            database.save_stocks(stocks)
        pass

    def sync_daily_indicators(self):
        """[Step 0] 종목별 정적 지표(52주 고점, 평균 거래량) 동기화"""
        print("\n[Step 0] 종목별 정적 지표(Cache) 동기화 시작...")
        
        # DB에서 전체 티커 리스트 가져오기
        tickers = database.get_all_tickers()
        if not tickers:
            print("⚠️ DB에 티커가 없습니다. Step 1이 먼저 성공해야 합니다.")
            return

        # 지표 연산 전략 실행
        # (YFinanceIndicatorStrategy가 야후에서 1년치 일봉을 긁어옵니다)
        indicators = self.indicator_chain.execute(tickers)
        
        # 결과가 있다면 DB의 stocks 테이블에 박제(UPDATE)
        if indicators:
            database.update_static_indicators(indicators)
            print(f"✅ {len(indicators)}개 종목의 정적 지표 동기화 완료.")
        else:
            print("⚠️ 동기화할 지표 데이터가 없습니다.")


    def _fetch_single_schedule(self, ticker):
        """멀티쓰레딩용 개별 일정 수집 작업"""
        try:
            return self.schedule_chain.execute(ticker)
        except Exception as e:
            print(f"❌ {ticker} 일정 수집 중 오류: {e}")
            return None

    def _resolve_financial_statement_tickers(self, universe=None):
        # 재무제표 수집 대상 universe를 결정한다.
        # 인자가 없으면 FINANCIAL_STATEMENT_UNIVERSE 환경 변수의 값을 사용하고,
        # 환경 변수도 없으면 config.py의 기본값인 "m7"을 사용한다.
        selected_universe = (universe or get_financial_statement_universe()).lower()

        if selected_universe == "m7":
            return get_m7_tickers()

        if selected_universe in {"stocks_table", "sp500"}:
            return database.get_all_tickers()

        raise ValueError(f"Unsupported financial statement universe: {selected_universe}")

    def _fetch_single_financial_statement(self, ticker):
        # ThreadPoolExecutor에서 ticker별로 호출되는 단일 수집 작업이다.
        # CollectorChain을 통해 yfinance 재무제표 수집 전략을 실행한다.
        try:
            return self.financial_statement_chain.execute(ticker)
        except Exception as e:
            # 특정 ticker 수집 실패가 전체 배치 중단으로 이어지지 않도록 None을 반환한다.
            print(f"[FinancialStatements] {ticker} collect failed: {e}")
            return None

    def sync_financial_statements(self, universe=None, max_workers=5):
        """Collect quarterly financial statements for the configured ticker universe."""
        # universe 설정에 따라 이번 배치에서 수집할 ticker 목록을 만든다.
        tickers = self._resolve_financial_statement_tickers(universe)
        if not tickers:
            print("[FinancialStatements] No tickers to collect.")
            return

        print(
            f"\n[FinancialStatements] Collecting quarterly statements "
            f"for {len(tickers)} tickers with {max_workers} workers..."
        )

        all_results = []
        # ticker별 yfinance 요청은 서로 독립적이므로 병렬로 실행한다.
        # max_workers는 yfinance 요청량을 조절하는 안전장치 역할도 한다.
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {
                executor.submit(self._fetch_single_financial_statement, ticker): ticker
                for ticker in tickers
            }
            for future in as_completed(future_to_ticker):
                result = future.result()
                if result:
                    all_results.extend(result)

        # 하나 이상의 line item이 수집된 경우에만 DB 저장을 수행한다.
        # save_financial_statement_items()는 테이블 생성과 upsert를 함께 처리한다.
        if all_results:
            database.save_financial_statement_items(all_results)
            print(f"[FinancialStatements] Synced {len(all_results)} statement items.")
        else:
            print("[FinancialStatements] No statement items collected.")

    def update_all_schedules(self, max_workers=10):
        """[Phase 2] 전 종목의 어닝 일정 병렬 수집"""
        print(f"\n[Step 2] 전 종목 어닝 일정 병렬 수집 시작 (쓰레드: {max_workers}개)...")
        tickers = database.get_all_tickers()
        if not tickers: return

        all_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {executor.submit(self._fetch_single_schedule, t): t for t in tickers}
            for future in as_completed(future_to_ticker):
                result = future.result()
                if result: all_results.extend(result)
        
        if all_results:
            database.save_earnings_schedules(all_results)
            print(f"✅ 총 {len(all_results)}개의 일정을 DB에 동기화했습니다.")

    def enrich_schedule_times(self, limit: int = 20):
        """Verify near-term call times only from issuer-owned evidence."""
        calls = database.get_calls_missing_verified_time(limit=limit)
        if not calls:
            print("[ScheduleTime] No unverified future calls to process.")
            return

        enricher = OfficialScheduleEnricher()
        verified_count = 0
        for call in calls:
            verified = enricher.verify_call(call)
            if verified:
                verified_count += 1
                print(
                    f"[ScheduleTime] {call['ticker']} verified "
                    f"{verified.scheduled_at_utc.isoformat()}"
                )
            else:
                print(f"[ScheduleTime] {call['ticker']} remains unverified")

        print(f"[ScheduleTime] Verified {verified_count}/{len(calls)} calls.")

    def sync_stock_prices(self, days_back=5):
        """[Phase 3] 주가 데이터 수집 (어닝콜 분석용 Ground Truth)"""
        from datetime import datetime, timedelta
        print(f"\n[Step 3] 최근 {days_back}일간의 주가 데이터 수집 시작...")
        
        tickers = database.get_all_tickers()
        
        # 날짜 설정
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days_back)
        
        # 우선 테스트를 위해 상위 10개만 순차적으로 수집해봅니다. 
        # (성공 확인 후 나중에 이것도 병렬로 바꿀 수 있습니다.)
        for t in tickers[:10]:
            price_data = self.price_chain.execute(
                t, 
                start_dt.strftime('%Y-%m-%d'), 
                end_dt.strftime('%Y-%m-%d')
            )
            if price_data:
                database.save_prices(price_data)

    def maintain_transcript_archive(self):
        """Keep transcript history bounded while retaining recent recovery data."""
        try:
            from .maintenance import purge_webcast_artifacts
        except ImportError:
            from maintenance import purge_webcast_artifacts

        retention_days = max(1, int(os.getenv("TRANSCRIPT_RETENTION_DAYS", "180")))
        deleted = database.purge_transcript_segments(
            retention_days,
            batch_size=int(os.getenv("TRANSCRIPT_PURGE_BATCH_SIZE", "10000")),
            max_batches=int(os.getenv("TRANSCRIPT_PURGE_MAX_BATCHES", "10")),
        )
        artifact_deleted = purge_webcast_artifacts(
            int(os.getenv("WEBCAST_ARTIFACT_RETENTION_DAYS", "14")),
            max_groups=int(os.getenv("WEBCAST_ARTIFACT_MAX_GROUPS", "2000")),
        )
        if deleted:
            print(
                f"[TranscriptArchive] purged {deleted} segments "
                f"older than {retention_days} days"
            )
        if artifact_deleted:
            print(f"[WebcastArtifacts] purged {artifact_deleted} generated files")

    def write_operations_report(self):
        """Write the current UTC day's machine-readable and human-readable report."""
        try:
            from .operations import write_daily_report
        except ImportError:
            from operations import write_daily_report
        json_path, markdown_path = write_daily_report()
        print(f"[OperationsReport] JSON={json_path} Markdown={markdown_path}")

    async def monitor_and_trigger_stt(self):
        """
        [Phase 4] 실시간 어닝콜 감시 및 워커 실행 로직 (뼈대)
        매 분마다 호출되어 DB를 확인하고, 임박한 일정이 있다면 워커를 깨웁니다.
        """
        # 시각적인 확인을 위해 현재 감시 중임을 표시합니다. (운영 시에는 선택 사항)
        # print(f"🔍 [Monitor] {datetime.now().strftime('%H:%M:%S')} 어닝콜 일정 스캔 중...")

        try:
            imminent_calls = database.get_imminent_calls(minutes_ahead=5, grace_minutes=1)

            if not imminent_calls:
                return

            for call in imminent_calls:
                call_id = call.get('id')
                ticker = call.get('ticker')
                
                print(f"🚀 [Orchestrator] {ticker} 어닝콜 임박 감지! 워커 배정을 시작합니다.")

                if not database.mark_call_running(call_id):
                    print(f"↪️ [Orchestrator] {ticker}는 이미 다른 워커가 처리 중입니다.")
                    continue

                try:
                    await self.worker_manager.launch_mission(call)
                except Exception as worker_error:
                    database.update_call_status(call_id, 'failed')
                    print(f"❌ [Orchestrator] {ticker} 워커 실행 실패: {worker_error}")

        except Exception as e:
            print(f"❌ [Monitor Error] 감시 로직 실행 중 오류 발생: {e}")

    async def monitor_date_based_streams(self):
        """Probe today's/tomorrow's calls, tightening checks around known start times."""
        if self._maintenance_window_active():
            self._record_operation("watch_cycle", status="maintenance", candidates=0)
            print("[DateStreamWatch] maintenance window active; skipping new probes")
            return

        days_ahead = int(os.getenv("DATE_STREAM_WATCH_DAYS_AHEAD", "2"))
        max_candidates = int(os.getenv("DATE_STREAM_WATCH_BATCH_SIZE", "10"))
        cooldown_minutes = int(os.getenv("DATE_STREAM_WATCH_COOLDOWN_MINUTES", "15"))
        near_start_minutes = int(os.getenv("DATE_STREAM_NEAR_START_MINUTES", "20"))
        near_end_minutes = int(os.getenv("DATE_STREAM_NEAR_END_MINUTES", "180"))
        near_cooldown_minutes = int(os.getenv("DATE_STREAM_NEAR_INTERVAL_MINUTES", "1"))
        concurrency = max(1, int(os.getenv("DATE_STREAM_WATCH_CONCURRENCY", "3")))
        candidates = database.get_date_based_stream_candidates(
            days_ahead=days_ahead,
            limit=max_candidates,
            cooldown_minutes=cooldown_minutes,
            near_start_minutes=near_start_minutes,
            near_end_minutes=near_end_minutes,
            near_cooldown_minutes=near_cooldown_minutes,
        )
        configured_tickers = {
            ticker.strip().upper()
            for ticker in os.getenv("DATE_STREAM_WATCH_TICKERS", "").split(",")
            if ticker.strip()
        }
        if configured_tickers:
            candidates = [
                call for call in candidates
                if str(call.get("ticker") or "").upper() in configured_tickers
            ]
        self._record_operation(
            "watch_cycle",
            status="candidates" if candidates else "idle",
            candidates=len(candidates),
            days_ahead=days_ahead,
            concurrency=concurrency,
        )
        if not candidates:
            return

        semaphore = asyncio.Semaphore(concurrency)

        async def process(call: dict[str, Any]) -> None:
            async with semaphore:
                try:
                    call_id = call["id"]
                    watch_state, probe_cooldown = self._probe_window(call, cooldown_minutes)
                    self._record_operation(
                        "probe_started",
                        ticker=call.get("ticker"),
                        call_id=call_id,
                        watch_state=watch_state,
                        scheduled_at_utc=call.get("scheduled_at_utc"),
                        probe_cooldown_minutes=probe_cooldown,
                    )
                    if not database.claim_stream_probe(call_id, cooldown_minutes=probe_cooldown):
                        return

                    capture_settings = {"WEBCAST_LIFECYCLE": "live"}
                    for key in (
                        "STT_MODEL_NAME",
                        "STT_MAX_CHUNKS",
                        "SEND_TO_AI_ENGINE",
                        "SEND_TO_BACKEND",
                        "TRANSCRIPT_ARCHIVE_ENABLED",
                        "AI_ENGINE_URL",
                        "BACKEND_URL",
                        "INTERNAL_SECRET",
                    ):
                        if os.getenv(key) is not None:
                            capture_settings[key] = os.environ[key]
                    runtime_env = self.worker_manager.build_isolated_capture_environment(
                        call,
                        capture_settings,
                    )
                    ready, error = await self.worker_manager.probe_date_based_call(
                        call,
                        capture_env=runtime_env,
                    )
                    database.record_stream_probe(call_id, stream_ready=ready, error=error)
                    self._record_operation(
                        "probe_result",
                        ticker=call.get("ticker"),
                        call_id=call_id,
                        status="stream_ready" if ready else "pending",
                        error=error,
                        watch_state=watch_state,
                        probe_cooldown_minutes=probe_cooldown,
                    )
                    if not ready:
                        print(f"[DateStreamWatch] {call['ticker']} pending: {error}")
                        return

                    print(f"[DateStreamWatch] {call['ticker']} audible stream detected")
                    if os.getenv("DATE_STREAM_AUTO_CAPTURE_ENABLED", "true").lower() != "true":
                        return
                    if not database.mark_call_running(call_id):
                        self._record_operation(
                            "capture_skipped",
                            ticker=call.get("ticker"),
                            call_id=call_id,
                            status="already_claimed",
                        )
                        print(f"[DateStreamWatch] {call['ticker']} is already assigned to a worker")
                        return
                    try:
                        self._record_operation(
                            "capture_started",
                            ticker=call.get("ticker"),
                            call_id=call_id,
                            status="running",
                            watch_state=watch_state,
                        )
                        await self.worker_manager.launch_date_based_audio_capture(
                            call,
                            capture_env=runtime_env,
                        )
                    except Exception as exc:
                        database.update_call_status(call_id, "failed")
                        self._record_operation(
                            "capture_failed",
                            ticker=call.get("ticker"),
                            call_id=call_id,
                            status="failed",
                            error=str(exc),
                        )
                        print(f"[DateStreamWatch] {call['ticker']} capture launch failed: {exc}")
                except Exception as exc:
                    self._record_operation(
                        "probe_result",
                        ticker=call.get("ticker"),
                        call_id=call.get("id"),
                        status="error",
                        error=str(exc),
                    )
                    print(f"[DateStreamWatch] {call['ticker']} probe failed unexpectedly: {exc}")

        await asyncio.gather(*(process(call) for call in candidates))
            
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
