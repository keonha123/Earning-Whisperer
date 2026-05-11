import { create } from 'zustand'

/**
 * 실시간 어닝콜 트랜스크립트 클라이언트 상태.
 *
 * Backend Contract 4.5 (STOMP /topic/transcript/{ticker} push) 와 1:1 매핑.
 * snake_case payload 는 store 의 upsertSegment 에서 camelCase 로 변환되어 저장된다
 * (useMarketIndicesStore 와 동일한 hook/store 변환 패턴).
 *
 * 단조성/중복/세션 종료 정책:
 *  - 동일 (callId, sequence) 중복 → 무시 (idempotency).
 *  - 동일 callId 내 sequence 가 마지막 sequence 보다 작거나 같음 → 역행/중복 드롭.
 *    (백엔드는 sequence 단조 증가를 보장하므로 역행은 비정상 — 안전 가드.)
 *  - is_session_end=true 메시지 도착 후 동일 callId 의 추가 segment → 드롭.
 *  - 새 callId 가 도착하면 이전 callId 의 segments 는 그대로 보존
 *    (앙코르콜/Q&A 분리 등 케이스 대비). 다만 endedCallIds 는 callId 단위.
 *  - ticker 별 독립 컨테이너 — ticker A 의 push 가 ticker B 의 segments 를 오염시키지 않는다.
 */

export interface TranscriptSegment {
  /** 어닝콜 종목 (예: "NVDA"). */
  ticker: string
  /** 어닝콜 세션 식별자 (예: "NVDA-2025-Q3"). */
  callId: string
  /** 동일 callId 내 단조 증가하는 정수 시퀀스. */
  sequence: number
  /** 어닝콜 시작 기준 segment 시작 ms. */
  startMs: number
  /** 어닝콜 시작 기준 segment 종료 ms. */
  endMs: number
  /** STT 인식 결과 본문 (plain string — XSS 방지 위해 innerHTML 미사용). */
  text: string
  /** 화자 라벨 (선택). */
  speaker?: string
  /** Unix Epoch Second UTC — 백엔드에서 push 한 시각. */
  timestamp: number
  /** 어닝콜 세션 종료 마커 (선택). true 시 동일 callId 추가 거부. */
  isSessionEnd?: boolean
}

/** 백엔드 raw payload (snake_case) — STOMP 메시지 그대로. */
export interface RawTranscriptSegmentPayload {
  ticker: string
  call_id: string
  sequence: number
  start_ms: number
  end_ms: number
  text: string
  speaker?: string
  timestamp: number
  is_session_end?: boolean
}

interface TickerState {
  /** sequence 오름차순 정렬을 유지하는 segment 배열. */
  segments: TranscriptSegment[]
  /** is_session_end=true 를 받은 callId 집합 — 추가 segment 거부 게이트. */
  endedCallIds: Set<string>
  /** 마지막으로 정상 반영된 (callId, sequence) — 단조성 검증용. */
  lastSequenceByCall: Map<string, number>
}

interface TranscriptState {
  /** ticker 별 독립 컨테이너. */
  byTicker: Map<string, TickerState>
  /**
   * 현재 사용자가 보고 있는 ticker (UI selector 용).
   * 한 번에 하나의 어닝콜만 화면에 표시되는 UX 가정.
   */
  currentTicker: string | null

  /** UI 가 어떤 ticker 를 보고 있는지 store 에 알려준다 (selector 단순화). */
  setCurrentTicker: (ticker: string | null) => void

  /**
   * snake_case payload 1건을 받아 변환 + 단조성/중복/ended 검증 후 append.
   * 6필드 필수 + speaker/is_session_end 옵션. 형식 불일치 시 silent drop.
   */
  upsertSegment: (raw: unknown) => void

  /** 특정 ticker 의 segments + endedCallIds 만 초기화 (다른 ticker 격리 유지). */
  clearTicker: (ticker: string) => void

  /** 전체 초기화 — 로그아웃/연결 해제 시. */
  reset: () => void
}

