# ═══════════════════════════════════════════════════════════════════════════
# core/context_manager.py
# 슬라이딩 윈도우 컨텍스트 관리
# 어닝콜 중 이전 발언 내용을 기억해 Gemini가 문맥을 이해할 수 있게 함
# ═══════════════════════════════════════════════════════════════════════════
from collections import deque
from dataclasses import dataclass, field
from config import settings


@dataclass
class ContextManager:
    """
    ticker별 최근 N개 텍스트 청크를 FIFO 큐로 관리.
    get_context() → Gemini USER_PROMPT의 PREVIOUS CONTEXT 섹션에 삽입됨.
    """
    # ticker → 최근 N개 청크 저장 (deque: maxlen 초과 시 가장 오래된 것 자동 삭제)
    _memory: dict = field(default_factory=dict)

    def get_context(self, ticker: str) -> str:
        """
        이전 청크들의 요약을 하나의 문자열로 반환.
        청크가 없으면 '(No previous context)' 반환.
        """
        if ticker not in self._memory or not self._memory[ticker]:
            return "(No previous context — this is the first chunk)"

        chunks = list(self._memory[ticker])

        # 각 청크를 최대 80자로 잘라서 연결 (토큰 비용 절약)
        summaries = []
        for i, chunk in enumerate(chunks):
            truncated = chunk[:80] + "..." if len(chunk) > 80 else chunk
            summaries.append(f"[{i+1}] {truncated}")

        context = " | ".join(summaries)

        # 전체 컨텍스트 길이 제한
        return context[:settings.context_summary_chars]

    def update(self, ticker: str, text_chunk: str) -> None:
        """
        새 청크를 컨텍스트에 추가 (FIFO, maxlen=N 초과 시 오래된 것 제거).
        """
        if ticker not in self._memory:
            self._memory[ticker] = deque(maxlen=settings.context_history_size)
        self._memory[ticker].append(text_chunk)

    def clear(self, ticker: str) -> None:
        """
        is_final=True 수신 시 해당 티커 컨텍스트 완전 초기화.
        어닝콜 세션이 끝나면 다음 어닝콜을 위해 메모리 비워야 함.
        """
        if ticker in self._memory:
            del self._memory[ticker]

    def get_all_tickers(self) -> list:
        """현재 컨텍스트가 있는 티커 목록 반환 (디버깅용)."""
        return list(self._memory.keys())


# 싱글턴
context_manager = ContextManager()
