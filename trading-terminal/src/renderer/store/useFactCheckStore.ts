import { create } from 'zustand'

/**
 * 실시간 어닝콜 팩트체크 클라이언트 상태.
 *
 * Backend Contract 4.6 (STOMP /topic/factcheck/{ticker} push) 와 1:1 매핑.
 * useTranscriptStore 와 동일한 패턴 — snake_case payload 를 store 에서 camelCase 로
 * 변환하고, 형식이 어긋나면 silent drop 한다.
 *
 * 중복/순서 정책:
 *  - 같은 claimId 재도착 → 무시 (idempotency). 재연결 시 중복 push 가능성 대비.
 *  - 배치는 도착 순서대로 append 한다. AI Engine 이 3문장 배치를 순서대로 처리하므로
 *    도착 순서가 곧 발언 순서다.
 *  - ticker 별 독립 컨테이너.
 */

/** 판정값. AI Engine 의 3종을 그대로 쓴다 (Contract 9.3). */
export type FactCheckVerdict = 'SUPPORTED' | 'CONTRADICTED' | 'INSUFFICIENT_EVIDENCE'

export interface FactCheckEvidence {
  docId: string
  title: string
  snippet: string
  url: string
  /** 매체명 (예: "reuters"). */
  source: string
}

export interface FactCheckClaim {
  claimId: string
  /** 검증 대상 주장 (정규화된 문장). */
  claim: string
  verdict: FactCheckVerdict
  /** 0~1. */
  confidence: number
  /** 한국어 판정 설명. UI 에 그대로 노출한다. */
  explanationKo: string
  reasonCode: string
  evidence: FactCheckEvidence[]
  /** 이 판정이 어느 발언 범위에 대한 것인지 (트랜스크립트 sequence). */
  batchStartSequence: number
  batchEndSequence: number
}

interface TickerState {
  claims: FactCheckClaim[]
  seenClaimIds: Set<string>
}

interface FactCheckState {
  byTicker: Map<string, TickerState>

  /** snake_case 배치 payload 1건을 검증 후 append. 형식 불일치 시 silent drop. */
  upsertBatch: (raw: unknown) => void

  /** 해당 ticker 의 누적 판정을 비운다. 시연 재시작 시 호출. */
  clearTicker: (ticker: string) => void
}

const VALID_VERDICTS: ReadonlySet<string> = new Set([
  'SUPPORTED',
  'CONTRADICTED',
  'INSUFFICIENT_EVIDENCE',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function toEvidence(raw: unknown): FactCheckEvidence | null {
  if (!isRecord(raw)) return null
  const docId = raw.doc_id
  if (typeof docId !== 'string' || !docId) return null
  return {
    docId,
    title: typeof raw.title === 'string' ? raw.title : '',
    snippet: typeof raw.snippet === 'string' ? raw.snippet : '',
    url: typeof raw.url === 'string' ? raw.url : '',
    source: typeof raw.source === 'string' ? raw.source : 'unknown',
  }
}

function toClaim(raw: unknown, startSeq: number, endSeq: number): FactCheckClaim | null {
  if (!isRecord(raw)) return null
  const { claim_id: claimId, claim, verdict, explanation_ko: explanationKo } = raw
  if (typeof claimId !== 'string' || !claimId) return null
  if (typeof claim !== 'string' || !claim) return null
  if (typeof verdict !== 'string' || !VALID_VERDICTS.has(verdict)) return null
  // 설명이 없으면 카드에 표시할 내용이 없다 — 판정만 덩그러니 띄우지 않는다.
  if (typeof explanationKo !== 'string' || !explanationKo) return null

  const confidence = typeof raw.confidence === 'number' && Number.isFinite(raw.confidence)
    ? Math.min(1, Math.max(0, raw.confidence))
    : 0

  const evidence = Array.isArray(raw.evidence)
    ? raw.evidence.map(toEvidence).filter((e): e is FactCheckEvidence => e !== null)
    : []

  return {
    claimId,
    claim,
    verdict: verdict as FactCheckVerdict,
    confidence,
    explanationKo,
    reasonCode: typeof raw.reason_code === 'string' ? raw.reason_code : '',
    evidence,
    batchStartSequence: startSeq,
    batchEndSequence: endSeq,
  }
}

export const useFactCheckStore = create<FactCheckState>((set) => ({
  byTicker: new Map(),

  upsertBatch: (raw) => {
    if (!isRecord(raw)) return
    const ticker = raw.ticker
    if (typeof ticker !== 'string' || !ticker) return
    if (!Array.isArray(raw.claims) || raw.claims.length === 0) return

    const startSeq = typeof raw.batch_start_sequence === 'number' ? raw.batch_start_sequence : -1
    const endSeq = typeof raw.batch_end_sequence === 'number' ? raw.batch_end_sequence : -1

    const parsed = raw.claims
      .map((c) => toClaim(c, startSeq, endSeq))
      .filter((c): c is FactCheckClaim => c !== null)
    if (parsed.length === 0) return

    set((state) => {
      const prev = state.byTicker.get(ticker)
      const seen = new Set(prev?.seenClaimIds ?? [])
      const fresh = parsed.filter((c) => !seen.has(c.claimId))
      if (fresh.length === 0) return state

      fresh.forEach((c) => seen.add(c.claimId))
      const next = new Map(state.byTicker)
      next.set(ticker, {
        claims: [...(prev?.claims ?? []), ...fresh],
        seenClaimIds: seen,
      })
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
