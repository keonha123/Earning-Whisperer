/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * 어닝콜 종료 후 종합 평가 데이터.
 * Oracle Q4 FY2026 어닝콜 전체 발언 기반 파트별 점수 + 최종 시그널.
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - STT 마지막 라인 도달 후 신호 피드 영역 대체 카드에 표시.
 * ========================================================================== */

export interface EvaluationScore {
  label: string
  score: number
}

export interface EarningsEvaluation {
  scores: readonly EvaluationScore[]
  totalScore: number
  signal: 'BUY' | 'HOLD' | 'SELL'
  buyScore: number
  sellScore: number
  strength: string
  rationale: string
}

export const earningsEvaluationDevMock: EarningsEvaluation = {
  scores: [
    { label: '성장성', score: 88 },
    { label: '수익성', score: 64 },
    { label: '리스크', score: 73 },
    { label: '미래 매출 가시성', score: 92 },
    { label: '발언 일관성', score: 81 },
    { label: '발화자 신뢰도', score: 85 },
  ],
  totalScore: 76,
  signal: 'HOLD',
  buyScore: 61,
  sellScore: 39,
  strength: '중립-긍정',
  rationale:
    'Oracle은 OCI와 AI 인프라 기반 성장성이 강하지만, 대규모 CapEx와 총마진 압박이 확인되어 즉각 매수보다 관망이 적절합니다.',
}
