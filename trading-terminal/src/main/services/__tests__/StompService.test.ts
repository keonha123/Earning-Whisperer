import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// vi.mock 은 import 보다 먼저 호이스팅된다.
vi.mock('@stomp/stompjs', () => ({
  Client: vi.fn(),
}))

vi.mock('ws', () => ({
  default: class FakeWebSocket {},
}))

vi.mock('../TradeExecutor', () => ({
  TradeExecutor: {
    execute: vi.fn(async () => undefined),
  },
}))

vi.mock('../BackendClient', () => ({
  BackendClient: {
    fetchPendingTrades: vi.fn(async () => []),
  },
}))

vi.mock('../NotificationService', () => ({
  NotificationService: {
    notifyWsDisconnected: vi.fn(),
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
  return { StompService, mainState, BrowserWindow }
}

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

  it('onWebSocketClose 는 MANUAL 강제 전환을 유발한다', async () => {
    const { StompService, mainState } = await loadService()
    mainState.setTradingMode('AUTO_PILOT')
    StompService.connect()

    last().connected = false
    last().onWebSocketClose!({ code: 1006 })

    expect(mainState.tradingMode).toBe('MANUAL')
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
    const { StompService, mainState, BrowserWindow } = await loadService()
    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => false, webContents: { send: sendSpy } } as never,
    ])
    mainState.setTradingMode('AUTO_PILOT')

    StompService.connect()
    // 아직 STOMP CONNECTED 이전(CONNECTING) 상태에서 재호출 → 첫 client 가 교체된다.
    last().connected = false
    StompService.connect()

    // 교체된 첫 client 의 소켓 close 가 뒤늦게 도착해도 유령 이벤트가 없어야 한다.
    vi.advanceTimersByTime(60000)

    expect(clients).toHaveLength(2)
    expect(mainState.tradingMode).toBe('AUTO_PILOT')
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
