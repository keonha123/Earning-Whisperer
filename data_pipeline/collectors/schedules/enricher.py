# data_pipeline/collectors/schedules/enricher.py

import os
import requests
from datetime import datetime

class ScheduleEnricher:
    def __init__(self):
        self.api_key = os.getenv("SERPER_API_KEY")

    def find_exact_time(self, ticker, company_name, date_str):
        """
        구글 검색을 통해 특정 기업 어닝콜의 정확한 시간을 찾습니다.
        예: "Apple earnings call time May 4 2026"
        """
        query = f"{company_name} ({ticker}) earnings call time {date_str}"
        # Serper API 등을 사용하여 검색 결과에서 "5:00 PM ET" 같은 문자열 추출
        # 추출된 문자열을 파이썬 datetime 객체로 변환하여 반환
        return "17:00" # (예시: 오후 5시)

    def run_daily_enrichment(self):
        # 1. DB에서 오늘 어닝콜 예정인 종목 추출
        today_calls = database.get_today_earnings_calls()
        
        for call in today_calls:
            # 2. 정확한 시간 검색
            exact_time = self.find_exact_time(call['ticker'], call['company_name'], call['earning_date'])
            
            # 3. DB 업데이트 (날짜 + 시간 합치기)
            database.update_earning_time(call['ticker'], exact_time)