"""Versioned, curated earnings-call vocabulary shared by the API and prompts."""
from __future__ import annotations

try:
    from models.transcript_assistant_models import GlossaryResponse, GlossaryTerm
except ImportError:  # pragma: no cover
    from ..models.transcript_assistant_models import GlossaryResponse, GlossaryTerm


# Definitions deliberately describe accounting concepts, not trading recommendations.
_ROWS = [
    ("comparable sales", ["comp sales", "comps", "same-store sales"], "기존점 매출", "일정 기간 계속 영업한 기존 점포의 매출입니다.", "신규 점포 효과를 제외해 점포 자체의 성장 추이를 봅니다.", "comparison"),
    ("revenue", ["sales", "top line"], "매출", "제품과 서비스 판매로 발생한 수익입니다.", "매출 증가가 이익 증가와 같은 뜻은 아닙니다.", "income"),
    ("gross profit", [], "매출총이익", "매출에서 매출원가를 뺀 금액입니다.", "원가 부담을 파악할 때 사용합니다.", "income"),
    ("gross margin", [], "매출총이익률", "매출총이익을 매출로 나눈 비율입니다.", "가격과 원가 변화의 영향을 보여 줍니다.", "margin"),
    ("operating income", ["operating profit"], "영업이익", "주요 영업활동에서 발생한 이익입니다.", "이자와 세금의 영향을 구분하는 데 쓰입니다.", "income"),
    ("operating margin", [], "영업이익률", "영업이익을 매출로 나눈 비율입니다.", "매출 대비 영업 수익성을 보여 줍니다.", "margin"),
    ("net income", ["bottom line"], "순이익", "비용과 세금 등을 반영한 최종 이익입니다.", "일회성 항목 포함 여부를 함께 확인합니다.", "income"),
    ("EPS", ["earnings per share"], "주당순이익", "보통주 한 주에 귀속되는 이익입니다.", "희석 주식 수와 조정 기준에 따라 달라집니다.", "income"),
    ("diluted EPS", [], "희석주당순이익", "잠재적 주식 수 증가를 반영한 주당순이익입니다.", "기본 주당순이익과 구분해야 합니다.", "income"),
    ("GAAP", [], "미국 일반회계기준", "미국 재무보고에 사용하는 회계기준입니다.", "조정 실적과 비교하는 기준입니다.", "accounting"),
    ("non-GAAP", ["adjusted"], "조정 기준", "회사가 특정 항목을 제외하거나 조정한 기준입니다.", "제외 항목과 GAAP 조정표를 확인해야 합니다.", "accounting"),
    ("EBITDA", [], "이자·세금·감가상각 전 이익", "이자와 세금 및 감가상각 비용 차감 전 이익입니다.", "현금흐름과 동일한 지표는 아닙니다.", "income"),
    ("free cash flow", ["FCF"], "잉여현금흐름", "일반적으로 영업현금흐름에서 설비투자를 뺀 금액입니다.", "회사별 정의 차이를 확인해야 합니다.", "cash"),
    ("operating cash flow", [], "영업현금흐름", "영업활동에서 유입·유출된 현금의 순액입니다.", "회계상 이익과 실제 현금을 구분합니다.", "cash"),
    ("capital expenditures", ["capex"], "설비투자", "장기간 사용하는 자산을 취득하는 지출입니다.", "단기 현금 지출과 장기 성장에 영향을 줍니다.", "cash"),
    ("guidance", [], "실적 전망", "회사가 제시하는 향후 실적 예상치입니다.", "확정 실적과 구분해야 합니다.", "outlook"),
    ("outlook", [], "전망", "경영진의 향후 사업 예상입니다.", "예상 기간과 전제 조건이 중요합니다.", "outlook"),
    ("headwind", [], "부정적 요인", "사업 성과를 제약하는 요인입니다.", "실적에 불리한 방향임을 나타냅니다.", "outlook"),
    ("tailwind", [], "긍정적 요인", "사업 성과에 유리하게 작용하는 요인입니다.", "실적에 유리한 방향임을 나타냅니다.", "outlook"),
    ("year over year", ["year-over-year", "YoY"], "전년 동기 대비", "직전 연도의 같은 기간과 비교한 수치입니다.", "전분기 대비와 구분해야 합니다.", "comparison"),
    ("quarter over quarter", ["quarter-over-quarter", "QoQ"], "전분기 대비", "직전 분기와 비교한 수치입니다.", "계절성이 비교에 영향을 줄 수 있습니다.", "comparison"),
    ("sequential", [], "직전 기간 대비", "바로 앞 기간과 비교한다는 뜻입니다.", "비교 기간을 함께 확인합니다.", "comparison"),
    ("basis points", ["bps"], "베이시스포인트", "1 베이시스포인트는 0.01 퍼센트포인트입니다.", "퍼센트 변화율과 혼동하면 안 됩니다.", "comparison"),
    ("constant currency", [], "환율 고정 기준", "환율 변동 영향을 제외하여 비교하는 기준입니다.", "공시된 명목 성장률과 다를 수 있습니다.", "comparison"),
    ("organic growth", [], "유기적 성장", "인수합병 등 외부 요인을 제외한 성장입니다.", "회사별 제외 기준을 확인해야 합니다.", "comparison"),
    ("backlog", [], "수주잔고", "수주했으나 아직 이행하지 않은 계약 잔액입니다.", "전액이 즉시 매출로 인식되지는 않습니다.", "demand"),
    ("bookings", [], "수주액", "해당 기간 체결한 주문 또는 계약의 금액입니다.", "매출 인식 시점과 다를 수 있습니다.", "demand"),
    ("deferred revenue", [], "이연수익", "현금을 받았으나 아직 매출로 인식하지 않은 금액입니다.", "의무 이행 후 매출로 전환됩니다.", "accounting"),
    ("ARR", ["annual recurring revenue"], "연간 반복매출", "반복 계약 매출을 연간 기준으로 환산한 지표입니다.", "회계상 연간 매출과 다를 수 있습니다.", "demand"),
    ("churn", [], "이탈", "고객이나 반복 매출이 감소하는 현상입니다.", "고객 수 기준인지 매출 기준인지 확인합니다.", "demand"),
    ("net retention", ["NRR"], "순매출유지율", "기존 고객의 확대·축소·이탈을 반영한 매출 유지 비율입니다.", "신규 고객 매출과 구분합니다.", "demand"),
    ("inventory", [], "재고", "판매 또는 생산을 위해 보유한 자산입니다.", "재고 증가에는 수요와 공급 양쪽 원인이 있습니다.", "balance"),
    ("working capital", [], "운전자본", "통상 유동자산에서 유동부채를 뺀 금액입니다.", "현금 소요를 파악할 때 사용합니다.", "balance"),
    ("liquidity", [], "유동성", "단기 지급 의무를 충족할 수 있는 능력입니다.", "장기 수익성과 구분해야 합니다.", "balance"),
    ("leverage", [], "차입 활용도", "부채를 활용하는 정도입니다.", "지표의 분모와 부채 범위를 확인합니다.", "balance"),
    ("share repurchase", ["buyback"], "자사주 매입", "회사가 자기 주식을 사들이는 행위입니다.", "승인 한도와 실제 집행액을 구분합니다.", "capital"),
    ("dividend", [], "배당", "회사가 주주에게 분배하는 이익 또는 자산입니다.", "선언일과 지급일을 구분합니다.", "capital"),
    ("stock-based compensation", ["SBC"], "주식보상비용", "직원 등에게 주식 기반 보상을 제공하면서 인식하는 비용입니다.", "현금 지출과 희석 효과를 구분합니다.", "accounting"),
    ("impairment", [], "손상차손", "자산 장부가액의 회수 가능성이 낮아져 인식하는 손실입니다.", "현금 유출 시점과 다를 수 있습니다.", "accounting"),
    ("restructuring", [], "구조조정", "조직이나 사업 운영 구조를 변경하는 활동입니다.", "관련 비용과 예상 절감액을 구분합니다.", "accounting"),
    ("one-time charge", [], "일회성 비용", "회사가 비반복적이라고 설명하는 비용입니다.", "실제 반복 여부를 과거 공시와 비교합니다.", "accounting"),
]


def matching_terms(text: str) -> list[GlossaryTerm]:
    """Match the longest expression first so non-GAAP does not also mean GAAP."""
    import re

    candidates = []
    for term in get_glossary().terms:
        for alias in [term.term, *term.aliases, term.ko]:
            for match in re.finditer(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", text, re.I):
                candidates.append((match.start(), match.end(), term))
    occupied = []
    found = {}
    for start, end, term in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0])):
        if any(start < right and end > left for left, right in occupied):
            continue
        occupied.append((start, end))
        found.setdefault(term.term, term)
    return list(found.values())


def get_glossary() -> GlossaryResponse:
    return GlossaryResponse(version="2026-09-16.1", terms=[
        GlossaryTerm(term=t, aliases=a, ko=k, definition_ko=d, why_ko=w, category=c)
        for t, a, k, d, w, c in _ROWS
    ])
