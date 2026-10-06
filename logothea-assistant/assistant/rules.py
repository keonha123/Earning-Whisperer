"""생성 전 1차 거절 규칙.

명시적인 매매 판단 요청만 잡는다. "목표주가", "매수 의견" 같은 넓은 표현은 사실로 답할 수 있는 질문이 섞여 있어
LLM 분류에 맡긴다. 규칙이 넓으면 답해야 할 질문까지 거절한다.
"""

from __future__ import annotations

import re

_EXPLICIT_TRADE = re.compile(
    r"사야\s*(돼|되|할까|하나|하냐|할지)"
    r"|살까|팔까"
    r"|팔아야\s*(돼|되|할까|하나|할지)"
    r"|(매수|매도)\s*(할까|하는\s*게|할지)"
    r"|들어가도\s*(돼|되|될까)"
    r"|손절\s*(할까|해야)"
    r"|물타기\s*(할까|해야|해도)"
    r"|should\s+i\s+(buy|sell)\b(?![-\s]*(back|side))"
    r"|is\s+it\s+a\s+(buy|sell)\b(?![-\s]*(back|side))",
    re.IGNORECASE,
)


def is_explicit_trade_request(question: str) -> bool:
    return _EXPLICIT_TRADE.search(question) is not None
