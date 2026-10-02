/**
 * 어닝콜 종료 후 종합 평가 모델 (`EarningsEvaluationCard` / `FinalSignalCard`).
 *
 * 아직 백엔드 발행 경로가 없다 — 연결은 후속 작업이다.
 * 화면 예시는 `docs/demo/fixtures/earningsEvaluation.dev-mock.ts` 참조.
 */

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
