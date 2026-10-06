from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: 핵심 문장 주제. 직전 콜 대조에서 같은 주제의 문장끼리 견주는 기준이다.
STATEMENT_TOPICS = (
    "guidance",  # 연간 · 분기 전망치, 가이던스 유지 · 상향 · 하향
    "revenue",  # 매출 · 기존점 매출 · 거래 건수 등 매출 지표
    "profit",  # 영업이익 · EPS · 순이익
    "margin",  # 이익률 · bp 변화
    "segment",  # 사업부 · 지역 · 채널별 실적 (이커머스, 해외, 멤버십 등)
    "cost",  # 비용 · 투자 집행 · 가격 투자
    "capital",  # 설비투자 · 자사주 매입 · 배당 · 현금흐름
    "risk",  # 악재 · 호재 요인, 관세 · 규제 · 거시 환경
    "strategy",  # 전략 · 신사업 · 경쟁에 관한 수치가 있는 주장
    "other",  # 위에 들지 않지만 비교할 가치가 있는 것
)


class KeyStatement(BaseModel):
    """직전 콜에서 원문 그대로 추출한 경영진 문장 1개.

    `text` 는 원문 발언의 부분 문자열이다. 추출 단계에서 원문에 실제로 있는지 검사하고,
    없으면 저장하지 않는다. 대조 결과의 "직전 발언" 은 이 값만 쓴다.
    """

    model_config = ConfigDict(extra="ignore")

    statement_id: str
    document_id: str
    ticker: str
    order: int = Field(ge=0, description="콜 안에서의 순서. 같은 발언 안에서는 등장 순서")
    turn_index: int = Field(ge=0)
    speaker: str | None = None
    section: str | None = None
    topic: str
    text: str = Field(min_length=1)
    published_at_epoch: int | None = None
    fiscal_quarter: str | None = None


__all__ = ["KeyStatement", "STATEMENT_TOPICS"]
