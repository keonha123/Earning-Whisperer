import os
import requests
from datetime import datetime, timedelta
from .base import ScheduleCollector

class FinnhubScheduleStrategy(ScheduleCollector):
    def __init__(self):
        self.api_key = 'os.getenv("FINNHUB_API_KEY")'
        self.url = "https://finnhub.io/api/v1/calendar/earnings"

    def collect(self, ticker: str) -> list[dict]:
        if not self.api_key:
            print("⚠️ FINNHUB_API_KEY가 설정되지 않았습니다.")
            return []

        # 오늘부터 향후 30일간의 일정을 가져옵니다.
        start_date = datetime.now().strftime('%Y-%m-%d')
        end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')

        params = {
            "from": start_date,
            "to": end_date,
            "symbol": ticker,
            "token": self.api_key
        }

        try:
            response = requests.get(self.url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("earningsCalendar", []):
                # Finnhub은 'hour' 필드에 'amc', 'bmo' 혹은 'HH:mm'을 줍니다.
                raw_hour = item.get("hour", "")
                
                results.append({
                    "ticker": item.get("symbol"),
                    "earning_date": item.get("date"), # YYYY-MM-DD
                    "raw_hour": raw_hour,             # amc, bmo, 08:30 등
                    "event_type": "earnings_call"
                })
            return results

        except Exception as e:
            print(f"❌ Finnhub ({ticker}) 수집 중 오류: {e}")
            return []