from abc import abstractmethod  # 👈 [핵심] 여기도 추가!
from ..base import BaseCollector
from typing import Optional

class StreamLinkCollector(BaseCollector[str]):
    @abstractmethod
    def collect(self, ticker: str) -> Optional[str]:
        pass