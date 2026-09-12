/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * FactCheckPanel 이 표시하는 어닝콜 실시간 팩트체크 더미 데이터.
 * Oracle Q4 FY2026 어닝콜 STT 스크립트(sttTranscript.dev-mock) 와 매핑.
 *
 * triggerStep: STT 스크립트의 몇 번째 라인이 노출된 후 이 항목이 트리거되는지.
 *   - 0-index 기준. sttStep >= triggerStep 일 때 카드 노출.
 *   - STT 2라인 간격으로 배치 → 스크립트 흐름과 자연스럽게 연동.
 * ========================================================================== */

export interface FactCheckItem {
  id: string
  triggerStep: number
  /** 경영진이 발언한 핵심 주장. */
  claim: string
  verdict: 'CONFIRMED' | 'EXAGGERATED' | 'SHIFTED' | 'UNVERIFIED'
  /** 과거 어닝콜에서 동일 주제로 발언한 내용. */
  pastReference: string
  /** 현재 발언과 과거 발언의 차이·시사점. */
  delta: string
  /** AI 교차검증 신뢰도 (0–1). */
  confidence: number
}

// 영상2용 — Oracle Q4 FY2026 어닝콜 후반 발언 기반 팩트체크
export const factCheckDevMock: readonly FactCheckItem[] = [
  {
    id: 'fc-007',
    triggerStep: 1,
    claim: 'FY2027 매출 34% 성장 전망 (고정환율 기준)',
    verdict: 'CONFIRMED',
    pastReference: 'Q3 FY26: "FY2027 성장률은 장기 목표 범위 내로 제시"',
    delta: '실제 가이던스가 장기 목표를 초과 — 강한 자신감이 수치로 확인됨',
    confidence: 0.93,
  },
  {
    id: 'fc-008',
    triggerStep: 3,
    claim: 'Q1 클라우드 매출 58~64% 성장, EPS $1.72~$1.76',
    verdict: 'CONFIRMED',
    pastReference: 'Q3 FY26: "클라우드 성장 가속 지속 전망"',
    delta: '구체적 수치 공식 제시 — 이전보다 상향된 성장 전망으로 기대치 상승',
    confidence: 0.91,
  },
  {
    id: 'fc-009',
    triggerStep: 5,
    claim: 'FY2027 순현금 CapEx 약 700억 달러',
    verdict: 'CONFIRMED',
    pastReference: 'Q3 FY26: "AI 인프라 투자 확대 예고, 규모 미공개"',
    delta: '700억 달러 공식화 — 시장 예상을 상회하는 대규모 투자 확정, 마진 압박 리스크',
    confidence: 0.96,
  },
  {
    id: 'fc-010',
    triggerStep: 7,
    claim: '인프라 프로젝트 ROIC 20%대 후반 (안정화 이후)',
    verdict: 'CONFIRMED',
    pastReference: 'Q3 FY26: "대규모 투자에도 수익률 방어 자신" 언급',
    delta: '20%대 후반 구체적 수치 제시 — BYOH·선지급 구조에서 추가 개선 가능',
    confidence: 0.82,
  },
  {
    id: 'fc-011',
    triggerStep: 9,
    claim: '클라우드 DB 매출 29% 성장, 멀티클라우드 더 빠른 성장',
    verdict: 'CONFIRMED',
    pastReference: 'Q3 FY26: "클라우드 DB, 멀티클라우드 수요 확대 기대"',
    delta: '기대 부합 — 멀티클라우드는 초기 단계로 향후 추가 성장 여력 확인',
    confidence: 0.89,
  },
  {
    id: 'fc-012',
    triggerStep: 11,
    claim: '선지급·BYOH 구조의 마진은 기존 계약과 동일하거나 개선',
    verdict: 'SHIFTED',
    pastReference: 'Q3 FY26: "BYOH 구조, 마진 영향 최소화 노력 중"',
    delta: 'CFO가 반복 강조하나 데이터센터 가동 전까지 총마진 압박 지속 — 단기 괴리',
    confidence: 0.68,
  },
] as const
