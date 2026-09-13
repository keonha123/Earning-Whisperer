import { create } from 'zustand'

/**
 * 직전 콜 발언 대조 클라이언트 상태.
 *
 * Backend STOMP /topic/transcript-diff/{ticker} push 와 1:1 매핑.
 * useFactCheckStore 와 동일한 패턴 — snake_case payload 를 store 에서 camelCase 로
 * 변환하고, 형식이 어긋나면 silent drop 한다.
 *
 * 팩트체크와 다른 점:
 *  - 근거가 뉴스가 아니라 <b>같은 회사의 직전 콜 발언</b>이다.
 *  - 도착 빈도가 훨씬 낮다. 주제와 무관한 발언은 백엔드가 발행하지 않는다.
 *  - 항목에 고유 id 가 없다. 그래서 `sequence` + 항목 순서로 중복을 판정한다.
 */

/** 변화 유형. AI Engine 의 5종을 그대로 쓴다. */
export type TranscriptDiffChangeType =
  | 'improved'
  | 'weakened'
  | 'unchanged'
  | 'mixed'
  | 'new_claim'

export interface TranscriptDiffEvidence {
  documentId: string
  title: string
  snippet: string
  publishedAt: string
  /** 0~1. 직전 콜 발언과의 관련도. */
  relevanceScore: number
}

export interface TranscriptDiffItem {
  /** guidance / margin / demand / capex / supply / competition / revenue 중 하나. */
  topic: string
  changeType: TranscriptDiffChangeType
  /** 무엇이 달라졌는지에 대한 한국어 설명. UI 에 그대로 노출한다. */
  summaryKo: string
  /** 이번 콜의 발언. */
  currentClaim: string
  /** 직전 콜의 대응 발언. 없으면 빈 문자열. */
  priorClaim: string
  /** 0~1. */
  confidence: number
  /** 0~1. 높을수록 부정적 변화. */
  riskScore: number
  evidence: TranscriptDiffEvidence[]
  /** 어느 발언에 대한 대조인지 (트랜스크립트 sequence). */
  sequence: number
}

/** 대조 대상이 된 직전 콜. 화면 상단에 "무엇과 비교했는지" 를 밝히는 데 쓴다. */
export interface PreviousCall {
  documentId: string
  title: string
  publishedAt: string
  fiscalQuarter: string
}

interface TickerState {
  items: TranscriptDiffItem[]
  previousCall: PreviousCall | null
  /** `${sequence}:${index}` 집합. 재연결 시 중복 push 를 거른다. */
  seenKeys: Set<string>
}

interface TranscriptDiffState {
  byTicker: Map<string, TickerState>

  /** snake_case payload 1건을 검증 후 append. 형식 불일치 시 silent drop. */
  upsertDiff: (raw: unknown) => void

  /** 해당 ticker 의 누적 대조를 비운다. 시연 재시작 시 호출. */
  clearTicker: (ticker: string) => void
}

const VALID_CHANGE_TYPES: ReadonlySet<string> = new Set([
  'improved',
  'weakened',
  'unchanged',
  'mixed',
  'new_claim',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function toUnitRange(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : 0
}

function toEvidence(raw: unknown): TranscriptDiffEvidence | null {
  if (!isRecord(raw)) return null
  const documentId = raw.document_id
  if (typeof documentId !== 'string' || !documentId) return null
  const snippet = typeof raw.snippet === 'string' ? raw.snippet : ''
  // 발췌가 없으면 "직전 콜에서 무슨 말을 했는지" 를 보여줄 수 없다. 근거 구실을 못한다.
  if (!snippet) return null
  return {
    documentId,
    title: typeof raw.title === 'string' ? raw.title : '',
    snippet,
    publishedAt: typeof raw.published_at === 'string' ? raw.published_at : '',
    relevanceScore: toUnitRange(raw.relevance_score),
  }
}

function toItem(raw: unknown, sequence: number): TranscriptDiffItem | null {
  if (!isRecord(raw)) return null
  const { change_type: changeType, summary_ko: summaryKo } = raw
  if (typeof changeType !== 'string' || !VALID_CHANGE_TYPES.has(changeType)) return null
  // 설명이 없으면 카드에 표시할 내용이 없다 — 유형만 덩그러니 띄우지 않는다.
  if (typeof summaryKo !== 'string' || !summaryKo) return null

  const evidence = Array.isArray(raw.evidence)
    ? raw.evidence.map(toEvidence).filter((e): e is TranscriptDiffEvidence => e !== null)
    : []

  return {
    topic: typeof raw.topic === 'string' && raw.topic ? raw.topic : 'general',
    changeType: changeType as TranscriptDiffChangeType,
    summaryKo,
    currentClaim: typeof raw.current_claim === 'string' ? raw.current_claim : '',
    priorClaim: typeof raw.prior_claim === 'string' ? raw.prior_claim : '',
    confidence: toUnitRange(raw.confidence),
    riskScore: toUnitRange(raw.risk_score),
    evidence,
    sequence,
  }
}

function toPreviousCall(raw: unknown): PreviousCall | null {
  if (!isRecord(raw)) return null
  const documentId = raw.document_id
  if (typeof documentId !== 'string' || !documentId) return null
  return {
    documentId,
    title: typeof raw.title === 'string' ? raw.title : '',
    publishedAt: typeof raw.published_at === 'string' ? raw.published_at : '',
    fiscalQuarter: typeof raw.fiscal_quarter === 'string' ? raw.fiscal_quarter : '',
  }
}

export const useTranscriptDiffStore = create<TranscriptDiffState>((set) => ({
  byTicker: new Map(),

  upsertDiff: (raw) => {
    if (!isRecord(raw)) return
    const ticker = raw.ticker
    if (typeof ticker !== 'string' || !ticker) return
    if (!Array.isArray(raw.items) || raw.items.length === 0) return

    const sequence = typeof raw.sequence === 'number' ? raw.sequence : -1
    const parsed = raw.items
      .map((item, index) => {
        const converted = toItem(item, sequence)
        return converted ? { key: `${sequence}:${index}`, item: converted } : null
      })
      .filter((entry): entry is { key: string; item: TranscriptDiffItem } => entry !== null)
    if (parsed.length === 0) return

    const previousCall = toPreviousCall(raw.previous_document)

    set((state) => {
      const prev = state.byTicker.get(ticker)
      const seen = new Set(prev?.seenKeys ?? [])
      const fresh = parsed.filter((entry) => !seen.has(entry.key))
      if (fresh.length === 0) return state

      fresh.forEach((entry) => seen.add(entry.key))
      const next = new Map(state.byTicker)
      next.set(ticker, {
        items: [...(prev?.items ?? []), ...fresh.map((entry) => entry.item)],
        // 직전 콜은 회차 내내 같다. 먼저 받은 값을 유지한다.
        previousCall: prev?.previousCall ?? previousCall,
        seenKeys: seen,
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
