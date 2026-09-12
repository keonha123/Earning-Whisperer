import { describe, it, expect, beforeEach } from 'vitest'
import { useEarningsSummaryStore } from '../useEarningsSummaryStore'

/**
 * useFactCheckStore.test.ts 패턴 차용.
 *
 * 이 store 의 입력은 백엔드가 STOMP 로 보내는 종합 판단(Contract 4.7)이다.
 * 여기서 주로 보는 것은 "엔진이 판단하지 못한 것을 화면이 판단한 것처럼 꾸미지 않는가" 다.
 */
function makePayload(override: Record<string, unknown> = {}) {
  return {
    ticker: 'ORCL',
    call_id: 'demo-orcl-1',
    generated_at: '2026-09-09T09:47:50Z',
    judgment: {
      direction: 'BULLISH',
      magnitude: 0.85,
      confidence: 0.74,
      catalyst_type: 'EARNINGS_GUIDANCE_UPGRADE',
      rationale: 'OCI growth accelerating',
      risk_flags: ['missing_rag_evidence'],
      hold_days: 1,
      model_version: 'gemini-3.6-flash',
    },
    gate: {
      action: 'AVOID',
      gate_result: 'soft_block',
      institutional_grade: 'D',
      institutional_grade_score: 48.06,
      position_intent_ko: '신규 진입 금지',
      no_trade_summary_ko: '근거 부족',
      risk_flags_ko: ['확인이 약합니다.'],
      counter_thesis_ko: null,
    },
    evasion: {
      evasion_score: 0.56,
      directness: 0.44,
      pivot_detected: false,
      missing_topics: ['capex', 'margin'],
      rationale_ko: '핵심 주제를 누락했습니다.',
    },
    impact_chain: [
      { ticker: 'NVDA', relationship: 'supplier', direction: 'positive', impact_score: 0.56, confidence: 0.45, rationale_ko: '근거' },
    ],
    intelligence_available: true,
    risk_plan: { available: true, direction: 'LONG', reference_price: 242.5, stop_loss: 233.8, take_profit_1: 254.0, risk_reward_1: 1.25 },
    warnings: ['RAG evidence is empty'],
    ...override,
  }
}

