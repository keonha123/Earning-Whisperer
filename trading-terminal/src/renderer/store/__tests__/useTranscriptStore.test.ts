import { describe, it, expect, beforeEach } from 'vitest'
import {
  useTranscriptStore,
  isValidTranscriptPayload,
  toCamelTranscript,
  type RawTranscriptSegmentPayload,
} from '../useTranscriptStore'

/**
 * useMarketIndicesStore.test.ts 패턴 차용:
 *  - beforeEach 에서 store reset.
 *  - factory 함수로 raw payload 생성 (snake_case).
 *  - 단조성/중복/ended/ticker 격리 케이스 커버.
 */
function makeRaw(
  override: Partial<RawTranscriptSegmentPayload> = {},
): RawTranscriptSegmentPayload {
  return {
    ticker: 'NVDA',
    call_id: 'NVDA-2025-Q3',
    sequence: 1,
    start_ms: 0,
    end_ms: 5000,
    text: 'Sample segment text.',
    speaker: 'CEO · Jensen Huang',
    timestamp: 1_700_000_000,
    ...override,
  }
}

beforeEach(() => {
  useTranscriptStore.getState().reset()
})

describe('useTranscriptStore', () => {
  describe('isValidTranscriptPayload', () => {
    it('필수 6필드 모두 정상이면 true', () => {
      expect(isValidTranscriptPayload(makeRaw())).toBe(true)
    })

    it('필수 필드 누락 시 false', () => {
      const p: any = makeRaw()
      delete p.text
      expect(isValidTranscriptPayload(p)).toBe(false)
    })

    it('sequence 가 number 가 아니면 false', () => {
      const p: any = makeRaw()
      p.sequence = '1'
      expect(isValidTranscriptPayload(p)).toBe(false)
    })

    it('sequence 가 NaN 이면 false', () => {
      const p: any = makeRaw()
      p.sequence = NaN
      expect(isValidTranscriptPayload(p)).toBe(false)
    })

    it('speaker 가 undefined 면 통과 (선택 필드)', () => {
      const p: any = makeRaw()
      delete p.speaker
      expect(isValidTranscriptPayload(p)).toBe(true)
    })

    it('is_session_end 가 boolean 이 아니면 false', () => {
      const p: any = makeRaw({ is_session_end: 'true' as any })
      expect(isValidTranscriptPayload(p)).toBe(false)
    })

    it('null/undefined/배열 모두 false', () => {
      expect(isValidTranscriptPayload(null)).toBe(false)
      expect(isValidTranscriptPayload(undefined)).toBe(false)
      expect(isValidTranscriptPayload([])).toBe(false)
    })
  })

  describe('toCamelTranscript', () => {
    it('snake_case → camelCase 1:1 매핑', () => {
      const seg = toCamelTranscript(
        makeRaw({
          call_id: 'NVDA-2025-Q3',
          start_ms: 1234,
          end_ms: 5678,
          is_session_end: true,
        }),
      )
      expect(seg.callId).toBe('NVDA-2025-Q3')
      expect(seg.startMs).toBe(1234)
      expect(seg.endMs).toBe(5678)
      expect(seg.isSessionEnd).toBe(true)
    })
  })

  describe('upsertSegment — append', () => {
    it('단일 segment 가 정상 append + currentTicker 셋팅 가능', () => {
      const store = useTranscriptStore.getState()
      store.setCurrentTicker('NVDA')
      store.upsertSegment(makeRaw({ sequence: 1, text: 'first' }))
      const s = useTranscriptStore.getState()
      const tickerState = s.byTicker.get('NVDA')!
      expect(tickerState.segments).toHaveLength(1)
      expect(tickerState.segments[0].text).toBe('first')
      expect(s.currentTicker).toBe('NVDA')
    })

    it('연속된 sequence 1→2→3 모두 append 되고 순서 유지', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(makeRaw({ sequence: 1, text: 'a' }))
      store.upsertSegment(makeRaw({ sequence: 2, text: 'b' }))
      store.upsertSegment(makeRaw({ sequence: 3, text: 'c' }))
      const tickerState = useTranscriptStore.getState().byTicker.get('NVDA')!
      expect(tickerState.segments.map((seg) => seg.text)).toEqual([
        'a',
        'b',
        'c',
      ])
      expect(tickerState.lastSequenceByCall.get('NVDA-2025-Q3')).toBe(3)
    })
  })

  describe('upsertSegment — dedup / 역행 드롭', () => {
    it('동일 (callId, sequence) 중복 push 는 무시한다', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(makeRaw({ sequence: 5, text: 'first-arrival' }))
      const before = useTranscriptStore.getState().byTicker.get('NVDA')!
      // 동일 sequence 재전송 — 드롭되어야 함.
      store.upsertSegment(makeRaw({ sequence: 5, text: 'duplicate' }))
      const after = useTranscriptStore.getState().byTicker.get('NVDA')!
      expect(after.segments).toHaveLength(1)
      expect(after.segments[0].text).toBe('first-arrival')
      // 변화 없음 — reference 동일성 검증.
      expect(after.segments).toBe(before.segments)
    })

    it('sequence 역행 (이미 본 sequence 보다 작은 값) 은 드롭', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(makeRaw({ sequence: 10, text: 'tenth' }))
      store.upsertSegment(makeRaw({ sequence: 7, text: 'seventh-late' }))
      const tickerState = useTranscriptStore.getState().byTicker.get('NVDA')!
      expect(tickerState.segments).toHaveLength(1)
      expect(tickerState.segments[0].text).toBe('tenth')
      expect(tickerState.lastSequenceByCall.get('NVDA-2025-Q3')).toBe(10)
    })

    it('서로 다른 callId 는 sequence 가 작아도 정상 append (call 간 격리)', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(
        makeRaw({ call_id: 'NVDA-2025-Q3', sequence: 10, text: 'q3-10' }),
      )
      // 새 callId 는 자체 sequence 카운터를 가진다.
      store.upsertSegment(
        makeRaw({ call_id: 'NVDA-2025-Q4', sequence: 1, text: 'q4-1' }),
      )
      const tickerState = useTranscriptStore.getState().byTicker.get('NVDA')!
      expect(tickerState.segments).toHaveLength(2)
      expect(tickerState.lastSequenceByCall.get('NVDA-2025-Q3')).toBe(10)
      expect(tickerState.lastSequenceByCall.get('NVDA-2025-Q4')).toBe(1)
    })
  })

  describe('upsertSegment — is_session_end 후 거부', () => {
    it('is_session_end=true 메시지 도착 후 동일 callId 의 추가 segment 는 드롭', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(makeRaw({ sequence: 1, text: 'opening' }))
      store.upsertSegment(
        makeRaw({ sequence: 2, text: 'closing', is_session_end: true }),
      )
      // 종료 후 (다음 sequence) 추가 — 거부되어야 함.
      store.upsertSegment(makeRaw({ sequence: 3, text: 'after-end' }))
      const tickerState = useTranscriptStore.getState().byTicker.get('NVDA')!
      expect(tickerState.segments).toHaveLength(2)
      expect(tickerState.endedCallIds.has('NVDA-2025-Q3')).toBe(true)
      expect(
        tickerState.segments.find((seg) => seg.text === 'after-end'),
      ).toBeUndefined()
    })

    it('이미 ended 인 callId 와 다른 callId 는 정상 append', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(
        makeRaw({
          call_id: 'NVDA-2025-Q3',
          sequence: 1,
          is_session_end: true,
        }),
      )
      // 새 어닝콜 — 별개 callId.
      store.upsertSegment(
        makeRaw({ call_id: 'NVDA-2026-Q1', sequence: 1, text: 'new-call' }),
      )
      const tickerState = useTranscriptStore.getState().byTicker.get('NVDA')!
      expect(tickerState.segments).toHaveLength(2)
      expect(tickerState.endedCallIds.has('NVDA-2025-Q3')).toBe(true)
      expect(tickerState.endedCallIds.has('NVDA-2026-Q1')).toBe(false)
    })
  })

  describe('upsertSegment — ticker 전환 격리', () => {
    it('서로 다른 ticker 는 독립 컨테이너에 저장된다', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(
        makeRaw({ ticker: 'NVDA', call_id: 'NVDA-Q3', sequence: 1 }),
      )
      store.upsertSegment(
        makeRaw({ ticker: 'AAPL', call_id: 'AAPL-Q3', sequence: 1 }),
      )
      const s = useTranscriptStore.getState()
      expect(s.byTicker.get('NVDA')!.segments).toHaveLength(1)
      expect(s.byTicker.get('AAPL')!.segments).toHaveLength(1)
      expect(s.byTicker.get('NVDA')!.segments[0].ticker).toBe('NVDA')
      expect(s.byTicker.get('AAPL')!.segments[0].ticker).toBe('AAPL')
    })

    it('한 ticker 의 ended 가 다른 ticker 에 영향을 주지 않는다', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(
        makeRaw({
          ticker: 'NVDA',
          call_id: 'NVDA-Q3',
          sequence: 1,
          is_session_end: true,
        }),
      )
      // AAPL 은 정상 append 가능해야 함.
      store.upsertSegment(
        makeRaw({ ticker: 'AAPL', call_id: 'AAPL-Q3', sequence: 1 }),
      )
      store.upsertSegment(
        makeRaw({ ticker: 'AAPL', call_id: 'AAPL-Q3', sequence: 2 }),
      )
      const s = useTranscriptStore.getState()
      expect(s.byTicker.get('NVDA')!.segments).toHaveLength(1)
      expect(s.byTicker.get('AAPL')!.segments).toHaveLength(2)
    })
  })

  describe('clearTicker / reset', () => {
    it('clearTicker 는 해당 ticker 만 제거하고 다른 ticker 는 유지한다', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(makeRaw({ ticker: 'NVDA' }))
      store.upsertSegment(makeRaw({ ticker: 'AAPL', call_id: 'AAPL-Q3' }))
      store.clearTicker('NVDA')
      const s = useTranscriptStore.getState()
      expect(s.byTicker.has('NVDA')).toBe(false)
      expect(s.byTicker.has('AAPL')).toBe(true)
    })

    it('clearTicker 호출 시 존재하지 않는 ticker 는 no-op (state reference 유지)', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(makeRaw({ ticker: 'NVDA' }))
      const before = useTranscriptStore.getState()
      store.clearTicker('UNKNOWN')
      const after = useTranscriptStore.getState()
      expect(after.byTicker).toBe(before.byTicker)
    })

    it('reset 은 모든 ticker 와 currentTicker 를 초기화한다', () => {
      const store = useTranscriptStore.getState()
      store.upsertSegment(makeRaw({ ticker: 'NVDA' }))
      store.setCurrentTicker('NVDA')
      store.reset()
      const s = useTranscriptStore.getState()
      expect(s.byTicker.size).toBe(0)
      expect(s.currentTicker).toBeNull()
    })
  })

  describe('upsertSegment — 형식 불일치 silent drop', () => {
    it('필수 필드 누락 페이로드는 state 변화 없이 드롭', () => {
      const store = useTranscriptStore.getState()
      const before = useTranscriptStore.getState()
      store.upsertSegment({ ticker: 'NVDA' } as any)
      const after = useTranscriptStore.getState()
      expect(after.byTicker).toBe(before.byTicker)
    })
  })
})
