import { describe, it, expect, beforeEach, vi } from 'vitest'

const invoke = vi.fn()
const listeners: Array<(payload: unknown) => void> = []
vi.mock('../../lib/ipc', async () => {
  const { IPC_CHANNELS } = await import('../../../lib/ipcChannels')
  return {
    ipc: {
      invoke: (...args: unknown[]) => invoke(...args),
      on: (_channel: string, listener: (payload: unknown) => void) => {
        listeners.push(listener)
        return () => undefined
      },
    },
    IPC_CHANNELS,
  }
})

const showIpcErrorToast = vi.fn()
vi.mock('../../components/common/Toast', () => ({ showIpcErrorToast: (...args: unknown[]) => showIpcErrorToast(...args) }))

import { useAssistantStore, selectCanAsk, selectIsStreaming, selectRemainingQuestions } from '../useAssistantStore'
import { useTranscriptStore } from '../useTranscriptStore'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { IpcError } from '../../../lib/types/ipcError'
import { ASSISTANT_ERROR_MESSAGES } from '../../constants/assistant'

function segment(sequence: number, callId = 'call-1') {
  return { ticker: 'WMT', call_id: callId, sequence, start_ms: sequence * 1000, end_ms: sequence * 1000 + 500,
    text: `t${sequence}`, speaker: 'CEO', timestamp: 1_787_227_200 + sequence, is_session_end: false }
}

function emit(event: unknown) {
  for (const listener of listeners) listener(event)
}

function lastAskPayload() {
  const call = invoke.mock.calls.filter((c) => c[0] === IPC_CHANNELS.ASSISTANT_ASK).at(-1)
  return call?.[1] as { requestId: string; history: unknown[]; asOfSequence: number; anchorSequence: number | null; suggestedQuestionId: string | null; question: string }
}

beforeEach(() => {
  useAssistantStore.getState().reset()
  invoke.mockReset()
  showIpcErrorToast.mockReset()
  invoke.mockImplementation(async (_channel: string, payload: { requestId?: string }) => ({ requestId: payload?.requestId }))
  useTranscriptStore.getState().clearTicker('WMT')
  for (const s of [1, 2, 3]) useTranscriptStore.getState().upsertSegment(segment(s))
})

