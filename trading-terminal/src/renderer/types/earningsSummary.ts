/**
 * 어닝콜 종료 후 종합 판단 모델 (Backend Contract 4.7).
 *
 * 기존 `earningsEvaluation.ts` 의 6축 점수 모델을 대체한다. 그 모델은 목업에서
 * 나온 것이고 AI Engine 에는 그런 산출물이 없다 — 화면이 만들어낸 숫자를 엔진이
 * 낸 것처럼 보여주게 되므로 쓰지 않는다.
 *
 * 여기 있는 필드는 전부 엔진이 실제로 돌려주는 값이다.
 */

export type SignalDirection = 'BULLISH' | 'BEARISH' | 'NEUTRAL'

/** LLM 이 어닝콜 전문을 읽고 낸 판단. */
export interface EarningsJudgment {
  direction: SignalDirection
  /** 0~1. 방향의 강도. */
  magnitude: number | null
  /** 0~1. */
  confidence: number | null
  /** 예: EARNINGS_GUIDANCE_UPGRADE */
  catalystType: string | null
  /** 판단 근거. 엔진이 영문으로 생성한다. */
  rationale: string | null
  riskFlags: readonly string[]
  holdDays: number | null
  /** 실제로 판단에 쓰인 모델. 폴백 여부를 눈으로 확인하는 용도. */
  modelVersion: string | null
}

/**
 * 실행 가능성 게이트.
 *
 * `action` 은 판단 방향이 아니라 "이 판단대로 움직여도 되는가" 의 답이다.
 * 뉴스 근거가 없으면 BULLISH 판단에도 AVOID 가 정상적으로 붙는다.
 * 화면에서 판단과 같은 줄에 놓으면 모순으로 읽히므로 반드시 분리해 표시한다.
 */
export interface ExecutionGate {
  action: string | null
  gateResult: string | null
  /** A~E. */
  institutionalGrade: string | null
  institutionalGradeScore: number | null
  positionIntentKo: string | null
  noTradeSummaryKo: string | null
  riskFlagsKo: readonly string[]
  counterThesisKo: string | null
}

/** 애널리스트 질문을 얼마나 피했는지. */
export interface EvasionMetrics {
  /** 0~1. 높을수록 회피. 엔진이 점수를 못 냈으면 null — 나머지 정보는 그대로 쓴다. */
  evasionScore: number | null
  /** 0~1. 높을수록 정면으로 답함. */
  directness: number | null
  pivotDetected: boolean
  /** 질문에는 있었으나 답변에 없던 주제. */
  missingTopics: readonly string[]
  rationaleKo: string | null
}

/** 엔진의 4값. 모르는 값은 null 로 두고 화면에서 회색으로 그린다. */
export type ImpactDirection = 'positive' | 'negative' | 'mixed' | 'neutral'

export interface ImpactLink {
  ticker: string
  relationship: string | null
  direction: ImpactDirection | null
  impactScore: number | null
  confidence: number | null
  rationaleKo: string | null
}

/**
 * 손절/익절 계획.
 *
 * `available=false` 면 나머지는 전부 null 이다. 가격 정보가 없거나 방향성이 서지
 * 않았다는 뜻이므로 화면에서 0 으로 채우면 안 된다 — 없는 계획을 있는 것처럼 보이게 된다.
 */
export interface RiskPlan {
  /**
   * 계획 산출 여부. 엔진이 이 키를 아예 빼면 null 이다.
   * null 을 false 로 뭉개면 실제로 존재하는 손절가를 버리고 "가격 정보가 없다" 는
   * 사실이 아닌 문장을 띄우게 된다. 세 갈래로 구분해 다룬다.
   */
  available: boolean | null
  direction: string | null
  referencePrice: number | null
  stopLoss: number | null
  takeProfit1: number | null
  takeProfit2: number | null
  stopPct: number | null
  takeProfit1Pct: number | null
  takeProfit2Pct: number | null
  riskReward1: number | null
  timeStopDays: number | null
  invalidationText: string | null
  sizingNoteKo: string | null
}

export interface EarningsSummary {
  ticker: string
  callId: string | null
  generatedAt: string | null
  judgment: EarningsJudgment
  gate: ExecutionGate | null
  /**
   * 부가 정보(회피·파급·손절) 조회 성공 여부.
   *
   * 아래 네 필드는 한 덩어리다 — 같이 오거나 같이 없다. 그래서 값이 비었을 때
   * "엔진이 해당 없음이라고 답한 것" 과 "조회가 실패한 것" 이 똑같아 보인다.
   * 이 플래그가 둘을 가른다. 백엔드가 보내지 않았으면 null.
   */
  intelligenceAvailable: boolean | null
  evasion: EvasionMetrics | null
  impactChain: readonly ImpactLink[]
  riskPlan: RiskPlan | null
  /**
   * 엔진이 붙인 주의사항. "RAG evidence is empty" 같은 것이 온다.
   * 숨기면 검증되지 않은 판단이 검증된 것처럼 보인다 — 반드시 화면에 남긴다.
   */
  warnings: readonly string[]
}
