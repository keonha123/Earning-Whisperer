from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional

# T는 결과 데이터의 타입 (List[dict] 혹은 str 등)
T = TypeVar('T')

class BaseCollector(ABC, Generic[T]):
    """모든 수집 전략의 최상위 부모"""
    @abstractmethod
    def collect(self, *args, **kwargs) -> Optional[T]:
        pass

class CollectorChain(Generic[T]):
    """책임 연쇄 패턴: 여러 전략을 순차적으로 시도"""
    def __init__(self, strategies: List[BaseCollector[T]]):
        self.strategies = strategies

    def execute(self, *args, **kwargs) -> Optional[T]:
        for strategy in self.strategies:
            try:
                result = strategy.collect(*args, **kwargs)
                if result:
                    return result
            except Exception as e:
                print(f"⚠️ {strategy.__class__.__name__} 실패: {e}")
        return None