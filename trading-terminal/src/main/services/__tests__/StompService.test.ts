import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// vi.mock 은 import 보다 먼저 호이스팅된다.
vi.mock('@stomp/stompjs', () => ({
  Client: vi.fn(),
}))

vi.mock('ws', () => ({
  default: class FakeWebSocket {},
}))

vi.mock('../BackendClient', () => ({
  BackendClient: {
    refreshSession: vi.fn(async () => undefined),
  },
}))

vi.mock('../NotificationService', () => ({
  NotificationService: {
    notifyWsReconnected: vi.fn(),
  },
}))

vi.mock('../PricePoller', () => ({
  markStompCovered: vi.fn(),
  clearStompCovered: vi.fn(),
}))

import { Client } from '@stomp/stompjs'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'

/** new Client({...}) 로 전달된 config 와 stub 메서드를 담는 fake 인스턴스. */
type StompCallbacks = {
  onConnect?: () => void
  onDisconnect?: () => void
  onStompError?: (frame: unknown) => void
  onWebSocketError?: (event: unknown) => void
  onWebSocketClose?: (event: unknown) => void
}

type FakeClient = StompCallbacks & {
  connected: boolean
  /** activate() 로 소켓이 열린 적이 있는지 — deactivate 의 지연 close 재현용. */
  activated: boolean
  activate: ReturnType<typeof vi.fn>
  deactivate: ReturnType<typeof vi.fn>
  subscribe: ReturnType<typeof vi.fn>
  publish: ReturnType<typeof vi.fn>
}

let clients: FakeClient[] = []

function makeFakeClient(config: StompCallbacks): FakeClient {
  const instance: FakeClient = {
    ...config,
    connected: false,
    activated: false,
    activate: vi.fn(() => {
      instance.activated = true
      instance.connected = true
    }),
    /*
     * 실제 stompjs 의 deactivate() 는 소켓이 CONNECTING/OPEN 이면 닫고, 그 close 가
     * 비동기로 해당 client 의 onWebSocketClose 를 호출한다(stomp-handler → client).
     * 교체된 옛 client 의 지연 close 콜백을 재현하기 위해 동일하게 동작시킨다.
     */
    deactivate: vi.fn(async () => {
      const wasOpen = instance.activated
      instance.activated = false
      instance.connected = false
      if (wasOpen) {
        setTimeout(() => instance.onWebSocketClose?.({ code: 1000 }), 0)
      }
    }),
    subscribe: vi.fn(() => ({ unsubscribe: vi.fn() })),
    publish: vi.fn(),
  }
  clients.push(instance)
  return instance
}

const last = (): FakeClient => clients[clients.length - 1]

/**
 * StompService 는 모듈 레벨 상태(client / retryCount / reconnectTimer)를 가지므로
 * 테스트마다 모듈 레지스트리를 리셋해 완전히 격리한다.
 */
async function loadService() {
  vi.resetModules()
  const { BackendClient } = await import('../BackendClient')
  vi.mocked(BackendClient.refreshSession).mockResolvedValue(undefined)
  const stompjs = await import('@stomp/stompjs')
  vi.mocked(stompjs.Client).mockImplementation(
    (function (config: StompCallbacks) {
      return makeFakeClient(config)
    }) as unknown as typeof Client,
  )
  const { mainState } = await import('../../store/mainState')
  mainState.setBackendToken('test-token')
  // resetModules 로 electron mock 도 새로 만들어지므로 같은 레지스트리에서 가져온다.
  const { BrowserWindow } = await import('electron')
  const { StompService } = await import('../StompService')
  return { StompService, mainState, BrowserWindow, BackendClient }
}

/** 백엔드가 인증 실패로 끊었을 때 보내는 ERROR 프레임. 서버 인터셉터의 메시지와 같아야 한다. */
const AUTH_ERROR_FRAME = { headers: { message: 'STOMP 인증 실패' } }

/** renderer 로 push 된 WS_STATUS_CHANGED 중 특정 status 만 센다. */
function countStatusPush(sendSpy: ReturnType<typeof vi.fn>, status: string): number {
  return sendSpy.mock.calls.filter(
    (c) => c[0] === IPC_CHANNELS.WS_STATUS_CHANGED && (c[1] as { status: string }).status === status,
  ).length
}

