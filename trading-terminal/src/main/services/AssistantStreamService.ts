import { BackendClient } from './BackendClient'
import { mainState } from '../store/mainState'
import { IpcError, type IpcErrorCode } from '../../lib/types/ipcError'
import { SseParser } from '../../lib/sse'
import type {
  AssistantAskRequest,
  AssistantAskStarted,
  AssistantEventType,
  AssistantRejection,
  AssistantStreamEvent,
} from '../../lib/types/assistant'

/**
 * 어닝콜 질의응답 스트림 (#112, Contract 7.10).
 *
 * backend 의 SSE 를 Node 내장 fetch 로 읽어 프레임마다 renderer 로 민다. axios 는 응답을 다 받은 뒤에야
 * 돌려주므로 스트림에는 쓰지 않는다. 한 창에서 질문은 하나만 진행한다 — 새 질문이 오면 이전 연결을 끊는다.
 * 연결을 끊으면 backend 가 assistant 연결을 닫고, assistant 가 OpenAI 생성을 멈춘다.
 */

export type AssistantEventSink = (event: AssistantStreamEvent) => void

export interface AssistantStreamDeps {
  fetch: typeof fetch
  sleep: (ms: number) => Promise<void>
  now: () => number
  baseUrl: string
}

const EVENT_TYPES = new Set<AssistantEventType>(['meta', 'delta', 'citations', 'done', 'error'])
const TERMINAL_EVENTS = new Set<AssistantEventType>(['done', 'error'])
// 직전 질문을 취소한 직후에는 backend 가 끊김을 알아채기 전(하트비트 주기 수 초)이라 같은 사용자의 잠금이 남아 409 가 온다.
// 그때만 짧게 기다렸다 다시 보낸다. 다른 기기에서 진행 중인 질문 때문인 409 는 바로 알린다.
const BUSY_RETRY_WINDOW_MS = 10_000
const BUSY_RETRY_DELAYS_MS = [1_500, 2_500, 3_500]

const DEFAULT_MESSAGES: Record<string, string> = {
  network: '서버에 연결하지 못했습니다.',
  cancelled: '질문을 취소했습니다.',
  auth: '로그인이 만료됐습니다. 다시 로그인해 주세요.',
  failed: '질문을 보내지 못했습니다.',
}

interface ActiveRequest {
  requestId: string
  controller: AbortController
  reader: ReadableStreamDefaultReader<Uint8Array> | null
}

export class AssistantStreamService {
  private readonly deps: AssistantStreamDeps
  private active: ActiveRequest | null = null
  private lastCancelAt = Number.NEGATIVE_INFINITY

