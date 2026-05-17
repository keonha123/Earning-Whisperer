import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from collectors import CollectorChain
from collectors.stocks import WikipediaStrategy
from collectors.schedules import YFinanceScheduleStrategy
from collectors.prices import YFinancePriceStrategy
from collectors.indicators import YFinanceIndicatorStrategy
from collectors.financial_statements import (
    YFinanceFinancialStatementStrategy,
    get_financial_statement_universe,
    get_m7_tickers,
)
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