describe('useAssistantStore', () => {
  it('질문 시점은 보고 있는 콜의 마지막 세그먼트이고, 요청 id 는 스토어가 만든다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1', anchorSequence: 2 })
    await store.ask({ question: '  가이던스가 바뀌었어?  ' })

    const payload = lastAskPayload()
    expect(payload.asOfSequence).toBe(3)
    expect(payload.anchorSequence).toBe(2)
    expect(payload.question).toBe('가이던스가 바뀌었어?')
    expect(payload.requestId).toMatch(/.+/)
    expect(useAssistantStore.getState().conversation?.turns[0]).toMatchObject({ id: payload.requestId, status: 'pending' })
  })

  it('invoke 응답 전에 도착한 이벤트도 반영하고, 끝 이벤트로 상태를 정한다', async () => {
    invoke.mockImplementation(async (channel: string, payload: { requestId: string }) => {
      if (channel === IPC_CHANNELS.ASSISTANT_ASK) {
        emit({ requestId: payload.requestId, type: 'meta', data: { scope: 'call', as_of_sequence: 3, as_of_time: '2026-08-20T12:00:00Z', anchor_sequence: null, missing_sources: ['news'] } })
        emit({ requestId: payload.requestId, type: 'delta', data: { text: '매출이 ' } })
      }
      return { requestId: payload.requestId }
    })
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: '요약해 줘', suggestedQuestionId: 'summary' })
    const id = lastAskPayload().requestId

    emit({ requestId: id, type: 'delta', data: { text: '늘었습니다 [S3].' } })
    emit({ requestId: id, type: 'citations', data: [{ marker: 'S3', type: 'segment', ref: '3', title: null, source: null, published_at: 1, start_ms: 3000, speaker: 'CEO', quote: 'Comp sales grew', verified: true }] })
    emit({ requestId: id, type: 'done', data: { status: 'answered', refusal_reason: null, suggested_question_ids: [], warnings: ['uncited_number'], usage: {}, latency_ms: 10 } })
    emit({ requestId: id, type: 'delta', data: { text: '늦은 조각' } })

    const turn = useAssistantStore.getState().conversation!.turns[0]
    expect(turn.text).toBe('매출이 늘었습니다 [S3].')
    expect(turn.status).toBe('answered')
    expect(turn.meta).toEqual({ scope: 'call', asOfSequence: 3, asOfTime: '2026-08-20T12:00:00Z', anchorSequence: null, missingSources: ['news'] })
    expect(turn.citations).toEqual([{ marker: 'S3', type: 'segment', ref: '3', title: null, source: null, publishedAt: 1, startMs: 3000, speaker: 'CEO', quote: 'Comp sales grew', verified: true }])
    expect(turn.warnings).toEqual(['uncited_number'])
    expect(selectIsStreaming(useAssistantStore.getState())).toBe(false)
  })

  it('거절과 근거 없음을 상태로 구분하고, 거절 시 추천 질문을 남긴다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: '지금 사야 돼?' })
    const id = lastAskPayload().requestId
    emit({ requestId: id, type: 'done', data: { status: 'refused', refusal_reason: 'investment_advice', suggested_question_ids: ['guidance', 'vs_expectations'], warnings: [] } })

    expect(useAssistantStore.getState().conversation!.turns[0]).toMatchObject({
      status: 'refused', refusalReason: 'investment_advice', suggestedQuestionIds: ['guidance', 'vs_expectations'],
    })
  })

  it('error 이벤트는 code 별 한국어 문구로 바꾼다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })
    const id = lastAskPayload().requestId
    emit({ requestId: id, type: 'error', data: { code: 'llm_timeout', message: 'server text' } })

    expect(useAssistantStore.getState().conversation!.turns[0]).toMatchObject({
      status: 'error', error: { code: 'llm_timeout', message: ASSISTANT_ERROR_MESSAGES.llm_timeout },
    })
  })

  it('스트림 전 거절(429)은 reset_at 과 함께 오류 턴이 된다', async () => {
    invoke.mockImplementation(async (channel: string) => {
      if (channel === IPC_CHANNELS.ASSISTANT_ASK) {
        throw new IpcError('BUSINESS_RULE', '오늘 질문 횟수를 모두 썼습니다.', { status: 429, code: 'daily_limit_exceeded', message: '오늘 질문 횟수를 모두 썼습니다.', resetAt: '2026-10-07T15:00:00Z' })
      }
      return true
    })
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })

    expect(useAssistantStore.getState().conversation!.turns[0]).toMatchObject({
      status: 'error', error: { code: 'daily_limit_exceeded', message: ASSISTANT_ERROR_MESSAGES.daily_limit_exceeded }, resetAt: '2026-10-07T15:00:00Z',
    })
    expect(useAssistantStore.getState().activeTurnId).toBeNull()
  })

  it('로그인 만료는 오류 턴과 함께 재로그인 흐름(토스트)으로 알리고, 429 는 알리지 않는다', async () => {
    const expired = new IpcError('AUTH_EXPIRED', '로그인이 만료됐습니다.', { status: 401, code: null, message: '로그인이 만료됐습니다.', resetAt: null })
    invoke.mockImplementation(async (channel: string) => {
      if (channel === IPC_CHANNELS.ASSISTANT_ASK) throw expired
      return true
    })
    useAssistantStore.getState().open({ ticker: 'WMT', callId: 'call-1' })
    await useAssistantStore.getState().ask({ question: 'q' })

    expect(showIpcErrorToast).toHaveBeenCalledWith(expired)
    expect(useAssistantStore.getState().conversation!.turns[0].status).toBe('error')

    showIpcErrorToast.mockReset()
    useAssistantStore.getState().reset()
    invoke.mockImplementation(async (channel: string) => {
      if (channel === IPC_CHANNELS.ASSISTANT_ASK) {
        throw new IpcError('BUSINESS_RULE', 'x', { status: 429, code: 'daily_limit_exceeded', message: 'x', resetAt: null })
      }
      return true
    })
    useAssistantStore.getState().open({ ticker: 'WMT', callId: 'call-1' })
    await useAssistantStore.getState().ask({ question: 'q' })
    expect(showIpcErrorToast).not.toHaveBeenCalled()
  })

  it('후속 질문에는 직전 답변까지의 대화를 최대 3쌍 싣고, 질문은 대화당 4개까지다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    for (let i = 0; i < 4; i++) {
      await useAssistantStore.getState().ask({ question: `q${i}` })
      const id = lastAskPayload().requestId
      emit({ requestId: id, type: 'delta', data: { text: `a${i}` } })
      emit({ requestId: id, type: 'done', data: { status: 'answered', suggested_question_ids: [], warnings: [] } })
    }

    expect(lastAskPayload().history).toEqual([
      { role: 'user', text: 'q0' }, { role: 'assistant', text: 'a0' },
      { role: 'user', text: 'q1' }, { role: 'assistant', text: 'a1' },
      { role: 'user', text: 'q2' }, { role: 'assistant', text: 'a2' },
    ])
    expect(selectRemainingQuestions(useAssistantStore.getState())).toBe(0)
    expect(selectCanAsk(useAssistantStore.getState())).toBe(false)

    const callsBefore = invoke.mock.calls.length
    await useAssistantStore.getState().ask({ question: 'q4' })
    expect(invoke.mock.calls.length).toBe(callsBefore)
  })

  it('오류·취소된 턴은 대화 기록과 질문 수에서 빠진다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q0' })
    emit({ requestId: lastAskPayload().requestId, type: 'error', data: { code: 'llm_failed', message: 'x' } })
    await useAssistantStore.getState().ask({ question: 'q1' })

    expect(lastAskPayload().history).toEqual([])
    expect(selectRemainingQuestions(useAssistantStore.getState())).toBe(3)
  })

  it('취소하면 턴이 cancelled 가 되고, 그 요청의 늦은 이벤트는 무시한다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })
    const id = lastAskPayload().requestId
    await useAssistantStore.getState().cancel()
    emit({ requestId: id, type: 'delta', data: { text: '늦은 조각' } })

    expect(invoke).toHaveBeenCalledWith(IPC_CHANNELS.ASSISTANT_CANCEL, { requestId: id })
    expect(useAssistantStore.getState().conversation!.turns[0]).toMatchObject({ status: 'cancelled', text: '' })
    expect(selectIsStreaming(useAssistantStore.getState())).toBe(false)
  })

  it('진행 중에 새 질문을 하면 이전 턴을 취소하고 새 턴을 연다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q0' })
    const first = lastAskPayload().requestId
    await useAssistantStore.getState().ask({ question: 'q1' })

    const turns = useAssistantStore.getState().conversation!.turns
    expect(turns.map((t) => t.status)).toEqual(['cancelled', 'pending'])
    emit({ requestId: first, type: 'delta', data: { text: 'old' } })
    expect(useAssistantStore.getState().conversation!.turns[1].text).toBe('')
  })

  it('범위(콜·대목)가 바뀌면 새 대화를 시작하고, 같으면 이어 간다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q0' })
    useAssistantStore.getState().open({ ticker: 'WMT', callId: 'call-1' })
    expect(useAssistantStore.getState().conversation!.turns).toHaveLength(1)

    useAssistantStore.getState().open({ ticker: 'WMT', callId: 'call-1', anchorSequence: 2 })
    expect(useAssistantStore.getState().conversation).toEqual({ ticker: 'WMT', callId: 'call-1', anchorSequence: 2, turns: [] })
  })

  it('추천 질문은 대목 없이 콜 전체 범위로 보낸다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1', anchorSequence: 2 })
    await store.ask({ question: '지금까지 핵심을 요약해 줘', suggestedQuestionId: 'summary' })

    expect(lastAskPayload()).toMatchObject({ anchorSequence: null, suggestedQuestionId: 'summary' })
  })

  it('빈 질문과 500자 초과는 보내지 않는다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: '   ' })
    await store.ask({ question: '가'.repeat(501) })

    expect(invoke).not.toHaveBeenCalled()
  })

  it('형식이 틀린 이벤트는 무시한다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })
    const id = lastAskPayload().requestId
    emit(null)
    emit({ requestId: id, type: 'delta', data: { text: 3 } })
    emit({ requestId: id, type: 'citations', data: 'x' })

    expect(useAssistantStore.getState().conversation!.turns[0]).toMatchObject({ text: '', citations: [] })
  })

  it('스트리밍 중 연달아 질문해도 새 턴은 하나만 열린다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q0' })
    invoke.mockClear()
    const p1 = useAssistantStore.getState().ask({ question: 'qA' })
    const p2 = useAssistantStore.getState().ask({ question: 'qB' })
    await Promise.all([p1, p2])

    const turns = useAssistantStore.getState().conversation!.turns
    expect(turns.filter((t) => t.status === 'pending')).toHaveLength(1)
    expect(turns.map((t) => t.question)).toEqual(['q0', 'qB'])
    expect(invoke.mock.calls.filter((c) => c[0] === IPC_CHANNELS.ASSISTANT_ASK)).toHaveLength(1)
    expect(useAssistantStore.getState().activeTurnId).toBe(turns[1].id)
  })

  it('취소를 기다리는 사이 범위가 바뀌면 질문을 보내지 않는다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q0' })
    invoke.mockClear()
    const p = useAssistantStore.getState().ask({ question: 'q1' })
    useAssistantStore.getState().open({ ticker: 'WMT', callId: 'call-1', anchorSequence: 2 })
    await p

    expect(useAssistantStore.getState().conversation!.turns).toEqual([])
    expect(invoke.mock.calls.filter((c) => c[0] === IPC_CHANNELS.ASSISTANT_ASK)).toHaveLength(0)
  })

  it('초기화하면 진행 중인 요청을 취소한다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })
    const id = lastAskPayload().requestId
    useAssistantStore.getState().reset()

    expect(invoke).toHaveBeenCalledWith(IPC_CHANNELS.ASSISTANT_CANCEL, { requestId: id })
    expect(useAssistantStore.getState().conversation).toBeNull()
    expect(useAssistantStore.getState().activeTurnId).toBeNull()
  })

  it('invoke 가 cancelled 로 거절되면 턴은 cancelled 가 된다', async () => {
    invoke.mockImplementation(async () => {
      throw new IpcError('UNKNOWN', 'cancelled', { status: 0, code: 'cancelled', message: 'cancelled', resetAt: null })
    })
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })

    expect(useAssistantStore.getState().conversation!.turns[0].status).toBe('cancelled')
    expect(useAssistantStore.getState().activeTurnId).toBeNull()
  })

  it('done 의 no_evidence 는 그대로 상태가 된다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })
    emit({ requestId: lastAskPayload().requestId, type: 'done', data: { status: 'no_evidence', suggested_question_ids: [], warnings: [] } })

    expect(useAssistantStore.getState().conversation!.turns[0].status).toBe('no_evidence')
  })

  it('모르는 error code 는 서버 메시지를 쓴다', async () => {
    const store = useAssistantStore.getState()
    store.open({ ticker: 'WMT', callId: 'call-1' })
    await store.ask({ question: 'q' })
    emit({ requestId: lastAskPayload().requestId, type: 'error', data: { code: 'weird_code', message: 'server text' } })

    expect(useAssistantStore.getState().conversation!.turns[0]).toMatchObject({
      status: 'error', error: { code: 'weird_code', message: 'server text' },
    })
  })
})
