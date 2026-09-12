import { describe, it, expect, beforeEach } from 'vitest'
import { useFactCheckStore } from '../useFactCheckStore'

/**
 * useTranscriptStore.test.ts 패턴 차용 — snake_case raw payload factory + 검증/중복/격리 케이스.
 *
 * 이 store 의 입력은 백엔드가 STOMP 로 보내는 값이므로, 형식이 어긋난 데이터가
 * 화면에 도달하지 않는지를 주로 본다.
 */
function makeClaim(override: Record<string, unknown> = {}) {
  return {
    claim_id: 'ORCL:0-2:c1',
    sentence_index: 0,
    source_text: '원문',
    claim: 'OCI 매출이 52% 성장했다',
    claim_type: 'numeric_fact',
    verdict: 'CONTRADICTED',
    confidence: 0.85,
    explanation_ko: '증거에 따르면 42% 입니다.',
    reason_code: 'contradicted_by_news',
    evidence: [
      {
        doc_id: 'd1',
        title: 'Oracle OCI revenue rises 42%',
        snippet: '발췌',
        url: 'https://example.com/d1',
        source: 'reuters',
      },
    ],
    retrieved_count: 2,
    accepted_count: 2,
    ...override,
  }
}

function makeBatch(override: Record<string, unknown> = {}) {
  return {
    ticker: 'ORCL',
    call_id: 'demo-orcl-1',
    batch_start_sequence: 0,
    batch_end_sequence: 2,
    claims: [makeClaim()],
    ...override,
  }
}

beforeEach(() => {
  useFactCheckStore.setState({ byTicker: new Map() })
})

const claimsOf = (ticker: string) =>
  useFactCheckStore.getState().byTicker.get(ticker)?.claims ?? []

describe('useFactCheckStore.upsertBatch', () => {
  it('snake_case 배치를 camelCase 로 변환해 누적한다', () => {
    useFactCheckStore.getState().upsertBatch(makeBatch())

    const [claim] = claimsOf('ORCL')
    expect(claim.claimId).toBe('ORCL:0-2:c1')
    expect(claim.verdict).toBe('CONTRADICTED')
    expect(claim.explanationKo).toBe('증거에 따르면 42% 입니다.')
    expect(claim.reasonCode).toBe('contradicted_by_news')
    expect(claim.batchStartSequence).toBe(0)
    expect(claim.batchEndSequence).toBe(2)
    expect(claim.evidence[0]).toEqual({
      docId: 'd1',
      title: 'Oracle OCI revenue rises 42%',
      snippet: '발췌',
      url: 'https://example.com/d1',
      source: 'reuters',
    })
  })

  it('같은 claimId 재도착은 무시한다', () => {
    // 재연결 시 같은 배치가 다시 밀려올 수 있다. 카드가 두 번 뜨면 안 된다.
    useFactCheckStore.getState().upsertBatch(makeBatch())
    useFactCheckStore.getState().upsertBatch(makeBatch())

    expect(claimsOf('ORCL')).toHaveLength(1)
  })

  it('배치를 도착 순서대로 누적한다', () => {
    useFactCheckStore.getState().upsertBatch(makeBatch())
    useFactCheckStore.getState().upsertBatch(
      makeBatch({
        batch_start_sequence: 3,
        batch_end_sequence: 5,
        claims: [makeClaim({ claim_id: 'ORCL:3-5:c1', verdict: 'SUPPORTED' })],
      }),
    )

    expect(claimsOf('ORCL').map((c) => c.claimId)).toEqual(['ORCL:0-2:c1', 'ORCL:3-5:c1'])
  })

  it('ticker 별로 격리된다', () => {
    useFactCheckStore.getState().upsertBatch(makeBatch())
    useFactCheckStore.getState().upsertBatch(
      makeBatch({ ticker: 'NVDA', claims: [makeClaim({ claim_id: 'NVDA:0-2:c1' })] }),
    )

    expect(claimsOf('ORCL')).toHaveLength(1)
    expect(claimsOf('NVDA')).toHaveLength(1)
  })

  it('알 수 없는 verdict 는 버린다', () => {
    // AI Engine 이 판정 종류를 늘리면 UI 에 매핑이 없어 빈 뱃지가 뜬다. 그 전에 막는다.
    useFactCheckStore.getState().upsertBatch(
      makeBatch({ claims: [makeClaim({ verdict: 'EXAGGERATED' })] }),
    )

    expect(claimsOf('ORCL')).toHaveLength(0)
  })

  it('한국어 설명이 없으면 버린다', () => {
    // 판정 뱃지만 덩그러니 뜨면 사용자가 이유를 알 수 없다.
    useFactCheckStore.getState().upsertBatch(
      makeBatch({ claims: [makeClaim({ explanation_ko: '' })] }),
    )

    expect(claimsOf('ORCL')).toHaveLength(0)
  })

  it('confidence 를 0~1 로 클램프하고 비수치는 0 으로 둔다', () => {
    useFactCheckStore.getState().upsertBatch(
      makeBatch({
        claims: [
          makeClaim({ claim_id: 'c-over', confidence: 1.8 }),
          makeClaim({ claim_id: 'c-nan', confidence: 'high' }),
        ],
      }),
    )

    const byId = new Map(claimsOf('ORCL').map((c) => [c.claimId, c.confidence]))
    expect(byId.get('c-over')).toBe(1)
    expect(byId.get('c-nan')).toBe(0)
  })

  it('형식이 깨진 근거는 걸러내되 판정 자체는 살린다', () => {
    useFactCheckStore.getState().upsertBatch(
      makeBatch({ claims: [makeClaim({ evidence: [{ title: 'doc_id 없음' }, null, 'string'] })] }),
    )

    expect(claimsOf('ORCL')).toHaveLength(1)
    expect(claimsOf('ORCL')[0].evidence).toEqual([])
  })

  it('빈 배치·비객체·ticker 누락은 무시한다', () => {
    const { upsertBatch } = useFactCheckStore.getState()
    upsertBatch(makeBatch({ claims: [] }))
    upsertBatch(makeBatch({ ticker: '' }))
    upsertBatch(null)
    upsertBatch('nope')

    expect(useFactCheckStore.getState().byTicker.size).toBe(0)
  })

  it('clearTicker 는 해당 ticker 만 비운다', () => {
    // 시연 재시작 시 이전 회차 판정이 남아 있으면 혼동된다.
    useFactCheckStore.getState().upsertBatch(makeBatch())
    useFactCheckStore.getState().upsertBatch(
      makeBatch({ ticker: 'NVDA', claims: [makeClaim({ claim_id: 'NVDA:0-2:c1' })] }),
    )

    useFactCheckStore.getState().clearTicker('ORCL')

    expect(claimsOf('ORCL')).toHaveLength(0)
    expect(claimsOf('NVDA')).toHaveLength(1)
  })

  it('비운 뒤 같은 claimId 가 다시 오면 표시된다', () => {
    // 중복 방지 집합도 함께 비워져야 재시작 시 판정이 다시 뜬다.
    useFactCheckStore.getState().upsertBatch(makeBatch())
    useFactCheckStore.getState().clearTicker('ORCL')
    useFactCheckStore.getState().upsertBatch(makeBatch())

    expect(claimsOf('ORCL')).toHaveLength(1)
  })
})
