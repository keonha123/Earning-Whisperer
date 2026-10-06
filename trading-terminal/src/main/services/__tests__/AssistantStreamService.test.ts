import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AssistantStreamService } from '../AssistantStreamService'
import { BackendClient } from '../BackendClient'
import { mainState } from '../../store/mainState'
import type { AssistantAskRequest, AssistantStreamEvent } from '../../../lib/types/assistant'
import { IpcError } from '../../../lib/types/ipcError'

const encoder = new TextEncoder()

function sseResponse(chunks: string[], keepOpen = false): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      if (!keepOpen) controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function request(overrides: Partial<AssistantAskRequest> = {}): AssistantAskRequest {
  return {
    requestId: 'r1', ticker: 'WMT', callId: 'call-1', asOfSequence: 17, anchorSequence: null,
    question: '요약해 줘', suggestedQuestionId: 'summary', history: [{ role: 'user', text: '앞 질문' }],
    ...overrides,
  }
}

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setTimeout(resolve, 0))
}

function setup(
  fetchImpl: (...args: unknown[]) => Promise<Response>,
  now = () => 1_000_000,
  extra: { baseUrl?: string; idleTimeoutMs?: number } = {},
) {
  const fetch = vi.fn(fetchImpl)
  const sleep = vi.fn(async () => undefined)
  const service = new AssistantStreamService({
    fetch: fetch as unknown as typeof globalThis.fetch, sleep, now, baseUrl: extra.baseUrl ?? 'http://backend', idleTimeoutMs: extra.idleTimeoutMs,
  })
  const events: AssistantStreamEvent[] = []
  return { fetch, sleep, service, events, sink: (e: AssistantStreamEvent) => events.push(e) }
}

beforeEach(() => {
  mainState.setBackendToken('tok')
  mainState.setBackendRefreshToken('rt')
})

