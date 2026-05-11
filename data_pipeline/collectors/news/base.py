from abc import abstractmethod
from typing import Dict, List

from ..base import BaseCollector


class NewsCollector(BaseCollector[List[Dict]]):
    @abstractmethod
    def collect(self, tickers: List[str]) -> List[Dict]:
        pass
