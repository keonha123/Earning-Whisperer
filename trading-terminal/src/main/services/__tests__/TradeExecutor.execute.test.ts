import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// vi.mock은 import보다 먼저 호출되도록 호이스팅된다.
vi.mock('../KisService', () => ({
  KisService: {
    getBalance: vi.fn(),
    getCurrentPrice: vi.fn(),
    placeOrder: vi.fn(),
  },
}))

vi.mock('../BackendClient', () => ({
  BackendClient: {
    sendCallback: vi.fn(),
    syncPortfolio: vi.fn(),
  },
}))

vi.mock('../NotificationService', () => ({
  NotificationService: {
    notifyTradeExecuted: vi.fn(),
    notifyTradeFailed: vi.fn(),
  },
}))

import { BrowserWindow } from 'electron'
import { TradeExecutor, type TradeSignal } from '../TradeExecutor'
import { KisService } from '../KisService'
import { BackendClient } from '../BackendClient'
import { NotificationService } from '../NotificationService'
import { mainState } from '../../store/mainState'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'

const Kis = vi.mocked(KisService)
const Backend = vi.mocked(BackendClient)
const Notify = vi.mocked(NotificationService)

function buySignal(overrides: Partial<TradeSignal> = {}): TradeSignal {
  return {
    trade_id: 'trade-1',
    action: 'BUY',
    order_ratio: 0.1,
    ticker: 'TSLA',
    ai_score: 0.85,
    ...overrides,
  }
}

function sellSignal(overrides: Partial<TradeSignal> = {}): TradeSignal {
  return {
    trade_id: 'trade-2',
    action: 'SELL',
    order_ratio: 0.5,
    ticker: 'TSLA',
    ai_score: 0.15,
    ...overrides,
  }
}

beforeEach(() => {
  // mainState는 모듈 싱글톤 — 각 테스트 시작 시 초기화
  mainState.clear()
})

afterEach(() => {
  // 잠재적 타이머 누수 방지 (mainState.setKisAccessToken은 timer를 만들지 않지만 안전 차원)
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('TradeExecutor.execute — BUY 정상 흐름', () => {
  it('잔고/현재가 조회 → 수량 산출 → placeOrder → EXECUTED 콜백', async () => {
    Kis.getBalance.mockResolvedValue({
      orderableCash: 1000,
      totalCash: 1000,
      holdings: [],
    })
    Kis.getCurrentPrice.mockResolvedValue(10)
    Kis.placeOrder.mockResolvedValue({
      orderId: 'ODNO123',
      executedPrice: null,
      executedQty: 10,
    })
    Backend.sendCallback.mockResolvedValue(undefined)
    Backend.syncPortfolio.mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(result.status).toBe('EXECUTED')
    expect(result.tradeId).toBe('trade-1')
    expect(result.orderId).toBe('ODNO123')
    expect(result.executedQty).toBe(10)
    expect(result.errorMessage).toBeNull()

    // placeOrder 호출 인자 검증
    expect(Kis.placeOrder).toHaveBeenCalledTimes(1)
    expect(Kis.placeOrder).toHaveBeenCalledWith('BUY', 'TSLA', 10)

    // EXECUTED 콜백 페이로드 검증
    expect(Backend.sendCallback).toHaveBeenCalledWith('trade-1', {
      status: 'EXECUTED',
      broker_order_id: 'ODNO123',
      executed_price: null,
      executed_qty: 10,
      error_message: null,
    })

    expect(Notify.notifyTradeExecuted).toHaveBeenCalledWith('TSLA', 'BUY', 10, null)
  })

  it('TRADE_EXECUTED IPC 이벤트 발화', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue(10)
    Kis.placeOrder.mockResolvedValue({ orderId: 'X', executedPrice: null, executedQty: 10 })
    Backend.sendCallback.mockResolvedValue(undefined)

    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValueOnce([
      { isDestroyed: () => false, webContents: { send: sendSpy } },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any)

    await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(sendSpy).toHaveBeenCalledWith(
      IPC_CHANNELS.TRADE_EXECUTED,
      expect.objectContaining({ status: 'EXECUTED', orderId: 'X' }),
    )
  })
})

describe('TradeExecutor.execute — qty=0 결과', () => {
  it('placeOrder 미호출 + FAILED 콜백 + 사유 메시지 포함', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 100, totalCash: 100, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue(200) // 100 × 0.05 / 200 = 0.025 → 0주
    Backend.sendCallback.mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.05 }))

    expect(result.status).toBe('FAILED')
    expect(result.executedQty).toBe(0)
    expect(result.errorMessage).toContain('1주 가격')
    expect(Kis.placeOrder).not.toHaveBeenCalled()

    expect(Backend.sendCallback).toHaveBeenCalledWith('trade-1', {
      status: 'FAILED',
      broker_order_id: null,
      executed_price: null,
      executed_qty: 0,
      error_message: expect.stringContaining('1주 가격'),
    })
  })
})

