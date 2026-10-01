from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
import yfinance as yf

from .base import FinancialStatementCollector


STATEMENT_GETTERS = {
    "income_statement": "get_income_stmt",
    "balance_sheet": "get_balance_sheet",
    "cash_flow": "get_cashflow",
}


class YFinanceFinancialStatementStrategy(FinancialStatementCollector):
    """Collect quarterly income, balance sheet, and cash flow items from yfinance."""

    def collect(self, ticker: str) -> List[Dict]:
        stock = yf.Ticker(ticker)
        collected_at = datetime.now(timezone.utc).replace(tzinfo=None)
        records: List[Dict] = []

        for statement_type, getter_name in STATEMENT_GETTERS.items():
            try:
                statement_df = self._get_statement(stock, getter_name)
                records.extend(
                    self._statement_to_records(
                        ticker=ticker,
                        statement_type=statement_type,
                        df=statement_df,
                        collected_at=collected_at,
                    )
                )
            except Exception as exc:
                print(f"[FinancialStatements] {ticker} {statement_type} collect failed: {exc}")

        return records

    def _get_statement(self, stock: yf.Ticker, getter_name: str) -> pd.DataFrame:
        getter = getattr(stock, getter_name)
        df = getter(freq="quarterly")
        if df is None:
            return pd.DataFrame()
        return df

    def _statement_to_records(
        self,
        ticker: str,
        statement_type: str,
        df: pd.DataFrame,
        collected_at: datetime,
    ) -> List[Dict]:
        if df is None or df.empty:
            return []

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)

        records: List[Dict] = []
        for line_item, row in df.iterrows():
            for period_end, value in row.items():
                if pd.isna(value):
                    continue

                period_date = pd.to_datetime(period_end, errors="coerce")
                if pd.isna(period_date):
                    continue

                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue

                records.append(
                    {
                        "ticker": ticker,
                        "statement_type": statement_type,
                        "fiscal_period_end": period_date.date(),
                        "frequency": "quarterly",
                        "line_item": str(line_item),
                        "value": numeric_value,
                        "source": "yfinance",
                        "collected_at": collected_at,
                    }
                )

        return records
