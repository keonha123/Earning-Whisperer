from abc import abstractmethod  # 👈 [핵심] 이 줄을 추가하세요!
from ..base import BaseCollector
from typing import List, Dict, Optional

class ScheduleCollector(BaseCollector[List[Dict]]):
    @abstractmethod
    def collect(self, ticker: str) -> Optional[List[Dict]]:
        pass