describe('TradeExecutor.execute — 동시 호출 차단', () => {
  it('mainState.isOrderInProgress=true일 때 즉시 FAILED 반환', async () => {
    mainState.setOrderInProgress(true)

    const result = await TradeExecutor.execute(buySignal())

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('이미 주문이 진행 중')
    expect(Kis.getBalance).not.toHaveBeenCalled()
    expect(Kis.placeOrder).not.toHaveBeenCalled()
  })

  it('차단된 호출은 isOrderInProgress 플래그를 false로 덮어쓰지 않는다', async () => {
    // TradeExecutor.execute의 early return은 try 블록 바깥이므로
    // finally의 setOrderInProgress(false)를 거치지 않는다 → 락은 안전하게 유지된다.
    mainState.setOrderInProgress(true)
    const result = await TradeExecutor.execute(buySignal())
    expect(result.status).toBe('FAILED')
    expect(mainState.isOrderInProgress).toBe(true) // 차단된 호출은 락을 풀지 않아야 한다
    expect(Kis.getBalance).not.toHaveBeenCalled() // 진입 자체를 막아야 한다
  })
})

describe('TradeExecutor.execute — 예외 처리', () => {
  it('placeOrder 예외 시 catch에서 FAILED 콜백', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue(10)
    Kis.placeOrder.mockRejectedValue(new Error('KIS 서버 500'))
    Backend.sendCallback.mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toBe('KIS 서버 500')
    expect(Backend.sendCallback).toHaveBeenCalledWith('trade-1', expect.objectContaining({
      status: 'FAILED',
      error_message: 'KIS 서버 500',
    }))
  })

  it('finally 락 해제: 예외 발생 후 isOrderInProgress=false', async () => {
    Kis.getBalance.mockRejectedValue(new Error('잔고 조회 실패'))
    Backend.sendCallback.mockResolvedValue(undefined)

    await TradeExecutor.execute(buySignal())

    expect(mainState.isOrderInProgress).toBe(false)
  })

  it('finally 락 해제: 정상 흐름에서도 isOrderInProgress=false', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue(10)
    Kis.placeOrder.mockResolvedValue({ orderId: 'X', executedPrice: null, executedQty: 10 })
    Backend.sendCallback.mockResolvedValue(undefined)

    await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(mainState.isOrderInProgress).toBe(false)
  })

  it('콜백 실패해도 결과 반환 (FAILED 경로)', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 0, totalCash: 0, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue(10)
    Backend.sendCallback.mockRejectedValue(new Error('백엔드 다운'))

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    // qty=0이라 sendFailCallback 진입 → 콜백이 실패해도 결과를 반환해야 함
    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toBe('예수금 부족')
  })

  it('EXECUTED 흐름에서 BackendClient.sendCallback이 실패하면 catch 경로로 빠져 FAILED로 보고된다', async () => {
    // KisService mock: 정상 잔고/현재가/주문
    Kis.getBalance.mockResolvedValueOnce({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue(10)
    Kis.placeOrder.mockResolvedValue({ orderId: 'X', executedPrice: null, executedQty: 10 })
    // 첫 sendCallback(EXECUTED용)은 throw → catch로 빠짐
    // 이후 sendFailCallback 내부에서 두 번째 sendCallback(FAILED 보고용) 호출은 성공
    Backend.sendCallback
      .mockRejectedValueOnce(new Error('백엔드 다운'))
      .mockResolvedValueOnce(undefined)

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('백엔드 다운')
    // EXECUTED 시도 1회 + FAILED 보고 1회 = 2회
    expect(Backend.sendCallback).toHaveBeenCalledTimes(2)
    expect(Backend.sendCallback).toHaveBeenNthCalledWith(
      1,
      'trade-1',
      expect.objectContaining({ status: 'EXECUTED' }),
    )
    expect(Backend.sendCallback).toHaveBeenNthCalledWith(
      2,
      'trade-1',
      expect.objectContaining({ status: 'FAILED', error_message: '백엔드 다운' }),
    )
    // 주문 자체는 EXECUTED 됐으므로 placeOrder는 호출됐어야 함
    expect(Kis.placeOrder).toHaveBeenCalledWith('BUY', 'TSLA', 10)
  })
})

describe('TradeExecutor.execute — SELL 흐름', () => {
  it('SELL은 현재가 조회를 호출하지 않는다', async () => {
    Kis.getBalance.mockResolvedValue({
      orderableCash: 0,
      totalCash: 0,
      holdings: [
        { ticker: 'TSLA', qty: 10, avgPrice: 200, currentPrice: 240 },
      ],
    })
    Kis.placeOrder.mockResolvedValue({
      orderId: 'SELL_OD',
      executedPrice: null,
      executedQty: 5,
    })
    Backend.sendCallback.mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(sellSignal({ order_ratio: 0.5 }))

    expect(result.status).toBe('EXECUTED')
    expect(result.executedQty).toBe(5)
    expect(Kis.getCurrentPrice).not.toHaveBeenCalled()
    expect(Kis.placeOrder).toHaveBeenCalledWith('SELL', 'TSLA', 5)
  })

  it('SELL: 미보유 종목 → FAILED + 사유 "보유 수량 없음"', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 0, totalCash: 0, holdings: [] })
    Backend.sendCallback.mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(sellSignal())

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toBe('보유 수량 없음')
    expect(Kis.placeOrder).not.toHaveBeenCalled()
  })
})