describe('useEarningsSummaryStore', () => {
  beforeEach(() => {
    useEarningsSummaryStore.setState({ byTicker: new Map() })
  })

  function get(ticker: string) {
    return useEarningsSummaryStore.getState().byTicker.get(ticker) ?? null
  }

  it('snake_case 페이로드를 camelCase 로 변환해 저장한다', () => {
    useEarningsSummaryStore.getState().setSummary(makePayload())

    const s = get('ORCL')!
    expect(s.judgment.direction).toBe('BULLISH')
    expect(s.judgment.catalystType).toBe('EARNINGS_GUIDANCE_UPGRADE')
    expect(s.gate?.institutionalGrade).toBe('D')
    expect(s.evasion?.missingTopics).toEqual(['capex', 'margin'])
    expect(s.impactChain[0].ticker).toBe('NVDA')
    expect(s.riskPlan?.stopLoss).toBe(233.8)
    expect(s.warnings).toEqual(['RAG evidence is empty'])
  })

  it('모르는 방향값은 통째로 버린다', () => {
    // NEUTRAL 로 대체하면 엔진이 판단하지 못한 것을 "중립 판단" 으로 위조하게 된다.
    useEarningsSummaryStore.getState().setSummary(
      makePayload({ judgment: { direction: 'MOON', confidence: 0.9 } }),
    )
    expect(get('ORCL')).toBeNull()
  })

  it('판단 본문이 없으면 저장하지 않는다', () => {
    useEarningsSummaryStore.getState().setSummary(makePayload({ judgment: null }))
    expect(get('ORCL')).toBeNull()
  })

  it('ticker 가 없으면 저장하지 않는다', () => {
    useEarningsSummaryStore.getState().setSummary(makePayload({ ticker: '' }))
    expect(useEarningsSummaryStore.getState().byTicker.size).toBe(0)
  })

  it('부가 정보가 없어도 판단은 저장한다', () => {
    // intelligence 호출이 실패한 경우. 판단까지 버리면 화면이 통째로 빈다.
    useEarningsSummaryStore.getState().setSummary(
      makePayload({ gate: null, evasion: null, impact_chain: null, risk_plan: null, warnings: null }),
    )
    const s = get('ORCL')!
    expect(s.judgment.direction).toBe('BULLISH')
    expect(s.gate).toBeNull()
    expect(s.evasion).toBeNull()
    expect(s.impactChain).toEqual([])
    expect(s.riskPlan).toBeNull()
    expect(s.warnings).toEqual([])
  })

  it('손절 계획이 산출되지 않으면 값을 0 으로 채우지 않는다', () => {
    useEarningsSummaryStore.getState().setSummary(
      makePayload({
        risk_plan: { available: false, stop_loss: null, take_profit_1: null, invalidation_text: '가격 부족' },
      }),
    )
    const plan = get('ORCL')!.riskPlan!
    expect(plan.available).toBe(false)
    expect(plan.stopLoss).toBeNull()
    expect(plan.invalidationText).toBe('가격 부족')
  })

  it('범위를 벗어난 비율은 0~1 로 자른다', () => {
    useEarningsSummaryStore.getState().setSummary(
      makePayload({ judgment: { direction: 'BEARISH', magnitude: 1.8, confidence: -0.3 } }),
    )
    const j = get('ORCL')!.judgment
    expect(j.magnitude).toBe(1)
    expect(j.confidence).toBe(0)
  })

  it('부가 정보 조회 실패와 해당 없음을 구분해 담는다', () => {
    const store = useEarningsSummaryStore.getState()
    store.setSummary(makePayload({ intelligence_available: false, evasion: null, risk_plan: null }))
    expect(get('ORCL')!.intelligenceAvailable).toBe(false)

    store.setSummary(makePayload({ intelligence_available: true }))
    expect(get('ORCL')!.intelligenceAvailable).toBe(true)

    // 백엔드가 아직 이 필드를 안 보내는 경우 — false 로 단정하면 안 된다.
    store.setSummary(makePayload({ intelligence_available: undefined }))
    expect(get('ORCL')!.intelligenceAvailable).toBeNull()
  })

  it('ticker 없는 파급 항목은 걸러 낸다', () => {
    useEarningsSummaryStore.getState().setSummary(
      makePayload({ impact_chain: [{ impact_score: 0.5 }, { ticker: 'MSFT', impact_score: 0.4 }] }),
    )
    expect(get('ORCL')!.impactChain.map((l) => l.ticker)).toEqual(['MSFT'])
  })

  it('같은 ticker 재수신은 누적이 아니라 치환이다', () => {
    const store = useEarningsSummaryStore.getState()
    store.setSummary(makePayload())
    store.setSummary(makePayload({ call_id: 'demo-orcl-2', judgment: { direction: 'BEARISH' } }))

    const s = get('ORCL')!
    expect(s.callId).toBe('demo-orcl-2')
    expect(s.judgment.direction).toBe('BEARISH')
    expect(useEarningsSummaryStore.getState().byTicker.size).toBe(1)
  })

  it('available 키가 없으면 false 로 단정하지 않는다', () => {
    // false 로 뭉개면 실제로 존재하는 손절가를 버리고 "가격 정보가 없다" 는
    // 사실이 아닌 문장을 띄우게 된다.
    useEarningsSummaryStore.getState().setSummary(
      makePayload({ risk_plan: { stop_loss: 233.8, take_profit_1: 254.0 } }),
    )
    const plan = get('ORCL')!.riskPlan!
    expect(plan.available).toBeNull()
    expect(plan.stopLoss).toBe(233.8)
  })

  it('게이트에 한국어 설명이 없어도 action 은 살린다', () => {
    // 설명이 비었다고 action 까지 버리면 강세 판단 옆에서 "실행 보류" 가 사라진다.
    useEarningsSummaryStore.getState().setSummary(
      makePayload({
        gate: { action: 'AVOID', gate_result: 'soft_block', position_intent_ko: null, risk_flags_ko: [] },
      }),
    )
    const gate = get('ORCL')!.gate!
    expect(gate.action).toBe('AVOID')
    expect(gate.gateResult).toBe('soft_block')
    expect(gate.riskFlagsKo).toEqual([])
  })

  it('회피 점수가 없어도 나머지 회피 정보는 살린다', () => {
    useEarningsSummaryStore.getState().setSummary(
      makePayload({
        evasion: { evasion_score: null, missing_topics: ['capex'], pivot_detected: true, rationale_ko: '사유' },
      }),
    )
    const e = get('ORCL')!.evasion!
    expect(e.evasionScore).toBeNull()
    expect(e.missingTopics).toEqual(['capex'])
    expect(e.pivotDetected).toBe(true)
  })

  it('회피 정보가 통째로 비면 버린다', () => {
    useEarningsSummaryStore.getState().setSummary(
      makePayload({ evasion: { evasion_score: null, missing_topics: [], pivot_detected: false } }),
    )
    expect(get('ORCL')!.evasion).toBeNull()
  })

  it('모르는 파급 방향은 null 로 둔다', () => {
    // 'mixed'/'neutral'/미상을 positive 와 같이 칠하면 없는 호재 판단이 생긴다.
    useEarningsSummaryStore.getState().setSummary(
      makePayload({
        impact_chain: [
          { ticker: 'NVDA', direction: 'mixed', impact_score: 0.5 },
          { ticker: 'MSFT', direction: 'sideways', impact_score: 0.4 },
          { ticker: 'AMZN', impact_score: 0.3 },
        ],
      }),
    )
    expect(get('ORCL')!.impactChain.map((l) => l.direction)).toEqual(['mixed', null, null])
  })

  it('중복 문자열과 중복 종목을 걸러 React key 충돌을 막는다', () => {
    useEarningsSummaryStore.getState().setSummary(
      makePayload({
        warnings: ['같은 경고', '같은 경고'],
        impact_chain: [
          { ticker: 'NVDA', impact_score: 0.5 },
          { ticker: 'NVDA', impact_score: 0.4 },
        ],
      }),
    )
    const s = get('ORCL')!
    expect(s.warnings).toEqual(['같은 경고'])
    expect(s.impactChain).toHaveLength(1)
  })

  it('clearTicker 가 해당 종목만 비운다', () => {
    const store = useEarningsSummaryStore.getState()
    store.setSummary(makePayload())
    store.setSummary(makePayload({ ticker: 'NVDA' }))

    store.clearTicker('ORCL')

    expect(get('ORCL')).toBeNull()
    expect(get('NVDA')).not.toBeNull()
  })
})
