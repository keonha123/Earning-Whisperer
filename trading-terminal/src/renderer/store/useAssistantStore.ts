import { create } from 'zustand'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useTranscriptStore } from './useTranscriptStore'
import { isIpcError } from '../../lib/types/ipcError'
import type {
  AssistantAskRequest,
  AssistantHistoryTurn,
  AssistantRejection,
  SuggestedQuestionId,
} from '../../lib/types/assistant'
import {
  ASSISTANT_ERROR_MESSAGES,
  MAX_QUESTION_CHARS,
  MAX_QUESTIONS_PER_CONVERSATION,
  SUGGESTED_QUESTIONS,
} from '../constants/assistant'

/**
 * 어닝콜 질의응답 대화 상태 (#112).
 *
 * 대화는 범위(콜 + 고른 대목)에 묶이고, 범위가 바뀌면 새 대화가 된다. 질문은 대화당 4개(첫 질문 + 후속 3회)까지다.
 * 대화 기록은 이 스토어만 들고 있고 서버는 보관하지 않는다(질문마다 직전 3쌍을 보낸다).
 * 요청 id 를 여기서 만들어 보내므로, 스트림 이벤트가 invoke 응답보다 먼저 와도 그대로 반영한다.
 * 화면(컴포넌트·배치)은 이 스토어를 읽어 그린다.
 */

export interface AssistantCitation {
  marker: string
  type: 'segment' | 'news' | 'prior_statement' | 'estimate' | null
  ref: string | null
  title: string | null
  source: string | null
  publishedAt: number | null
  /** 세그먼트 인용이면 콜 시작 기준 ms. 해당 대목으로 이동할 때 쓴다. */
  startMs: number | null
  speaker: string | null
  quote: string | null
  /** false 면 원문과 일치하지 않을 수 있다(흐리게 표시). */
  verified: boolean
}

export interface AssistantMeta {
  scope: 'anchor' | 'call'
  asOfSequence: number
  asOfTime: string
  anchorSequence: number | null
  missingSources: string[]
}

export type AssistantTurnStatus = 'pending' | 'streaming' | 'answered' | 'refused' | 'no_evidence' | 'error' | 'cancelled'

export interface AssistantTurn {
  /** 요청 id. */
  id: string
  question: string
  suggestedQuestionId: SuggestedQuestionId | null
  status: AssistantTurnStatus
  /** 답 본문. 근거 표시([S12] 등)가 들어 있다. */
  text: string
  meta: AssistantMeta | null
  citations: AssistantCitation[]
  refusalReason: string | null
  /** 거절했을 때 대신 볼 만한 추천 질문. */
  suggestedQuestionIds: SuggestedQuestionId[]
  warnings: string[]
  error: { code: string; message: string } | null
  /** 하루 한도 초과일 때 다음 초기화 시각(UTC ISO-8601). */
  resetAt: string | null
}

export interface AssistantConversation {
  ticker: string
  callId: string
  anchorSequence: number | null
  turns: AssistantTurn[]
}

interface AssistantState {
  conversation: AssistantConversation | null
  /** 진행 중인 턴의 id. 없으면 null. */
  activeTurnId: string | null
  open: (scope: { ticker: string; callId: string; anchorSequence?: number | null }) => void
  ask: (input: { question: string; suggestedQuestionId?: SuggestedQuestionId | null }) => Promise<void>
  cancel: () => Promise<void>
  reset: () => void
  handleEvent: (event: unknown) => void
}

const SUGGESTED_IDS = new Set<string>(SUGGESTED_QUESTIONS.map((q) => q.id))
const FINISHED_FOR_HISTORY = new Set<AssistantTurnStatus>(['answered', 'no_evidence', 'refused'])
const HISTORY_PAIRS = 3

let unsubscribe: (() => void) | null = null

function ensureSubscribed(handle: (event: unknown) => void) {
  if (unsubscribe === null) unsubscribe = ipc.on(IPC_CHANNELS.ASSISTANT_EVENT, handle)
}

