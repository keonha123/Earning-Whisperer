import { create } from 'zustand'

/**
 * 어닝콜 자막 한국어 번역 클라이언트 상태 (#110).
 *
 * Backend STOMP /topic/transcript-translation/{ticker} (Contract 4.8) push 와 1:1 매핑.
 * useTranscriptDiffStore 와 같은 패턴 — snake_case payload 를 camelCase 로 바꾸고, 형식이 어긋나면
 * silent drop 한다.
 *
 * 번역은 세그먼트 몇 개를 묶은 한 문단 단위로 온다. `sequences` 가 그 문단에 담긴 원문 세그먼트다.
 * 도착 순서가 뒤집힐 수 있어 첫 sequence 기준으로 정렬해 둔다.
 */

export interface TranscriptTranslation {
  callId: string
  /** 이 번역이 담은 원문 세그먼트 sequence. 오름차순, 1개 이상. */
  sequences: number[]
  /** 한국어 번역문. UI 에 그대로 노출한다. */
  textKo: string
  /** 사전 번역어가 번역문에 실제로 들어간 용어 (원문 표기). 밑줄 위치를 찾을 때 쓴다. */
  termsUsed: string[]
}

interface TickerState {
  callId: string
  items: TranscriptTranslation[]
  /** sequences 를 이은 키. 재연결 시 중복 push 를 거른다. */
  seenKeys: Set<string>
}

interface TranscriptTranslationState {
  byTicker: Map<string, TickerState>
  /**
   * ticker → 지나간 회차 call_id. 번역은 LLM 지연만큼 늦게 오므로, 시연을 다시 시작한 뒤에도 이전 회차의
   * 번역이 도착할 수 있다. 그 번역이 새 회차를 밀어내지 않도록 버린다. clearTicker 로도 지우지 않는다.
   */
  retiredCallIds: Map<string, Set<string>>

  /** snake_case payload 1건을 검증 후 반영. 형식 불일치 시 silent drop. */
  upsertTranslation: (raw: unknown) => void

  /** 해당 ticker 의 누적 번역을 비운다. 시연 재시작 시 호출. */
  clearTicker: (ticker: string) => void
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function toSequences(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  if (!value.every((v) => typeof v === 'number' && Number.isInteger(v) && v >= 0)) return null
  return [...new Set(value as number[])].sort((a, b) => a - b)
}

export const useTranscriptTranslationStore = create<TranscriptTranslationState>((set) => ({
  byTicker: new Map(),
  retiredCallIds: new Map(),

  upsertTranslation: (raw) => {
    if (!isRecord(raw)) return
    const { ticker, call_id: callId, text_ko: textKo } = raw
    if (typeof ticker !== 'string' || !ticker) return
    if (typeof callId !== 'string' || !callId) return
    // 번역문이 없으면 보여줄 것이 없다. 원문을 대신 넣지 않는다.
    if (typeof textKo !== 'string' || !textKo.trim()) return
    const sequences = toSequences(raw.sequences)
    if (!sequences) return
    const termsUsed = Array.isArray(raw.terms_used)
      ? raw.terms_used.filter((t): t is string => typeof t === 'string' && t.trim() !== '')
      : []

    const key = sequences.join(',')
    set((state) => {
      if (state.retiredCallIds.get(ticker)?.has(callId)) return state
      const prev = state.byTicker.get(ticker)
      // 다른 회차의 번역이 오면 새 회차로 보고, 이전 회차는 지나간 것으로 기록해 버린다.
      const base = prev && prev.callId === callId ? prev : null
      if (base?.seenKeys.has(key)) return state

      let retiredCallIds = state.retiredCallIds
      if (prev && prev.callId !== callId) {
        retiredCallIds = new Map(retiredCallIds)
        retiredCallIds.set(ticker, new Set([...(retiredCallIds.get(ticker) ?? []), prev.callId]))
      }

      const item: TranscriptTranslation = { callId, sequences, textKo, termsUsed }
      const items = [...(base?.items ?? []), item].sort((a, b) => a.sequences[0] - b.sequences[0])
      const next = new Map(state.byTicker)
      next.set(ticker, { callId, items, seenKeys: new Set([...(base?.seenKeys ?? []), key]) })
      return { byTicker: next, retiredCallIds }
    })
  },

  clearTicker: (ticker) =>
    set((state) => {
      const prev = state.byTicker.get(ticker)
      if (!prev) return state
      const next = new Map(state.byTicker)
      next.delete(ticker)
      // 비운 회차의 번역이 뒤늦게 와서 다시 살아나지 않게 한다.
      const retiredCallIds = new Map(state.retiredCallIds)
      retiredCallIds.set(ticker, new Set([...(retiredCallIds.get(ticker) ?? []), prev.callId]))
      return { byTicker: next, retiredCallIds }
    }),
}))
