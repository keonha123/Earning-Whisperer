"""콜 세그먼트 키워드 검색(BM25).

에이전트의 search_call 도구가 쓴다. 콜 원문이 영어라 검색어도 영어로 받는다. 임베딩을 쓰지 않아 호출 비용과
지연이 없고, 한 콜 수백 문장 규모에서는 메모리 안 계산으로 충분하다.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from assistant.context import Evidence

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOPWORDS = frozenset(
    "a an and are as at be been but by for from has have in is it its of on or our that the this to was we were with"
    " you your".split())
_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS]


class SegmentIndex:
    def __init__(self, segments: list[Evidence]) -> None:
        self._segments = segments
        self._docs = [Counter(tokenize(item.text)) for item in segments]
        self._lengths = [sum(doc.values()) for doc in self._docs]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        frequency: Counter[str] = Counter()
        for doc in self._docs:
            frequency.update(doc.keys())
        total = len(self._docs)
        self._idf = {term: math.log(1 + (total - count + 0.5) / (count + 0.5)) for term, count in frequency.items()}

    def search(self, query: str, top_k: int) -> list[Evidence]:
        terms = [term for term in dict.fromkeys(tokenize(query)) if term in self._idf]
        if not terms or not self._average:
            return []
        scored = []
        for position, (doc, length) in enumerate(zip(self._docs, self._lengths)):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    norm = tf + _K1 * (1 - _B + _B * length / self._average)
                    score += self._idf[term] * tf * (_K1 + 1) / norm
            if score > 0:
                scored.append((-score, position))
        scored.sort()
        return [self._segments[position] for _, position in scored[:top_k]]