export const useAssistantStore = create<AssistantState>((set, get) => ({
  conversation: null,
  activeTurnId: null,

  open: ({ ticker, callId, anchorSequence = null }) => {
    const current = get().conversation
    if (current && current.ticker === ticker && current.callId === callId && current.anchorSequence === anchorSequence) return
    void get().cancel()
    set({ conversation: { ticker, callId, anchorSequence, turns: [] }, activeTurnId: null })
  },

  ask: async ({ question, suggestedQuestionId = null }) => {
    const conversation = get().conversation
    const trimmed = question.trim()
    if (!conversation || trimmed.length === 0 || trimmed.length > MAX_QUESTION_CHARS) return
    if (countedQuestions(conversation) >= MAX_QUESTIONS_PER_CONVERSATION) return
    ensureSubscribed(get().handleEvent)
    if (get().activeTurnId) await get().cancel()

    const current = get().conversation as AssistantConversation
    const requestId = crypto.randomUUID()
    const suggested = suggestedQuestionId && SUGGESTED_IDS.has(suggestedQuestionId) ? suggestedQuestionId : null
    const request: AssistantAskRequest = {
      requestId,
      ticker: current.ticker,
      callId: current.callId,
      asOfSequence: lastSequence(current.ticker, current.callId),
      anchorSequence: suggested ? null : current.anchorSequence,
      question: trimmed,
      suggestedQuestionId: suggested,
      history: historyOf(current),
    }
    set({
      conversation: { ...current, turns: [...current.turns, newTurn(requestId, trimmed, suggested)] },
      activeTurnId: requestId,
    })
    try {
      await ipc.invoke(IPC_CHANNELS.ASSISTANT_ASK, request)
    } catch (e) {
      if (get().activeTurnId !== requestId) return
      const rejection = rejectionOf(e)
      updateTurn(set, get, requestId, (turn) =>
        rejection.code === 'cancelled'
          ? { ...turn, status: 'cancelled' }
          : { ...turn, status: 'error', error: { code: rejection.code, message: rejection.message }, resetAt: rejection.resetAt },
      )
      set({ activeTurnId: null })
    }
  },

  cancel: async () => {
    const id = get().activeTurnId
    if (!id) return
    updateTurn(set, get, id, (turn) => ({ ...turn, status: 'cancelled' }))
    set({ activeTurnId: null })
    try {
      await ipc.invoke(IPC_CHANNELS.ASSISTANT_CANCEL, { requestId: id })
    } catch {
      // 취소 실패는 화면에 영향이 없다. backend 는 연결이 끊기면 스스로 정리한다.
    }
  },

  reset: () => set({ conversation: null, activeTurnId: null }),

  handleEvent: (event) => {
    if (!isStreamEvent(event)) return
    const id = get().activeTurnId
    if (event.requestId !== id) return
    const data = event.data
    switch (event.type) {
      case 'meta': {
        const meta = toMeta(data)
        if (meta) updateTurn(set, get, id, (turn) => ({ ...turn, meta, status: 'streaming' }))
        return
      }
      case 'delta': {
        const text = (data as { text?: unknown } | null)?.text
        if (typeof text === 'string') updateTurn(set, get, id, (turn) => ({ ...turn, text: turn.text + text, status: 'streaming' }))
        return
      }
      case 'citations': {
        if (Array.isArray(data)) updateTurn(set, get, id, (turn) => ({ ...turn, citations: data.map(toCitation).filter(isPresent) }))
        return
      }
      case 'done': {
        const done = (data ?? {}) as Record<string, unknown>
        const status = done.status === 'refused' || done.status === 'no_evidence' ? done.status : 'answered'
        updateTurn(set, get, id, (turn) => ({
          ...turn,
          status,
          refusalReason: typeof done.refusal_reason === 'string' ? done.refusal_reason : null,
          suggestedQuestionIds: Array.isArray(done.suggested_question_ids)
            ? (done.suggested_question_ids.filter((q) => typeof q === 'string' && SUGGESTED_IDS.has(q)) as SuggestedQuestionId[])
            : [],
          warnings: Array.isArray(done.warnings) ? done.warnings.filter((w): w is string => typeof w === 'string') : [],
        }))
        set({ activeTurnId: null })
        return
      }
      case 'error': {
        const payload = (data ?? {}) as Record<string, unknown>
        const code = typeof payload.code === 'string' ? payload.code : 'internal'
        const fallback = typeof payload.message === 'string' ? payload.message : ASSISTANT_ERROR_MESSAGES.internal
        updateTurn(set, get, id, (turn) => ({
          ...turn,
          status: 'error',
          error: { code, message: ASSISTANT_ERROR_MESSAGES[code] ?? fallback },
        }))
        set({ activeTurnId: null })
        return
      }
    }
  },
}))

export const selectIsStreaming = (state: AssistantState): boolean => state.activeTurnId !== null

