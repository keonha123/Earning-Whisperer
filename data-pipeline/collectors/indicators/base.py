from abc import abstractmethod
from ..base import BaseCollector
from typing import List, Dict

class IndicatorCollector(BaseCollector[List[Dict]]):
    """지표(Indicators) 수집 전략의 추상 베이스 클래스"""
    @abstractmethod
    def collect(self, ticker_list: List[str]) -> List[Dict]:
        """티커 리스트를 받아 정적 지표(52주 고점 등)를 계산하여 반환"""
        pass