beforeEach(() => {
  clients = []
  vi.useFakeTimers()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('StompService — 소켓 종료 감지', () => {
  it('onWebSocketClose 시 DISCONNECTED 통보 + 재연결 예약', async () => {
    const { StompService } = await loadService()
    StompService.connect()
    expect(clients).toHaveLength(1)
    expect(last().onWebSocketClose).toBeTypeOf('function')

    last().connected = false
    last().onWebSocketClose!({ code: 1006 })

    // 2초 뒤 재연결 → 새 Client 생성
    vi.advanceTimersByTime(2000)
    expect(clients).toHaveLength(2)
  })

  it('의도적 disconnect() 후 onWebSocketClose 가 와도 재연결하지 않는다', async () => {
    const { StompService } = await loadService()
    StompService.connect()
    const first = last()

    StompService.disconnect()
    first.onWebSocketClose!({ code: 1000 })

    vi.advanceTimersByTime(60000)
    expect(clients).toHaveLength(1)
  })
})

describe('StompService — 재연결 중첩 방지', () => {
  it('onStompError + onWebSocketClose 가 연달아 와도 재연결은 1회만', async () => {
    const { StompService } = await loadService()
    StompService.connect()
    const first = last()
    first.connected = false

    first.onStompError!({ headers: {}, body: '' })
    first.onWebSocketClose!({ code: 1006 })

    vi.advanceTimersByTime(2000)
    expect(clients).toHaveLength(2)

    // 남은 타이머가 또 connect 하지 않는지 확인
    vi.advanceTimersByTime(60000)
    expect(clients).toHaveLength(2)
  })

  it('connect() 재호출 시 기존 client 를 deactivate 후 교체한다', async () => {
    const { StompService } = await loadService()
    StompService.connect()
    const first = last()
    first.connected = false

    StompService.connect()

    expect(first.deactivate).toHaveBeenCalledTimes(1)
    expect(clients).toHaveLength(2)
  })

  it('교체된 옛 client 의 지연 close 콜백은 무시된다', async () => {
    const { StompService, BrowserWindow } = await loadService()
    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => false, webContents: { send: sendSpy } } as never,
    ])
    StompService.connect()
    // 아직 STOMP CONNECTED 이전(CONNECTING) 상태에서 재호출 → 첫 client 가 교체된다.
    last().connected = false
    StompService.connect()

    // 교체된 첫 client 의 소켓 close 가 뒤늦게 도착해도 유령 이벤트가 없어야 한다.
    vi.advanceTimersByTime(60000)

    expect(clients).toHaveLength(2)
    expect(countStatusPush(sendSpy, 'DISCONNECTED')).toBe(0)
  })

  it('재연결 지연은 2s→4s→8s→16s→30s 로 증가하고 30s 에서 고정된다', async () => {
    const { StompService } = await loadService()
    StompService.connect()

    const delays = [2000, 4000, 8000, 16000, 30000, 30000]
    for (let i = 0; i < delays.length; i++) {
      const current = last()
      current.connected = false
      current.onWebSocketClose!({ code: 1006 })

      // 지연 직전에는 재연결되지 않는다
      vi.advanceTimersByTime(delays[i] - 1)
      expect(clients).toHaveLength(i + 1)

      vi.advanceTimersByTime(1)
      expect(clients).toHaveLength(i + 2)
    }
  })
})

