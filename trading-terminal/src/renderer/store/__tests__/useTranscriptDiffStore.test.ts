import { describe, it, expect, beforeEach } from 'vitest'
import { useTranscriptDiffStore } from '../useTranscriptDiffStore'

/**
 * useFactCheckStore.test.ts 패턴 차용 — snake_case raw payload factory + 검증/중복/격리 케이스.
 *
 * 이 store 의 입력은 백엔드가 STOMP 로 보내는 값이므로, 형식이 어긋난 데이터가
 * 화면에 도달하지 않는지를 주로 본다.
 */
function makeEvidence(override: Record<string, unknown> = {}) {
  return {
    document_id: 'factset:WMT:wmt-fy27q1-2026-05-21',
    source: 'factset',
    title: 'Walmart, Inc. (WMT) Q1 FY2027 Earnings Call',
    published_at: '2026-05-21',
    source_url: null,
    snippet: 'We are reiterating our full year guidance of constant currency sales growth between 3.5% and 4.5%.',
    relevance_score: 0.72,
    confidence_score: 0.68,
    ...override,
  }
}

function makeItem(override: Record<string, unknown> = {}) {
  return {
    topic: 'guidance',
    change_type: 'improved',
    summary_ko: '직전 콜에서는 연간 가이던스를 유지한다고 했으나 이번에는 상향했습니다.',
    current_claim: "We're raising our fiscal year sales guidance to 4% to 5%.",
    prior_claim: 'We are reiterating our full year guidance of 3.5% and 4.5%.',
    confidence: 0.82,
    risk_score: 0.25,
    evidence: [makeEvidence()],
    ...override,
  }
}

function makePayload(override: Record<string, unknown> = {}) {
  return {
    ticker: 'WMT',
    call_id: 'demo-wmt-1',
    sequence: 22,
    previous_document: {
      document_id: 'factset:WMT:wmt-fy27q1-2026-05-21',
      title: 'Walmart, Inc. (WMT) Q1 FY2027 Earnings Call',
      published_at: '2026-05-21',
      fiscal_quarter: 'FY2027Q1',
      source_url: null,
    },
    items: [makeItem()],
    ...override,
  }
}

function itemsOf(ticker: string) {
  return useTranscriptDiffStore.getState().byTicker.get(ticker)?.items ?? []
}

describe('useTranscriptDiffStore', () => {
  beforeEach(() => {
    useTranscriptDiffStore.setState({ byTicker: new Map() })
  })

  it('정상 payload 를 camelCase 로 변환해 누적한다', () => {
    useTranscriptDiffStore.getState().upsertDiff(makePayload())

    const items = itemsOf('WMT')
    expect(items).toHaveLength(1)
    expect(items[0].changeType).toBe('improved')
    expect(items[0].topic).toBe('guidance')
    expect(items[0].summaryKo).toContain('상향')
    expect(items[0].priorClaim).toContain('3.5%')
    expect(items[0].sequence).toBe(22)
    expect(items[0].evidence[0].relevanceScore).toBe(0.72)
  })

  it('비교 대상 직전 콜을 함께 보관한다', () => {
    useTranscriptDiffStore.getState().upsertDiff(makePayload())

    const previous = useTranscriptDiffStore.getState().byTicker.get('WMT')?.previousCall
    expect(previous?.fiscalQuarter).toBe('FY2027Q1')
    expect(previous?.publishedAt).toBe('2026-05-21')
  })

  it('같은 sequence 의 payload 가 다시 와도 중복 누적하지 않는다', () => {
    // 재연결 시 같은 메시지가 다시 push 될 수 있다.
    useTranscriptDiffStore.getState().upsertDiff(makePayload())
    useTranscriptDiffStore.getState().upsertDiff(makePayload())

    expect(itemsOf('WMT')).toHaveLength(1)
  })

  it('알 수 없는 change_type 은 버린다', () => {
    useTranscriptDiffStore.getState().upsertDiff(
      makePayload({ items: [makeItem({ change_type: 'wildly_different' })] }),
    )

    expect(itemsOf('WMT')).toHaveLength(0)
  })

  it('설명이 없으면 버린다', () => {
    // 유형만 덩그러니 띄우면 사용자가 무엇이 달라졌는지 알 수 없다.
    useTranscriptDiffStore.getState().upsertDiff(
      makePayload({ items: [makeItem({ summary_ko: '' })] }),
    )

    expect(itemsOf('WMT')).toHaveLength(0)
  })

  it('발췌 없는 근거는 버리되 항목 자체는 살린다', () => {
    useTranscriptDiffStore.getState().upsertDiff(
      makePayload({ items: [makeItem({ evidence: [makeEvidence({ snippet: '' })] })] }),
    )

    const items = itemsOf('WMT')
    expect(items).toHaveLength(1)
    expect(items[0].evidence).toHaveLength(0)
  })

  it('items 가 비면 아무것도 하지 않는다', () => {
    // 백엔드가 거르지만 방어한다.
    useTranscriptDiffStore.getState().upsertDiff(makePayload({ items: [] }))

    expect(itemsOf('WMT')).toHaveLength(0)
  })

  it('ticker 가 없으면 버린다', () => {
    useTranscriptDiffStore.getState().upsertDiff(makePayload({ ticker: '' }))

    expect(useTranscriptDiffStore.getState().byTicker.size).toBe(0)
  })

  it('confidence 와 risk_score 를 0~1 로 가둔다', () => {
    useTranscriptDiffStore.getState().upsertDiff(
      makePayload({ items: [makeItem({ confidence: 1.7, risk_score: -0.5 })] }),
    )

    const items = itemsOf('WMT')
    expect(items[0].confidence).toBe(1)
    expect(items[0].riskScore).toBe(0)
  })

  it('ticker 별로 격리된다', () => {
    useTranscriptDiffStore.getState().upsertDiff(makePayload())
    useTranscriptDiffStore.getState().upsertDiff(makePayload({ ticker: 'ORCL' }))

    expect(itemsOf('WMT')).toHaveLength(1)
    expect(itemsOf('ORCL')).toHaveLength(1)
  })

  it('clearTicker 는 해당 ticker 만 비운다', () => {
    useTranscriptDiffStore.getState().upsertDiff(makePayload())
    useTranscriptDiffStore.getState().upsertDiff(makePayload({ ticker: 'ORCL' }))

    useTranscriptDiffStore.getState().clearTicker('WMT')

    expect(itemsOf('WMT')).toHaveLength(0)
    expect(itemsOf('ORCL')).toHaveLength(1)
  })
})
