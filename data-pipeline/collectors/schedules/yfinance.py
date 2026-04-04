import yfinance as yf
from .base import ScheduleCollector

class YFinanceScheduleStrategy(ScheduleCollector):
    def collect(self, ticker: str) -> list[dict]:
        stock = yf.Ticker(ticker)
        calendar = stock.calendar
        
        if calendar and 'Earnings Date' in calendar:
            return [{
                "ticker": ticker,
                "earning_date": date_val,
                "event_type": "earnings_call"
            } for date_val in calendar['Earnings Date']]
        return []