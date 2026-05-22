# data_pipeline/orchestrator.py
import os
import sys
import time
import asyncio
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# 내부 패키지 및 수집 전략 임포트 (기존 유산 완벽 유지)
from collectors import CollectorChain
from collectors.stocks import WikipediaStrategy
from collectors.schedules import YFinanceScheduleStrategy
from collectors.prices import YFinancePriceStrategy
from collectors.indicators import YFinanceIndicatorStrategy
from collectors.schedules import FinnhubScheduleStrategy  
import data_pipeline.database as database

# 🎧 stt_worker 구역의 총괄 관리자 소환
from data_pipeline.stt_worker.manager import EarningManager

load_dotenv()

class EarningsOrchestrator:
    def __init__(self):
        # 각 단계별 "체인" 정의 (기존 합성함수 구조 완벽 유지)
        self.stock_chain = CollectorChain([WikipediaStrategy()])
        self.schedule_chain = CollectorChain([FinnhubScheduleStrategy()])
        self.price_chain = CollectorChain([YFinancePriceStrategy()])
        self.indicator_chain = CollectorChain([YFinanceIndicatorStrategy()])
        
        # 👑 실시간 도청 현황을 추적할 블랙리스트 장부 및 워커 관리자 개설
        self.worker_manager = EarningManager()
        self.running_agents = set()

    def sync_stock_master(self):
        """[Phase 1] S&P 500 종목 리스트 동기화"""
        print("\n[Step 1] S&P 500 종목 리스트 동기화...")
        stocks = self.stock_chain.execute()
        if stocks:
            database.save_stocks(stocks)

    def sync_daily_indicators(self):
        """[Step 0] 종목별 정적 지표(52주 고점, 평균 거래량) 동기화"""
        print("\n[Step 0] 종목별 정적 지표(Cache) 동기화 시작...")
        
        # DB에서 전체 티커 리스트 가져오기
        tickers = database.get_all_tickers()
        if not tickers:
            print("⚠️ DB에 티커가 없습니다. Step 1이 먼저 성공해야 합니다.")
            return

        # 지표 연산 전략 실행
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
        """[Phase 2] 전 종목의 어닝 일정 수집 및 KST 변환 저장"""
        print(f"\n[Step 2] Finnhub 기반 정밀 일정 수집 시작...")
        tickers = database.get_all_tickers()
        if not tickers: return

        raw_results = []
        # 1. 병렬 수집 (Finnhub에서 날짜와 raw_hour를 가져옴)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {executor.submit(self._fetch_single_schedule, t): t for t in tickers}
            for future in as_completed(future_to_ticker):
                res = future.result()
                if res: raw_results.extend(res)
        
        # 2. 시간 보정 (미국 시간 -> 한국 시간 변환)
        final_schedules = self._process_and_localize_time(raw_results)

        # 3. DB 저장
        if final_schedules:
            database.save_earnings_schedules(final_schedules)
            print(f"✅ 총 {len(final_schedules)}개의 정밀 일정을 KST로 저장 완료.")

    def _process_and_localize_time(self, raw_data_list):
        """
        Finnhub의 raw_hour를 기반으로 실제 한국 시각(KST)을 계산합니다.
        """
        processed = []
        et_tz = pytz.timezone('America/New_York')
        kst_tz = pytz.timezone('Asia/Seoul')

        for item in raw_data_list:
            date_str = item['earning_date']    # 예: "2026-05-22"
            raw_hour = item['raw_hour'].lower() # 예: "amc"

            # [규칙 1] amc/bmo 텍스트를 숫자로 변환
            if raw_hour == 'bmo':
                target_time = "08:30"  # 개장 전: 현지 08:30
            elif raw_hour == 'amc':
                target_time = "16:30"  # 장 마감 후: 현지 16:30
            elif ":" in raw_hour:
                target_time = raw_hour # 이미 숫자인 경우 그대로 사용
            else:
                target_time = "09:00"  # 예외 상황 기본값

            try:
                # [규칙 2] 미국 동부 시각(ET) 객체 생성
                et_naive = datetime.strptime(f"{date_str} {target_time}", "%Y-%m-%d %H:%M")
                et_dt = et_tz.localize(et_naive)

                # [규칙 3] 한국 시각(KST)으로 변환
                # (날짜가 다음 날로 넘어가는 것까지 자동으로 계산됨)
                kst_dt = et_dt.astimezone(kst_tz)

                # DB에 저장할 최종 필드 추가
                item['start_time'] = kst_dt.strftime('%Y-%m-%d %H:%M:%S')
                processed.append(item)

            except Exception as e:
                print(f"⚠️ {item['ticker']} 시간 변환 실패: {e}")
                
        return processed

    def sync_stock_prices(self, days_back=5):
        """[Phase 3] 주가 데이터 수집 (어닝콜 분석용 Ground Truth)"""
        print(f"\n[Step 3] 최근 {days_back}일간의 주가 데이터 수집 시작...")
        
        tickers = database.get_all_tickers()
        
        # 날짜 설정
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days_back)
        
        # 우선 테스트를 위해 상위 10개만 순차적으로 수집해봅니다.
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
        🔥 [Phase 4 - 완공] 날짜 깜깜이 데이터 전용 게릴라 정찰 오케스트레이션
        매 5분마다 스케줄러에 의해 호출되어, 지정된 '어닝 존' 안에서만 정찰대를 순간 소환합니다.
        """
        now_time = datetime.now()
        now_hour = now_time.hour
        
        # ① [어닝 존 필터] 미국 주식 시장의 어닝콜 집중 시간대 검증 (이 시간 외엔 자원 소비 0%)
        is_morning_zone = (20 <= now_hour <= 23)  # KST 저녁 20시 ~ 밤 23시 59분 (BMO 타겟)
        is_evening_zone = (4 <= now_hour <= 8)    # KST 새벽 04시 ~ 아침 08시 59분 (AMC 타겟)
        
        if not (is_morning_zone or is_evening_zone):
            return

        try:
            # ② DB에서 오늘 날짜('YYYY-MM-DD')에 해당하는 킬 리스트 전원 조회
            today_str = now_time.strftime('%Y-%m-%d')
            
            # 사용자님의 DB 헬퍼 함수를 호출하여 오늘 날짜 리스트 수집
            today_calls = database.get_calls_by_date(today_str) 

            if not today_calls:
                return

            for call in today_calls:
                ticker = call.get('ticker')
                ir_url = call.get('ir_url')
                
                # 이미 본방이 포착되어 서버에 상주하며 도청 중인 요원은 중복 정찰 금지
                if ticker in self.running_agents:
                    continue

                if not ir_url:
                    continue
                
                print(f"🕵️ [Orchestrator] 오늘자 어닝 존 대상종목 식별 ➔ [{ticker}]")
                
                # ③ 다른 스레드가 침투하기 전에 전역 장부에 락(Lock) 명시
                self.running_agents.add(ticker)
                
                # ④ 👑 관제탑 스케줄러 루프가 얼지 않도록 비동기 스레드로 매니저 살포 기동!
                asyncio.create_task(self._deploy_scout_agent(ticker, ir_url))

        except Exception as e:
            print(f"❌ [Monitor Error] 게릴라 정찰 제어레이어 예외: {e}")

    async def _deploy_scout_agent(self, ticker, ir_url):
        """ 🛡️ 매니저에게 우분투 오디오 가상 채널 환경을 할당하도록 지시하고 요원을 출격시킴 """
        print(f"🚀 [Orchestrator] 가상 사운드 인프라 래핑 후 [{ticker}] 정찰 프로세스 생성.")
        
        # 동기식 manager.launch_agent()를 비동기 스레드 풀에 위임 실행합니다.
        # 방이 안 열려서 요원이 금방 철수하면, 이 함수는 바로 False를 리턴하고 종료됩니다.
        is_active_streaming = await asyncio.to_thread(self.worker_manager.launch_agent, ticker, ir_url)
        
        # 작전 유닛이 죽거나 상주 모드를 마치고 퇴근하면 장부에서 완벽 자원 수거
        if ticker in self.running_agents:
            self.running_agents.remove(ticker)
            
            if not is_active_streaming:
                print(f"🧹 [Orchestrator] 정찰 리포트 ➔ [{ticker}] 아직 본방 미개설 상태 확인. 자원 회수 후 5분 뒤 재추적.")
            else:
                print(f"🏁 [Orchestrator] 작전 마감 완료 ➔ [{ticker}] 본방 캡처 성공 및 도청 종료로 자원 완전 청소.")

if __name__ == "__main__":
    orchestrator = EarningsOrchestrator()
    
    print("🚀 Earning Whisperer 데이터 파이프라인 가동...")
    
    # 1. 마스터 리스트 업데이트
    orchestrator.sync_stock_master()
    orchestrator.sync_daily_indicators()

    # 2. 어닝 일정 전체 업데이트 (병렬)
    orchestrator.update_all_schedules(max_workers=10)
    
    # 3. 주가 데이터 업데이트
    orchestrator.sync_stock_prices(days_back=7)
    
    print("\n✨ 모든 데이터 동기화가 완료되었습니다.")