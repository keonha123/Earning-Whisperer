from abc import abstractmethod
from ..base import BaseCollector
from typing import List, Dict

class PriceCollector(BaseCollector[List[Dict]]):
    @abstractmethod
    def collect(self, ticker: str, start_date: str, end_date: str) -> List[Dict]:
        pass