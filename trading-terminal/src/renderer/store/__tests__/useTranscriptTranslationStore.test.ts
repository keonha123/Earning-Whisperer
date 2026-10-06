import { describe, it, expect, beforeEach } from 'vitest'
import { useTranscriptTranslationStore } from '../useTranscriptTranslationStore'

/** 백엔드가 STOMP 로 보내는 snake_case payload (Contract 4.8). */
function makePayload(override: Record<string, unknown> = {}) {
  return {
    ticker: 'WMT',
    call_id: 'demo-wmt-1',
    sequences: [3, 4, 5],
    text_ko: 'Walmart U.S.의 기존점 매출은 2.6%였으며 거래 건수가 이를 견인했습니다.',
    terms_used: ['Comp sales', 'transactions'],
    ...override,
  }
}

function items(ticker = 'WMT') {
  return useTranscriptTranslationStore.getState().byTicker.get(ticker)?.items ?? []
}

describe('useTranscriptTranslationStore', () => {
  beforeEach(() => {
    useTranscriptTranslationStore.setState({ byTicker: new Map(), retiredCallIds: new Map() })
  })

  it('snake_case payload 를 camelCase 로 바꿔 저장한다', () => {
    useTranscriptTranslationStore.getState().upsertTranslation(makePayload())

    expect(items()).toEqual([
      {
        callId: 'demo-wmt-1',
        sequences: [3, 4, 5],
        textKo: 'Walmart U.S.의 기존점 매출은 2.6%였으며 거래 건수가 이를 견인했습니다.',
        termsUsed: ['Comp sales', 'transactions'],
      },
    ])
  })

  it('늦게 도착한 앞 문단도 첫 sequence 순으로 정렬한다', () => {
    const { upsertTranslation } = useTranscriptTranslationStore.getState()
    upsertTranslation(makePayload({ sequences: [3, 4, 5] }))
    upsertTranslation(makePayload({ sequences: [0, 1, 2], text_ko: '앞 문단' }))

    expect(items().map((i) => i.sequences[0])).toEqual([0, 3])
  })

  it('같은 sequences 가 다시 오면 무시한다 (재연결 중복)', () => {
    const { upsertTranslation } = useTranscriptTranslationStore.getState()
    upsertTranslation(makePayload())
    upsertTranslation(makePayload({ text_ko: '다른 번역' }))

    expect(items()).toHaveLength(1)
    expect(items()[0].textKo).toContain('기존점 매출')
  })

  it('다른 회차(call_id)가 오면 이전 회차 번역을 버린다', () => {
    const { upsertTranslation } = useTranscriptTranslationStore.getState()
    upsertTranslation(makePayload())
    upsertTranslation(makePayload({ call_id: 'demo-wmt-2', sequences: [0] }))

    expect(items().map((i) => i.callId)).toEqual(['demo-wmt-2'])
  })

  it('새 회차로 넘어간 뒤 늦게 도착한 이전 회차 번역은 버린다', () => {
    const { upsertTranslation } = useTranscriptTranslationStore.getState()
    upsertTranslation(makePayload({ call_id: 'demo-wmt-1', sequences: [0] }))
    upsertTranslation(makePayload({ call_id: 'demo-wmt-2', sequences: [0] }))
    upsertTranslation(makePayload({ call_id: 'demo-wmt-1', sequences: [3] }))

    expect(items().map((i) => [i.callId, i.sequences[0]])).toEqual([['demo-wmt-2', 0]])
  })

  it('비운 회차의 번역이 뒤늦게 와도 다시 살아나지 않는다', () => {
    const { upsertTranslation, clearTicker } = useTranscriptTranslationStore.getState()
    upsertTranslation(makePayload({ sequences: [0] }))
    clearTicker('WMT')
    useTranscriptTranslationStore.getState().upsertTranslation(makePayload({ sequences: [3] }))

    expect(items()).toEqual([])
    useTranscriptTranslationStore.getState().upsertTranslation(makePayload({ call_id: 'demo-wmt-2', sequences: [0] }))
    expect(items()).toHaveLength(1)
  })

  it('sequences 를 오름차순 · 중복 제거해 저장한다', () => {
    useTranscriptTranslationStore.getState().upsertTranslation(makePayload({ sequences: [5, 3, 3, 4] }))

    expect(items()[0].sequences).toEqual([3, 4, 5])
  })

  it.each([
    ['ticker 없음', { ticker: '' }],
    ['call_id 없음', { call_id: undefined }],
    ['번역문 없음', { text_ko: '   ' }],
    ['sequences 비어 있음', { sequences: [] }],
    ['sequences 에 음수', { sequences: [-1] }],
    ['sequences 에 소수', { sequences: [1.5] }],
  ])('형식이 틀리면 버린다: %s', (_label, override) => {
    useTranscriptTranslationStore.getState().upsertTranslation(makePayload(override))

    expect(useTranscriptTranslationStore.getState().byTicker.size).toBe(0)
  })

  it('객체가 아닌 값은 버린다', () => {
    useTranscriptTranslationStore.getState().upsertTranslation('oops')
    useTranscriptTranslationStore.getState().upsertTranslation(null)

    expect(useTranscriptTranslationStore.getState().byTicker.size).toBe(0)
  })

  it('terms_used 가 없거나 형식이 틀리면 빈 배열로 둔다', () => {
    const { upsertTranslation } = useTranscriptTranslationStore.getState()
    upsertTranslation(makePayload({ terms_used: undefined, sequences: [0] }))
    upsertTranslation(makePayload({ terms_used: ['ok', 3, ''], sequences: [1] }))

    expect(items().map((i) => i.termsUsed)).toEqual([[], ['ok']])
  })

  it('ticker 별로 따로 쌓고, clearTicker 는 해당 ticker 만 비운다', () => {
    const { upsertTranslation, clearTicker } = useTranscriptTranslationStore.getState()
    upsertTranslation(makePayload())
    upsertTranslation(makePayload({ ticker: 'TGT' }))
    clearTicker('WMT')

    expect(items('WMT')).toEqual([])
    expect(items('TGT')).toHaveLength(1)
  })
})
