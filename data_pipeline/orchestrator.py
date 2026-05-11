import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from collectors import CollectorChain
from collectors.stocks import WikipediaStrategy
from collectors.schedules import YFinanceScheduleStrategy
from collectors.prices import YFinancePriceStrategy
from collectors.indicators import YFinanceIndicatorStrategy
import database

load_dotenv()

class EarningsOrchestrator:
    def __init__(self):
        # 각 단계별 "체인" 정의 (합성함수 구조)
        self.stock_chain = CollectorChain([WikipediaStrategy()])
        self.schedule_chain = CollectorChain([YFinanceScheduleStrategy()])
        self.price_chain = CollectorChain([YFinancePriceStrategy()])
        self.indicator_chain = CollectorChain([YFinanceIndicatorStrategy()])

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

    async def monitor_and_trigger_stt(self):
        """
        [Phase 4] 실시간 어닝콜 감시 및 워커 실행 로직 (뼈대)
        매 분마다 호출되어 DB를 확인하고, 임박한 일정이 있다면 워커를 깨웁니다.
        """
        from datetime import datetime
        # 시각적인 확인을 위해 현재 감시 중임을 표시합니다. (운영 시에는 선택 사항)
        # print(f"🔍 [Monitor] {datetime.now().strftime('%H:%M:%S')} 어닝콜 일정 스캔 중...")

        try:
            # 1. DB에서 '현재 시간'과 '시작 시간'이 일치하거나 임박한 종목 조회
            # imminent_calls = database.get_imminent_calls(minutes_ahead=2)
            imminent_calls = [] # 아직 DB 조회 로직이 없으므로 빈 리스트로 둡니다.

            if not imminent_calls:
                return

            for call in imminent_calls:
                ticker = call.get('ticker')
                ir_url = call.get('ir_url')
                
                print(f"🚀 [Orchestrator] {ticker} 어닝콜 임박 감지! 워커 배정을 시작합니다.")
                
                # 2. STT 워커 매니저에게 비동기로 작업 전달
                # (manager.py의 입구 함수를 호출하는 부분 - 추후 연결)
                # asyncio.create_task(self.worker_manager.start_worker(ticker, ir_url))
                
                # 3. 중복 실행 방지를 위해 DB 상태를 'RUNNING' 등으로 업데이트
                # database.update_call_status(ticker, 'RUNNING')

        except Exception as e:
            print(f"❌ [Monitor Error] 감시 로직 실행 중 오류 발생: {e}")
            
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
    
    print("\n✨ 모든 데이터 동기화가 완료되었습니다.")