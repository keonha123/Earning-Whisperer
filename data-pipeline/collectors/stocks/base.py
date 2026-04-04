from abc import abstractmethod  # 👈 [중요] 이 줄이 없으면 에러가 납니다!
from ..base import BaseCollector
from typing import List, Dict

class StockListCollector(BaseCollector[List[Dict]]):
    @abstractmethod
    def collect(self) -> List[Dict]:
        pass