export const selectRemainingQuestions = (state: AssistantState): number =>
  state.conversation ? Math.max(0, MAX_QUESTIONS_PER_CONVERSATION - countedQuestions(state.conversation)) : 0

export const selectCanAsk = (state: AssistantState): boolean =>
  state.conversation !== null && selectRemainingQuestions(state) > 0

type SetState = (partial: Partial<AssistantState>) => void
type GetState = () => AssistantState

function updateTurn(set: SetState, get: GetState, id: string, update: (turn: AssistantTurn) => AssistantTurn) {
  const conversation = get().conversation
  if (!conversation) return
  set({ conversation: { ...conversation, turns: conversation.turns.map((turn) => (turn.id === id ? update(turn) : turn)) } })
}

function newTurn(id: string, question: string, suggestedQuestionId: SuggestedQuestionId | null): AssistantTurn {
  return {
    id, question, suggestedQuestionId, status: 'pending', text: '', meta: null, citations: [],
    refusalReason: null, suggestedQuestionIds: [], warnings: [], error: null, resetAt: null,
  }
}

/** 질문 수에는 오류·취소된 턴을 세지 않는다(답을 받지 못했으므로). 진행 중인 턴은 센다. */
function countedQuestions(conversation: AssistantConversation): number {
  return conversation.turns.filter((turn) => turn.status !== 'error' && turn.status !== 'cancelled').length
}

function historyOf(conversation: AssistantConversation): AssistantHistoryTurn[] {
  return conversation.turns
    .filter((turn) => FINISHED_FOR_HISTORY.has(turn.status))
    .slice(-HISTORY_PAIRS)
    .flatMap((turn) => [
      { role: 'user' as const, text: turn.question },
      { role: 'assistant' as const, text: turn.text },
    ])
}

function lastSequence(ticker: string, callId: string): number {
  const segments = useTranscriptStore.getState().byTicker.get(ticker)?.segments ?? []
  let last = 0
  for (const segment of segments) if (segment.callId === callId && segment.sequence > last) last = segment.sequence
  return last
}

function rejectionOf(e: unknown): { code: string; message: string; resetAt: string | null } {
  if (isIpcError(e)) {
    const details = (e.details ?? null) as Partial<AssistantRejection> | null
    const code = details?.code ?? (e.code === 'AUTH_EXPIRED' ? 'auth_expired' : e.code === 'VALIDATION' ? 'validation' : e.code === 'NETWORK' ? 'network' : 'internal')
    return { code, message: ASSISTANT_ERROR_MESSAGES[code] ?? details?.message ?? e.message, resetAt: details?.resetAt ?? null }
  }
  return { code: 'internal', message: ASSISTANT_ERROR_MESSAGES.internal, resetAt: null }
}

function isStreamEvent(value: unknown): value is { requestId: string; type: string; data: unknown } {
  return value !== null && typeof value === 'object' &&
    typeof (value as Record<string, unknown>).requestId === 'string' &&
    typeof (value as Record<string, unknown>).type === 'string'
}

function toMeta(data: unknown): AssistantMeta | null {
  if (data === null || typeof data !== 'object') return null
  const d = data as Record<string, unknown>
  if (typeof d.as_of_sequence !== 'number' || typeof d.as_of_time !== 'string') return null
  return {
    scope: d.scope === 'anchor' ? 'anchor' : 'call',
    asOfSequence: d.as_of_sequence,
    asOfTime: d.as_of_time,
    anchorSequence: typeof d.anchor_sequence === 'number' ? d.anchor_sequence : null,
    missingSources: Array.isArray(d.missing_sources) ? d.missing_sources.filter((s): s is string => typeof s === 'string') : [],
  }
}

function toCitation(value: unknown): AssistantCitation | null {
  if (value === null || typeof value !== 'object') return null
  const c = value as Record<string, unknown>
  if (typeof c.marker !== 'string') return null
  const str = (v: unknown) => (typeof v === 'string' ? v : null)
  const num = (v: unknown) => (typeof v === 'number' ? v : null)
  const type = c.type === 'segment' || c.type === 'news' || c.type === 'prior_statement' || c.type === 'estimate' ? c.type : null
  return {
    marker: c.marker, type, ref: str(c.ref), title: str(c.title), source: str(c.source),
    publishedAt: num(c.published_at), startMs: num(c.start_ms), speaker: str(c.speaker), quote: str(c.quote),
    verified: c.verified === true,
  }
}

function isPresent<T>(value: T | null): value is T {
  return value !== null
}
