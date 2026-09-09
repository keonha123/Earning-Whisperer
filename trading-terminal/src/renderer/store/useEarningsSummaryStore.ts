import { create } from 'zustand'
import type {
  EarningsJudgment,
  ImpactDirection,
  EarningsSummary,
  EvasionMetrics,
  ExecutionGate,
  ImpactLink,
  RiskPlan,
  SignalDirection,
} from '../types/earningsSummary'

/**
 * 어닝콜 종료 후 종합 판단 클라이언트 상태.
 *
 * Backend Contract 4.7 (STOMP /topic/evaluation/{ticker} push) 와 1:1 매핑.
 * useFactCheckStore 와 동일한 패턴 — snake_case payload 를 store 경계에서 camelCase 로
 * 변환하고 검증한다. 형식이 어긋나면 silent drop.
 *
 * 팩트체크와 달리 <b>회차당 1건</b>만 온다. 그래서 누적이 아니라 치환이다.
 */

interface EarningsSummaryState {
  byTicker: Map<string, EarningsSummary>

  /** snake_case payload 1건을 검증 후 저장. 형식 불일치 시 silent drop. */
  setSummary: (raw: unknown) => void

  /** 해당 ticker 의 종합 판단을 비운다. 재생을 다시 시작할 때 호출. */
  clearTicker: (ticker: string) => void
}

const VALID_DIRECTIONS: ReadonlySet<string> = new Set(['BULLISH', 'BEARISH', 'NEUTRAL'])

/** 파급 영향의 방향. 4값 중 하나가 아니면 null — 모르는 값을 호재로 칠하지 않는다. */
const VALID_IMPACT_DIRECTIONS: ReadonlySet<string> = new Set([
  'positive', 'negative', 'mixed', 'neutral',
])

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() !== '' ? v : null
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** 0~1 범위로 자른다. 엔진이 범위를 벗어난 값을 주면 게이지가 넘친다. */
function ratio(v: unknown): number | null {
  const n = num(v)
  if (n === null) return null
  return Math.min(1, Math.max(0, n))
}

/**
 * 문자열 목록 정규화.
 *
 * 중복을 제거하는 이유는 화면이 이 값을 그대로 React key 로 쓰기 때문이다.
 * 엔진이 같은 리스크 문구를 두 번 보내면 key 가 충돌한다.
 */
function strList(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  const seen = new Set<string>()
  for (const item of v) {
    if (typeof item === 'string' && item.trim() !== '') seen.add(item)
  }
  return [...seen]
}

/** boolean 이 아니면 null. 키 부재를 false 로 단정하지 않는다. */
function bool(v: unknown): boolean | null {
  return typeof v === 'boolean' ? v : null
}

function toJudgment(raw: unknown): EarningsJudgment | null {
  if (!isRecord(raw)) return null
  const direction = raw.direction
  // 방향이 없거나 모르는 값이면 화면에 그릴 수 없다. 임의로 NEUTRAL 로 채우면
  // 엔진이 판단하지 못한 것을 "중립 판단" 으로 위조하는 셈이 된다.
  if (typeof direction !== 'string' || !VALID_DIRECTIONS.has(direction)) return null
  return {
    direction: direction as SignalDirection,
    magnitude: ratio(raw.magnitude),
    confidence: ratio(raw.confidence),
    catalystType: str(raw.catalyst_type),
    rationale: str(raw.rationale),
    riskFlags: strList(raw.risk_flags),
    holdDays: num(raw.hold_days),
    modelVersion: str(raw.model_version),
  }
}

function toGate(raw: unknown): ExecutionGate | null {
  if (!isRecord(raw)) return null
  return {
    action: str(raw.action),
    gateResult: str(raw.gate_result),
    institutionalGrade: str(raw.institutional_grade),
    institutionalGradeScore: num(raw.institutional_grade_score),
    positionIntentKo: str(raw.position_intent_ko),
    noTradeSummaryKo: str(raw.no_trade_summary_ko),
    riskFlagsKo: strList(raw.risk_flags_ko),
    counterThesisKo: str(raw.counter_thesis_ko),
  }
}