  constructor(deps: Partial<AssistantStreamDeps> = {}) {
    this.deps = {
      fetch: deps.fetch ?? ((input, init) => globalThis.fetch(input, init)),
      sleep: deps.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms))),
      now: deps.now ?? (() => Date.now()),
      baseUrl: deps.baseUrl ?? process.env.BACKEND_URL ?? 'http://localhost:8082',
    }
  }

  async ask(request: AssistantAskRequest, sink: AssistantEventSink): Promise<AssistantAskStarted> {
    this.cancel()
    const controller = new AbortController()
    const active: ActiveRequest = { requestId: request.requestId, controller, reader: null }
    this.active = active
    let response: Response
    try {
      response = await this.open(request, controller.signal)
    } catch (error) {
      if (this.active === active) this.active = null
      throw error
    }
    if (this.active !== active) {
      controller.abort()
      throw rejection('BUSINESS_RULE', 0, 'cancelled', DEFAULT_MESSAGES.cancelled)
    }
    if (!response.body) {
      this.active = null
      controller.abort()
      throw rejection('UNKNOWN', 0, 'stream_interrupted', '답변 전송이 중간에 끊겼습니다.')
    }
    active.reader = response.body.getReader()
    void this.pump(active, sink)
    return { requestId: request.requestId }
  }

  /** 진행 중인 질문을 끊는다. requestId 를 주면 그 요청일 때만 끊는다. 끊었으면 true. */
  cancel(requestId?: string): boolean {
    const active = this.active
    if (!active || (requestId !== undefined && active.requestId !== requestId)) return false
    this.active = null
    this.lastCancelAt = this.deps.now()
    active.controller.abort()
    void active.reader?.cancel().catch(() => undefined)
    return true
  }

  private async open(request: AssistantAskRequest, signal: AbortSignal): Promise<Response> {
    let refreshed = false
    let busyAttempts = 0
    for (;;) {
      let response: Response
      try {
        response = await this.deps.fetch(`${this.deps.baseUrl}/api/v1/assistant/ask`, {
          method: 'POST',
          signal,
          headers: headers(),
          body: JSON.stringify(toBody(request)),
        })
      } catch {
        if (signal.aborted) throw rejection('BUSINESS_RULE', 0, 'cancelled', DEFAULT_MESSAGES.cancelled)
        throw rejection('NETWORK', 0, 'network', DEFAULT_MESSAGES.network)
      }
      if (response.ok) return response

      const body = await readJson(response)
      const code = typeof body.code === 'string' ? body.code : null
      if (response.status === 401 && !refreshed) {
        refreshed = true
        try {
          await BackendClient.refreshSession()
        } catch {
          // 세션이 끝났으면(토큰 없음) 재로그인, 일시적인 갱신 실패면 연결 문제로 알린다.
          if (!mainState.backendToken) throw rejection('AUTH_EXPIRED', 401, code, DEFAULT_MESSAGES.auth)
          throw rejection('NETWORK', 0, 'network', DEFAULT_MESSAGES.network)
        }
        continue
      }
      const recentlyCancelled = this.deps.now() - this.lastCancelAt < BUSY_RETRY_WINDOW_MS
      if (response.status === 409 && code === 'assistant_busy' && recentlyCancelled && busyAttempts < BUSY_RETRY_DELAYS_MS.length) {
        await this.deps.sleep(BUSY_RETRY_DELAYS_MS[busyAttempts])
        busyAttempts += 1
        if (signal.aborted) throw rejection('BUSINESS_RULE', 0, 'cancelled', DEFAULT_MESSAGES.cancelled)
        continue
      }
      const message = typeof body.error === 'string' ? body.error : DEFAULT_MESSAGES.failed
      const resetAt = typeof body.reset_at === 'string' ? body.reset_at : null
      throw rejection(errorCodeFor(response.status), response.status, code, message, resetAt)
    }
  }

  private async pump(active: ActiveRequest, sink: AssistantEventSink): Promise<void> {
    const reader = active.reader as ReadableStreamDefaultReader<Uint8Array>
    const parser = new SseParser()
    const decoder = new TextDecoder()
    let sinkFailed = false
    const emit = (type: AssistantEventType, data: unknown) => {
      if (sinkFailed) return
      try {
        sink({ requestId: active.requestId, type, data })
      } catch {
        sinkFailed = true
        active.controller.abort()
      }
    }
    let terminal = false
    let interrupted = false
    try {
      reading: for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
          if (!EVENT_TYPES.has(frame.event as AssistantEventType)) continue
          let data: unknown
          try {
            data = JSON.parse(frame.data)
          } catch {
            continue
          }
          emit(frame.event as AssistantEventType, data)
          if (TERMINAL_EVENTS.has(frame.event as AssistantEventType)) {
            terminal = true
            break reading
          }
        }
      }
      interrupted = !terminal && !active.controller.signal.aborted
    } catch {
      // 사용자가 취소했으면(abort) 화면은 이미 취소 상태다. 그 밖의 읽기 실패는 끊김으로 알린다.
      interrupted = !active.controller.signal.aborted
    } finally {
      if (this.active === active) this.active = null
      // 끝 이벤트 뒤에는 연결을 닫는다. backend 가 뒤늦게 보내는 이벤트와 하트비트를 받을 이유가 없다.
      active.controller.abort()
      void reader.cancel().catch(() => undefined)
    }
    if (interrupted) emit('error', { code: 'stream_interrupted', message: '답변 전송이 중간에 끊겼습니다.' })
  }
}

function headers(): Record<string, string> {
  const result: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream, application/json',
  }
  const token = mainState.backendToken
  if (token) result.Authorization = `Bearer ${token}`
  return result
}

function toBody(request: AssistantAskRequest) {
  return {
    ticker: request.ticker,
    call_id: request.callId,
    as_of_sequence: request.asOfSequence,
    anchor_sequence: request.anchorSequence,
    question: request.question,
    suggested_question_id: request.suggestedQuestionId,
    history: request.history.map((turn) => ({ role: turn.role, text: turn.text })),
  }
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const value = (await response.json()) as unknown
    return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

function errorCodeFor(status: number): IpcErrorCode {
  if (status === 401) return 'AUTH_EXPIRED'
  if (status === 400) return 'VALIDATION'
  if (status === 404 || status === 409 || status === 429) return 'BUSINESS_RULE'
  if (status >= 500) return 'BACKEND_5XX'
  return 'UNKNOWN'
}

function rejection(
  ipcCode: IpcErrorCode,
  status: number,
  code: string | null,
  message: string,
  resetAt: string | null = null,
): IpcError {
  const details: AssistantRejection = { status, code, message, resetAt }
  return new IpcError(ipcCode, message, details)
}

export const assistantStreamService = new AssistantStreamService()
