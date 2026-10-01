import os
from typing import List


M7_TICKERS = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA"]


def get_financial_statement_universe() -> str:
    return os.getenv("FINANCIAL_STATEMENT_UNIVERSE", "m7").strip().lower()


def get_m7_tickers() -> List[str]:
    return list(M7_TICKERS)