function toEvasion(raw: unknown): EvasionMetrics | null {
  if (!isRecord(raw)) return null
  const evasionScore = ratio(raw.evasion_score)
  const missingTopics = strList(raw.missing_topics)
  const pivotDetected = raw.pivot_detected === true
  const rationaleKo = str(raw.rationale_ko)
  // 점수가 없어도 "답변에서 빠진 주제" 는 그 자체로 보여줄 값이 있다.
  // 전부 비었을 때만 버린다.
  if (evasionScore === null && missingTopics.length === 0 && !pivotDetected && rationaleKo === null) {
    return null
  }
  return {
    evasionScore,
    directness: ratio(raw.directness),
    pivotDetected,
    missingTopics,
    rationaleKo,
  }
}

function toImpactChain(raw: unknown): ImpactLink[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  return raw.flatMap((item) => {
    if (!isRecord(item)) return []
    const ticker = str(item.ticker)
    // 같은 종목이 두 번 오면 화면의 React key 가 충돌한다.
    if (ticker === null || seen.has(ticker)) return []
    seen.add(ticker)
    const direction = str(item.direction)
    return [{
      ticker,
      relationship: str(item.relationship),
      direction:
        direction !== null && VALID_IMPACT_DIRECTIONS.has(direction)
          ? (direction as ImpactDirection)
          : null,
      impactScore: ratio(item.impact_score),
      confidence: ratio(item.confidence),
      rationaleKo: str(item.rationale_ko),
    }]
  })
}

function toRiskPlan(raw: unknown): RiskPlan | null {
  if (!isRecord(raw)) return null
  return {
    available: bool(raw.available),
    direction: str(raw.direction),
    // available 이 참이 아니면 엔진이 나머지를 null 로 준다. num() 이 null 을
    // 돌려주므로 0 으로 둔갑하지 않는다.
    referencePrice: num(raw.reference_price),
    stopLoss: num(raw.stop_loss),
    takeProfit1: num(raw.take_profit_1),
    takeProfit2: num(raw.take_profit_2),
    stopPct: num(raw.stop_pct),
    takeProfit1Pct: num(raw.take_profit_1_pct),
    takeProfit2Pct: num(raw.take_profit_2_pct),
    riskReward1: num(raw.risk_reward_1),
    timeStopDays: num(raw.time_stop_days),
    invalidationText: str(raw.invalidation_text),
    sizingNoteKo: str(raw.sizing_note_ko),
  }
}

export const useEarningsSummaryStore = create<EarningsSummaryState>((set) => ({
  byTicker: new Map(),

  setSummary: (raw) => {
    if (!isRecord(raw)) return
    const ticker = str(raw.ticker)
    if (ticker === null) return
    const judgment = toJudgment(raw.judgment)
    // 판단 본문이 없으면 저장하지 않는다. 백엔드도 같은 조건에서 발행하지 않으므로
    // 여기 걸리는 것은 계약 위반이다.
    if (judgment === null) return

    const summary: EarningsSummary = {
      ticker,
      callId: str(raw.call_id),
      generatedAt: str(raw.generated_at),
      judgment,
      gate: toGate(raw.gate),
      intelligenceAvailable: bool(raw.intelligence_available),
      evasion: toEvasion(raw.evasion),
      impactChain: toImpactChain(raw.impact_chain),
      riskPlan: toRiskPlan(raw.risk_plan),
      warnings: strList(raw.warnings),
    }

    set((state) => {
      // 새 Map 을 만들어야 zustand 가 변경을 알아챈다.
      const next = new Map(state.byTicker)
      next.set(ticker, summary)
      return { byTicker: next }
    })
  },

  clearTicker: (ticker) =>
    set((state) => {
      if (!state.byTicker.has(ticker)) return state
      const next = new Map(state.byTicker)
      next.delete(ticker)
      return { byTicker: next }
    }),
}))