/**
 * snake_case payload 6필드 + 타입 가드.
 * 누락/타입불일치 시 false (useMarketIndices.isValidPayload 와 동일 패턴).
 */
export function isValidTranscriptPayload(
  p: unknown,
): p is RawTranscriptSegmentPayload {
  if (!p || typeof p !== 'object') return false
  const o = p as Record<string, unknown>
  return (
    typeof o.ticker === 'string' &&
    typeof o.call_id === 'string' &&
    typeof o.sequence === 'number' &&
    Number.isFinite(o.sequence) &&
    typeof o.start_ms === 'number' &&
    typeof o.end_ms === 'number' &&
    typeof o.text === 'string' &&
    typeof o.timestamp === 'number' &&
    (o.speaker === undefined || typeof o.speaker === 'string') &&
    (o.is_session_end === undefined || typeof o.is_session_end === 'boolean')
  )
}

/** snake_case → camelCase 단순 매핑. 외부 단위 테스트를 위해 export. */
export function toCamelTranscript(
  p: RawTranscriptSegmentPayload,
): TranscriptSegment {
  return {
    ticker: p.ticker,
    callId: p.call_id,
    sequence: p.sequence,
    startMs: p.start_ms,
    endMs: p.end_ms,
    text: p.text,
    speaker: p.speaker,
    timestamp: p.timestamp,
    isSessionEnd: p.is_session_end,
  }
}

function emptyTickerState(): TickerState {
  return {
    segments: [],
    endedCallIds: new Set<string>(),
    lastSequenceByCall: new Map<string, number>(),
  }
}

export const useTranscriptStore = create<TranscriptState>((set) => ({
  byTicker: new Map(),
  currentTicker: null,

  setCurrentTicker: (ticker) => set({ currentTicker: ticker }),

  upsertSegment: (raw) =>
    set((state) => {
      if (!isValidTranscriptPayload(raw)) {
        // 형식 불일치 — silent drop (warn 은 hook 계층에서 처리하지 않고 store 가
        // 받은 시점이면 이미 검증을 통과했어야 한다. 안전 가드로만 둠.)
        return state
      }
      const seg = toCamelTranscript(raw)

      // ticker 별 독립 컨테이너 가져오기 (없으면 생성).
      const prev =
        state.byTicker.get(seg.ticker) ?? emptyTickerState()

      // 1) 이미 종료된 callId 의 추가 segment 거부.
      if (prev.endedCallIds.has(seg.callId)) {
        return state
      }

      // 2) 단조성 검증 — 동일 callId 내 sequence 가 마지막 값 이하면 드롭.
      //    (중복 sequence 도 동일 처리. callId 가 처음이면 음수 sequence 만 거부.)
      const lastSeq = prev.lastSequenceByCall.get(seg.callId)
      if (lastSeq !== undefined && seg.sequence <= lastSeq) {
        return state
      }

      // 3) 새 segment 반영 — 불변성 유지를 위해 새 컨테이너로 교체.
      const nextSegments = [...prev.segments, seg]
      const nextLastSeqMap = new Map(prev.lastSequenceByCall)
      nextLastSeqMap.set(seg.callId, seg.sequence)
      const nextEndedCallIds = new Set(prev.endedCallIds)
      if (seg.isSessionEnd === true) {
        nextEndedCallIds.add(seg.callId)
      }

      const nextTickerState: TickerState = {
        segments: nextSegments,
        endedCallIds: nextEndedCallIds,
        lastSequenceByCall: nextLastSeqMap,
      }

      const nextByTicker = new Map(state.byTicker)
      nextByTicker.set(seg.ticker, nextTickerState)

      return { ...state, byTicker: nextByTicker }
    }),

  clearTicker: (ticker) =>
    set((state) => {
      if (!state.byTicker.has(ticker)) return state
      const nextByTicker = new Map(state.byTicker)
      nextByTicker.delete(ticker)
      return { ...state, byTicker: nextByTicker }
    }),

  reset: () =>
    set({
      byTicker: new Map(),
      currentTicker: null,
    }),
}))
