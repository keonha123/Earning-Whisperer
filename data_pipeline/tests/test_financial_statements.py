import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.financial_statements import get_m7_tickers
from collectors.financial_statements.yfinance import YFinanceFinancialStatementStrategy


class FinancialStatementStrategyTest(unittest.TestCase):
    def test_statement_to_records_flattens_quarterly_dataframe(self):
        strategy = YFinanceFinancialStatementStrategy()
        df = pd.DataFrame(
            {
                pd.Timestamp("2025-03-31"): [100.0, None],
                pd.Timestamp("2024-12-31"): [90.0, 20.0],
            },
            index=["Total Revenue", "Net Income"],
        )

        records = strategy._statement_to_records(
            ticker="AAPL",
            statement_type="income_statement",
            df=df,
            collected_at=datetime(2026, 5, 18, 0, 0, 0),
        )

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["ticker"], "AAPL")
        self.assertEqual(records[0]["statement_type"], "income_statement")
        self.assertEqual(records[0]["frequency"], "quarterly")
        self.assertEqual(records[0]["line_item"], "Total Revenue")
        self.assertEqual(records[0]["value"], 100.0)
        self.assertEqual(str(records[0]["fiscal_period_end"]), "2025-03-31")
        self.assertEqual(records[0]["source"], "yfinance")

    def test_statement_to_records_skips_empty_and_non_numeric_values(self):
        strategy = YFinanceFinancialStatementStrategy()
        df = pd.DataFrame(
            {pd.Timestamp("2025-03-31"): ["not-a-number", pd.NA]},
            index=["Bad Item", "Missing Item"],
        )

        records = strategy._statement_to_records(
            ticker="MSFT",
            statement_type="balance_sheet",
            df=df,
            collected_at=datetime(2026, 5, 18, 0, 0, 0),
        )

        self.assertEqual(records, [])

    def test_m7_universe_defaults_to_expected_tickers(self):
        self.assertEqual(
            get_m7_tickers(),
            ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA"],
        )


if __name__ == "__main__":
    unittest.main()