describe('StompService — 인증 실패 후 재연결', () => {
  /*
   * 액세스 토큰 수명은 15분이다. 서버가 만료된 토큰의 연결을 거부하게 된 뒤로는,
   * 갱신 없이 재연결하면 같은 토큰으로 영원히 거부당한다. REST 의 401 재시도 경로는
   * STOMP ERROR 프레임을 보지 못하므로 StompService 가 직접 갱신해야 한다.
   */
  it('인증 실패 ERROR 프레임을 받으면 토큰을 갱신하고 지연 없이 재연결한다', async () => {
    const { StompService, BackendClient } = await loadService()
    StompService.connect()

    last().connected = false
    last().onStompError!(AUTH_ERROR_FRAME)

    /*
     * 타이머를 전진시키지 않고 마이크로태스크만 비운다. vi.waitFor 는 fake timer 가 켜져
     * 있으면 폴링마다 타이머를 전진시키므로, 그걸 쓰면 백오프를 거쳐 재연결해도 통과한다.
     */
    await Promise.resolve()
    await Promise.resolve()

    expect(BackendClient.refreshSession).toHaveBeenCalledTimes(1)
    // 타이머를 전혀 전진시키지 않았는데 새 client 가 생겼다 = 백오프를 거치지 않았다
    expect(clients).toHaveLength(2)
  })

  it('갱신한 토큰으로도 거부당하면 갱신을 반복하지 않고 백오프로 넘어간다', async () => {
    /*
     * refreshSession 성공은 refresh token 이 멀쩡하다는 뜻일 뿐, 새 액세스 토큰이 통과한다는
     * 보장이 아니다. 서버 비밀키가 바뀌었거나 시계가 어긋나면 갱신한 토큰도 거부되는데,
     * 그때마다 다시 갱신하면 지연 없는 재연결이 계속 돌아 자기 백엔드를 두드린다.
     */
    const { StompService, BackendClient } = await loadService()
    StompService.connect()

    last().connected = false
    last().onStompError!(AUTH_ERROR_FRAME)
    await Promise.resolve()
    await Promise.resolve()
    expect(clients).toHaveLength(2)

    // 갱신한 토큰으로 붙은 두 번째 연결도 거부당한다
    last().connected = false
    last().onStompError!(AUTH_ERROR_FRAME)
    await Promise.resolve()
    await Promise.resolve()

    expect(BackendClient.refreshSession).toHaveBeenCalledTimes(1)
    expect(clients).toHaveLength(2)

    // 백오프로 넘어가 2초 뒤에 붙는다
    vi.advanceTimersByTime(2000)
    expect(clients).toHaveLength(3)
  })

  it('연결에 성공하면 다음 인증 실패에서 다시 갱신한다', async () => {
    const { StompService, BackendClient } = await loadService()
    StompService.connect()

    last().connected = false
    last().onStompError!(AUTH_ERROR_FRAME)
    await Promise.resolve()
    await Promise.resolve()

    // 갱신한 토큰으로 연결에 성공했다
    last().onConnect!()

    last().connected = false
    last().onStompError!(AUTH_ERROR_FRAME)
    await Promise.resolve()
    await Promise.resolve()

    expect(BackendClient.refreshSession).toHaveBeenCalledTimes(2)
  })

  it('인증 실패가 아닌 에러는 토큰을 갱신하지 않고 기존 백오프로 재연결한다', async () => {
    const { StompService, BackendClient } = await loadService()
    StompService.connect()

    last().connected = false
    last().onStompError!({ headers: { message: 'destination 을 찾을 수 없습니다' } })

    expect(BackendClient.refreshSession).not.toHaveBeenCalled()
    vi.advanceTimersByTime(2000)
    expect(clients).toHaveLength(2)
  })

  it('토큰 갱신이 실패하면 백오프로 돌아가고 즉시 재연결하지 않는다', async () => {
    const { StompService, BackendClient } = await loadService()
    vi.mocked(BackendClient.refreshSession).mockRejectedValue(new Error('일시적 실패'))
    StompService.connect()

    last().connected = false
    last().onStompError!(AUTH_ERROR_FRAME)

    // 거부 핸들러까지 실행된 뒤에 확인한다. 안 그러면 "아직 아무 일도 안 일어났다" 를 단정한다
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
    expect(BackendClient.refreshSession).toHaveBeenCalled()
    expect(clients).toHaveLength(1)

    vi.advanceTimersByTime(2000)
    expect(clients).toHaveLength(2)
  })

  it('갱신이 최종 실패해 세션이 끝나면 재연결하지 않고 DISCONNECTED 로 끝난다', async () => {
    const { StompService, mainState, BackendClient, BrowserWindow } = await loadService()
    // refresh token 이 무효면 BackendClient 가 세션을 정리해 backendToken 을 비운다
    vi.mocked(BackendClient.refreshSession).mockImplementation(async () => {
      mainState.setBackendToken(null)
      throw new Error('refresh token 무효')
    })
    const sendSpy = vi.mocked(BrowserWindow.getAllWindows()[0].webContents.send)
    StompService.connect()
    sendSpy.mockClear()

    last().connected = false
    last().onStompError!(AUTH_ERROR_FRAME)
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()

    // 다시 붙지 않는데 화면만 재연결 중으로 남으면 안 된다
    expect(countStatusPush(sendSpy, 'RECONNECTING')).toBe(0)
    expect(countStatusPush(sendSpy, 'DISCONNECTED')).toBeGreaterThan(0)
    vi.advanceTimersByTime(60000)
    expect(clients).toHaveLength(1)
  })
})

describe('paired transcript translation subscriptions', () => {
  it('relays translation payloads and restores both subscriptions after socket loss', async () => {
    const { StompService, BrowserWindow } = await loadService()
    const send = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => false, webContents: { send } } as never,
    ])
    StompService.connect()
    last().onConnect?.()
    StompService.subscribeTranscript('NVDA')
    const payload = { ticker: 'NVDA', call_id: 'call', sequences: [1, 2], text_ko: '번역' }
    last().subscribe.mock.calls.find(c => c[0] === '/topic/transcript-translation/NVDA')![1]({ body: JSON.stringify(payload) })
    expect(send).toHaveBeenCalledWith(IPC_CHANNELS.TRANSCRIPT_TRANSLATION_RECEIVED, payload)
    last().connected = false
    last().onWebSocketClose?.({ code: 1006 })
    vi.advanceTimersByTime(2000)
    last().onConnect?.()
    expect(last().subscribe.mock.calls.map(c => c[0])).toEqual(expect.arrayContaining([
      '/topic/transcript/NVDA', '/topic/transcript-translation/NVDA',
    ]))
  })
  it('subscribes and unsubscribes both topics and reconnects the pair', async () => {
    const { StompService } = await loadService()
    StompService.subscribeTranscript('NVDA')
    StompService.connect()
    last().onConnect?.()
    const original = last().subscribe.mock.calls.find(c => c[0] === '/topic/transcript/NVDA')
    const translated = last().subscribe.mock.calls.find(c => c[0] === '/topic/transcript-translation/NVDA')
    expect(original).toBeDefined()
    expect(translated).toBeDefined()
    const handles = last().subscribe.mock.results.map(r => r.value)
    StompService.unsubscribeTranscript('NVDA')
    expect(handles.filter(h => h.unsubscribe.mock.calls.length === 1)).toHaveLength(2)
    StompService.disconnect()
    StompService.connect()
    last().onConnect?.()
    expect(last().subscribe.mock.calls.some(c => c[0].includes('/transcript'))).toBe(false)
  })
})
