from abc import abstractmethod
from typing import Dict, List

from ..base import BaseCollector


class FinancialStatementCollector(BaseCollector[List[Dict]]):
    """Base collector for quarterly financial statement line items."""

    @abstractmethod
    def collect(self, ticker: str) -> List[Dict]:
        pass