describe('AssistantStreamService', () => {
  it('snake_case 본문과 인증·Accept 헤더로 보내고 이벤트를 순서대로 민다', async () => {
    const { fetch, service, events, sink } = setup(async () =>
      sseResponse([
        'event:meta\ndata:{"scope": "call"}\n\n:\n\n',
        'event:delta\ndata:{"text": "매',
        '출"}\n\nevent:citations\ndata:[]\n\n',
        'event:done\ndata:{"status": "answered"}\n\nevent:delta\ndata:{"text": "늦은 조각"}\n\n',
      ]),
    )

    await expect(service.ask(request(), sink)).resolves.toEqual({ requestId: 'r1' })
    await flush()

    const [url, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('http://backend/api/v1/assistant/ask')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
    expect((init.headers as Record<string, string>).Accept).toBe('text/event-stream, application/json')
    expect(JSON.parse(init.body as string)).toEqual({
      ticker: 'WMT', call_id: 'call-1', as_of_sequence: 17, anchor_sequence: null,
      question: '요약해 줘', suggested_question_id: 'summary', history: [{ role: 'user', text: '앞 질문' }],
    })
    expect(events.map((e) => [e.requestId, e.type, e.data])).toEqual([
      ['r1', 'meta', { scope: 'call' }],
      ['r1', 'delta', { text: '매출' }],
      ['r1', 'citations', []],
      ['r1', 'done', { status: 'answered' }],
    ])
  })

  it('끝 이벤트 없이 스트림이 끝나면 stream_interrupted 를 민다', async () => {
    const { service, events, sink } = setup(async () => sseResponse(['event:delta\ndata:{"text": "앞"}\n\n']))

    await service.ask(request(), sink)
    await flush()

    expect(events.map((e) => e.type)).toEqual(['delta', 'error'])
    expect(events[1].data).toEqual({ code: 'stream_interrupted', message: '답변 전송이 중간에 끊겼습니다.' })
  })

  it('JSON 이 아닌 data 와 모르는 이벤트는 건너뛴다', async () => {
    const { service, events, sink } = setup(async () =>
      sseResponse(['event:delta\ndata:not-json\n\nevent:ping\ndata:{}\n\nevent:done\ndata:{}\n\n']),
    )

    await service.ask(request(), sink)
    await flush()

    expect(events.map((e) => e.type)).toEqual(['done'])
  })

  it('401 이면 토큰을 갱신하고 한 번 다시 보낸다', async () => {
    const refresh = vi.spyOn(BackendClient, 'refreshSession').mockImplementation(async () => {
      mainState.setBackendToken('tok2')
    })
    const responses = [jsonResponse(401, { error: 'expired' }), sseResponse(['event:done\ndata:{}\n\n'])]
    const { fetch, service, sink } = setup(async () => responses.shift() as Response)

    await service.ask(request(), sink)

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(2)
    const [, retryInit] = fetch.mock.calls[1] as [string, RequestInit]
    expect((retryInit.headers as Record<string, string>).Authorization).toBe('Bearer tok2')
  })

  it('갱신이 일시적으로 실패하고 세션이 살아 있으면 NETWORK', async () => {
    vi.spyOn(BackendClient, 'refreshSession').mockRejectedValue(new Error('timeout'))
    const { service, sink } = setup(async () => jsonResponse(401, {}))

    await expect(service.ask(request(), sink)).rejects.toMatchObject({ code: 'NETWORK' })
  })

  it('갱신 실패로 세션이 끝났으면 AUTH_EXPIRED', async () => {
    vi.spyOn(BackendClient, 'refreshSession').mockImplementation(async () => {
      mainState.setBackendToken(null)
      throw new Error('no refresh token')
    })
    const { service, sink } = setup(async () => jsonResponse(401, {}))

    await expect(service.ask(request(), sink)).rejects.toMatchObject({ code: 'AUTH_EXPIRED' })
  })

  it('거절된 요청은 진행 중으로 남지 않아 다음 409 를 재시도하지 않고 cancel 도 false', async () => {
    const { fetch, sleep, service, sink } = setup(async () => jsonResponse(409, { error: 'busy', code: 'assistant_busy' }))

    await expect(service.ask(request({ requestId: 'r1' }), sink)).rejects.toMatchObject({ code: 'BUSINESS_RULE' })
    expect(service.cancel('r1')).toBe(false)
    await expect(service.ask(request({ requestId: 'r2' }), sink)).rejects.toMatchObject({ code: 'BUSINESS_RULE' })

    expect(fetch).toHaveBeenCalledTimes(2)
    expect(sleep).not.toHaveBeenCalled()
  })

  it('sink 가 던지면 연결을 끊고 더 이상 밀지 않는다', async () => {
    const { fetch, service } = setup(async () => sseResponse(['event:meta\ndata:{}\n\nevent:delta\ndata:{"text": "a"}\n\n'], true))
    const sink = vi.fn(() => {
      throw new Error('window destroyed')
    })

    await service.ask(request(), sink)
    await flush()

    const [, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect((init.signal as AbortSignal).aborted).toBe(true)
    expect(sink).toHaveBeenCalledTimes(1)
  })

  it('429 는 BUSINESS_RULE 과 reset_at 을 details 로 넘긴다', async () => {
    const { service, sink } = setup(async () =>
      jsonResponse(429, { error: '오늘 질문 횟수를 모두 썼습니다.', code: 'daily_limit_exceeded', reset_at: '2026-10-07T15:00:00Z' }),
    )

    const error = await service.ask(request(), sink).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(IpcError)
    expect((error as IpcError).code).toBe('BUSINESS_RULE')
    expect((error as IpcError).details).toEqual({
      status: 429, code: 'daily_limit_exceeded', message: '오늘 질문 횟수를 모두 썼습니다.', resetAt: '2026-10-07T15:00:00Z',
    })
  })

  it.each([
    [400, 'VALIDATION'],
    [404, 'BUSINESS_RULE'],
    [503, 'BACKEND_5XX'],
    [418, 'UNKNOWN'],
  ])('상태 %i 는 %s', async (status, code) => {
    const { service, sink } = setup(async () => jsonResponse(status, { error: 'x', code: 'c' }))
    await expect(service.ask(request(), sink)).rejects.toMatchObject({ code })
  })

  it('연결 실패는 NETWORK', async () => {
    const { service, sink } = setup(async () => {
      throw new TypeError('fetch failed')
    })
    await expect(service.ask(request(), sink)).rejects.toMatchObject({ code: 'NETWORK' })
  })

  it('취소 직후의 409 assistant_busy 는 잠시 기다렸다 다시 보낸다', async () => {
    let time = 1_000_000
    const busy = () => jsonResponse(409, { error: 'busy', code: 'assistant_busy' })
    const responses = [sseResponse(['event:meta\ndata:{}\n\n'], true), busy(), busy(), sseResponse(['event:done\ndata:{}\n\n'])]
    const { fetch, sleep, service, sink } = setup(async () => responses.shift() as Response, () => time)

    await service.ask(request({ requestId: 'r1' }), sink)
    time += 1_000
    await service.ask(request({ requestId: 'r2' }), sink)

    expect(fetch).toHaveBeenCalledTimes(4)
    expect(sleep).toHaveBeenCalledTimes(2)
  })

  it('최근 취소가 없으면 409 를 바로 거절로 돌려준다', async () => {
    const { fetch, sleep, service, sink } = setup(async () => jsonResponse(409, { error: 'busy', code: 'assistant_busy' }))

    await expect(service.ask(request(), sink)).rejects.toMatchObject({ code: 'BUSINESS_RULE' })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(sleep).not.toHaveBeenCalled()
  })

  it('취소하면 연결을 끊고 더 이상 이벤트를 밀지 않는다(끊김 오류도 없음)', async () => {
    const { fetch, service, events, sink } = setup(async () => sseResponse(['event:meta\ndata:{}\n\n'], true))

    await service.ask(request(), sink)
    await flush()
    expect(service.cancel('r1')).toBe(true)
    await flush()

    const [, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect((init.signal as AbortSignal).aborted).toBe(true)
    expect(events.map((e) => e.type)).toEqual(['meta'])
    expect(service.cancel('r1')).toBe(false)
  })

  it('새 질문은 진행 중인 이전 질문을 끊는다', async () => {
    const responses = [sseResponse(['event:meta\ndata:{}\n\n'], true), sseResponse(['event:done\ndata:{}\n\n'])]
    const { fetch, service, events, sink } = setup(async () => responses.shift() as Response)

    await service.ask(request({ requestId: 'r1' }), sink)
    await service.ask(request({ requestId: 'r2' }), sink)
    await flush()

    const [, firstInit] = fetch.mock.calls[0] as [string, RequestInit]
    expect((firstInit.signal as AbortSignal).aborted).toBe(true)
    expect(events.filter((e) => e.requestId === 'r1').map((e) => e.type)).toEqual(['meta'])
    expect(events.filter((e) => e.requestId === 'r2').map((e) => e.type)).toEqual(['done'])
  })

  it('401 인데 갱신 토큰이 없으면 갱신 없이 AUTH_EXPIRED', async () => {
    mainState.setBackendRefreshToken(null)
    const refresh = vi.spyOn(BackendClient, 'refreshSession').mockResolvedValue(undefined as never)
    const { service, sink } = setup(async () => jsonResponse(401, {}))

    await expect(service.ask(request(), sink)).rejects.toMatchObject({ code: 'AUTH_EXPIRED' })
    expect(refresh).not.toHaveBeenCalled()
  })

  it('답변이 끝난 직후의 409 assistant_busy 도 다시 시도한다', async () => {
    const busy = () => jsonResponse(409, { error: 'busy', code: 'assistant_busy' })
    const responses = [sseResponse(['event:done\ndata:{}\n\n']), busy(), sseResponse(['event:done\ndata:{}\n\n'])]
    const { fetch, sleep, service, sink } = setup(async () => responses.shift() as Response)

    await service.ask(request({ requestId: 'r1' }), sink)
    await flush()
    await service.ask(request({ requestId: 'r2' }), sink)

    expect(sleep).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('baseUrl 끝의 슬래시는 주소를 겹치게 하지 않는다', async () => {
    const { fetch, service, sink } = setup(async () => sseResponse(['event:done\ndata:{}\n\n']), undefined, { baseUrl: 'http://backend/' })

    await service.ask(request(), sink)

    expect(fetch.mock.calls[0][0]).toBe('http://backend/api/v1/assistant/ask')
  })

  it('바이트가 한동안 오지 않으면 연결을 끊고 stream_interrupted 를 한 번 민다', async () => {
    const { fetch, service, events, sink } = setup(async () => sseResponse(['event:meta\ndata:{}\n\n'], true), undefined, { idleTimeoutMs: 20 })

    await service.ask(request(), sink)
    await new Promise((resolve) => setTimeout(resolve, 80))

    const [, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect((init.signal as AbortSignal).aborted).toBe(true)
    expect(events.map((e) => e.type)).toEqual(['meta', 'error'])
    expect(events[1].data).toEqual({ code: 'stream_interrupted', message: '답변 전송이 중간에 끊겼습니다.' })
  })

  it('시간 안에 계속 바이트가 오면 끊지 않는다', async () => {
    let push: (text: string) => void = () => undefined
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        push = (text) => controller.enqueue(encoder.encode(text))
      },
    })
    const { fetch, service, events, sink } = setup(async () => new Response(body, { status: 200 }), undefined, { idleTimeoutMs: 60 })

    await service.ask(request(), sink)
    for (let i = 0; i < 4; i++) {
      await new Promise((resolve) => setTimeout(resolve, 30))
      push(':\n\n')
    }
    push('event:done\ndata:{}\n\n')
    await flush()

    const [, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect(events.map((e) => e.type)).toEqual(['done'])
    expect((init.signal as AbortSignal).aborted).toBe(true) // 끝 이벤트 뒤 정리
  })
})
