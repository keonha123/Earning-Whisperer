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
    activate: vi.fn(() => {
      instance.connected = true
    }),
    deactivate: vi.fn(async () => {
      instance.connected = false
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
  const { StompService } = await import('../StompService')
  return { StompService, mainState }
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
