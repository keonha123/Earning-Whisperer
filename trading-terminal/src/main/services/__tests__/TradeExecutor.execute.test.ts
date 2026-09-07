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
import { flushMicrotasks } from '../../../test/setup'

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
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
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

  it('EXECUTED 후 포트폴리오 동기화가 백엔드 계약대로 { cash_balance, positions } 로 호출된다', async () => {
    Kis.getBalance.mockResolvedValue({
      orderableCash: 1000,
      totalCash: 1234,
      holdings: [{ ticker: 'TSLA', qty: 7, avgPrice: 250.5, currentPrice: 260 }],
    })
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
    Kis.placeOrder.mockResolvedValue({
      orderId: 'ODNO123',
      executedPrice: null,
      executedQty: 10,
    })
    Backend.sendCallback.mockResolvedValue(undefined)
    Backend.syncPortfolio.mockResolvedValue(undefined)

    await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))
    await flushMicrotasks()

    expect(Backend.syncPortfolio).toHaveBeenCalledWith({
      cash_balance: 1234,
      positions: [{ ticker: 'TSLA', quantity: 7, avg_price: 250.5 }],
    })
  })

  it('TRADE_EXECUTED IPC 이벤트 발화', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
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
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 200, previousClose: 200 }) // 100 × 0.05 / 200 = 0.025 → 0주
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
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
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
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
    Kis.placeOrder.mockResolvedValue({ orderId: 'X', executedPrice: null, executedQty: 10 })
    Backend.sendCallback.mockResolvedValue(undefined)

    await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(mainState.isOrderInProgress).toBe(false)
  })

  it('콜백 실패해도 결과 반환 (FAILED 경로)', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 0, totalCash: 0, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
    Backend.sendCallback.mockRejectedValue(new Error('백엔드 다운'))

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    // qty=0이라 sendFailCallback 진입 → 콜백이 실패해도 결과를 반환해야 함
    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toBe('예수금 부족')
  })

  it('체결 후 sendCallback이 1회 실패해도 재시도로 EXECUTED가 전달되고 FAILED로 뒤집지 않는다', async () => {
    vi.useFakeTimers()
    // KisService mock: 정상 잔고/현재가/주문
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
    Kis.placeOrder.mockResolvedValue({ orderId: 'X', executedPrice: null, executedQty: 10 })
    // 1회차 EXECUTED 콜백은 throw → 1s 뒤 재시도에서 성공
    Backend.sendCallback
      .mockRejectedValueOnce(new Error('백엔드 400'))
      .mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(result.status).toBe('EXECUTED')
    expect(result.orderId).toBe('X')

    await vi.advanceTimersByTimeAsync(1000)
    await flushMicrotasks()

    expect(Backend.sendCallback).toHaveBeenCalledTimes(2)
    // 두 번 모두 EXECUTED — FAILED 콜백은 절대 나가면 안 된다
    expect(Backend.sendCallback).toHaveBeenNthCalledWith(
      1,
      'trade-1',
      expect.objectContaining({ status: 'EXECUTED' }),
    )
    expect(Backend.sendCallback).toHaveBeenNthCalledWith(
      2,
      'trade-1',
      expect.objectContaining({ status: 'EXECUTED', broker_order_id: 'X' }),
    )
    expect(Backend.sendCallback).not.toHaveBeenCalledWith(
      'trade-1',
      expect.objectContaining({ status: 'FAILED' }),
    )
    expect(Kis.placeOrder).toHaveBeenCalledWith('BUY', 'TSLA', 10)
  })

  it('체결 후 sendCallback이 계속 실패하면 FAILED 콜백 없이 CALLBACK_FAILED로 통보한다', async () => {
    vi.useFakeTimers()
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
    // ODNO 미반환 케이스 — 백엔드가 blank broker_order_id를 400으로 거부하는 상황 재현
    Kis.placeOrder.mockResolvedValue({ orderId: '', executedPrice: null, executedQty: 10 })
    Backend.sendCallback.mockRejectedValue(new Error('백엔드 400'))

    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => false, webContents: { send: sendSpy } },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any)

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(result.status).toBe('EXECUTED')

    // 1s + 2s + 4s 백오프 재시도까지 모두 소진
    await vi.advanceTimersByTimeAsync(7000)
    await flushMicrotasks()

    // 최초 1회 + 1s·2s·4s 재시도 3회 = 4회 전송 시도
    expect(Backend.sendCallback).toHaveBeenCalledTimes(4)
    // FAILED 콜백은 단 한 번도 나가지 않아야 한다
    expect(Backend.sendCallback).not.toHaveBeenCalledWith(
      'trade-1',
      expect.objectContaining({ status: 'FAILED' }),
    )
    expect(Notify.notifyTradeFailed).not.toHaveBeenCalled()

    // 렌더러에는 기존 TRADE_FAILED 채널로 CALLBACK_FAILED 사유를 통보
    expect(sendSpy).toHaveBeenCalledWith(
      IPC_CHANNELS.TRADE_FAILED,
      expect.objectContaining({ tradeId: 'trade-1', reason: 'CALLBACK_FAILED' }),
    )
  })
})

describe('TradeExecutor.execute — 진행 중 신호 통보', () => {
  it('주문 진행 중 두 번째 신호는 FAILED 콜백 + TRADE_FAILED push로 통보된다', async () => {
    mainState.setOrderInProgress(true)
    Backend.sendCallback.mockResolvedValue(undefined)

    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => false, webContents: { send: sendSpy } },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any)

    const result = await TradeExecutor.execute(buySignal({ trade_id: 'trade-9' }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('주문이 진행 중')
    expect(Backend.sendCallback).toHaveBeenCalledWith(
      'trade-9',
      expect.objectContaining({ status: 'FAILED' }),
    )
    expect(sendSpy).toHaveBeenCalledWith(
      IPC_CHANNELS.TRADE_FAILED,
      expect.objectContaining({ tradeId: 'trade-9', status: 'FAILED' }),
    )
    // 첫 주문은 영향 없음 — 락 유지 + 주문 API 미호출
    expect(mainState.isOrderInProgress).toBe(true)
    expect(Kis.getBalance).not.toHaveBeenCalled()
    expect(Kis.placeOrder).not.toHaveBeenCalled()
  })

  it('signal이 undefined면 진행 중이어도 TypeError 없이 검증 실패로 처리된다', async () => {
    mainState.setOrderInProgress(true)
    Backend.sendCallback.mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(undefined as unknown as TradeSignal)

    expect(result.status).toBe('FAILED')
    expect(result.tradeId).toBe('invalid')
    expect(result.errorMessage).toContain('시그널 페이로드 없음')
    expect(Kis.placeOrder).not.toHaveBeenCalled()
  })
})

describe('TradeExecutor.execute — KIS rt_cd 실패 통합', () => {
  it('placeOrder가 KIS rt_cd 실패로 throw하면 FAILED 콜백 + errorMessage에 msg1 포함', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
    // KIS가 rt_cd='1'로 거부 → KisService.placeOrder가 throw
    Kis.placeOrder.mockRejectedValue(
      new Error('KIS 주문 거부: 주문가능금액이 부족합니다.'),
    )
    Backend.sendCallback.mockResolvedValue(undefined)

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('주문가능금액이 부족')
    expect(result.errorMessage).toContain('KIS 주문 거부')
    expect(Backend.sendCallback).toHaveBeenCalledWith(
      'trade-1',
      expect.objectContaining({
        status: 'FAILED',
        error_message: expect.stringContaining('주문가능금액이 부족'),
      }),
    )
    expect(Notify.notifyTradeFailed).toHaveBeenCalled()
  })
})

describe('TradeExecutor.execute — 시그널 검증 (validateSignal)', () => {
  beforeEach(() => {
    Backend.sendCallback.mockResolvedValue(undefined)
  })

  it('action이 BUY/SELL이 아니면 즉시 FAILED, KisService 호출되지 않음', async () => {
    const result = await TradeExecutor.execute(
      buySignal({ action: 'HOLD' as unknown as 'BUY' }),
    )

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 action')
    expect(Kis.getBalance).not.toHaveBeenCalled()
    expect(Kis.placeOrder).not.toHaveBeenCalled()
    expect(Backend.sendCallback).toHaveBeenCalledWith(
      'trade-1',
      expect.objectContaining({ status: 'FAILED', error_message: expect.stringContaining('비정상 action') }),
    )
    expect(Notify.notifyTradeFailed).toHaveBeenCalled()
  })

  it('ticker가 빈 문자열이면 즉시 FAILED', async () => {
    const result = await TradeExecutor.execute(buySignal({ ticker: '' }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 ticker')
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('ticker가 공백만 있는 문자열이면 즉시 FAILED', async () => {
    const result = await TradeExecutor.execute(buySignal({ ticker: '   ' }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 ticker')
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('trade_id가 빈 문자열이면 fallback id로 콜백 전송', async () => {
    const result = await TradeExecutor.execute(buySignal({ trade_id: '' }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 trade_id')
    // 빈 trade_id → 'invalid' fallback id로 콜백
    expect(Backend.sendCallback).toHaveBeenCalledWith(
      'invalid',
      expect.objectContaining({ status: 'FAILED' }),
    )
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('order_ratio가 NaN이면 즉시 FAILED', async () => {
    const result = await TradeExecutor.execute(buySignal({ order_ratio: NaN }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 order_ratio')
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('order_ratio가 Infinity이면 즉시 FAILED', async () => {
    const result = await TradeExecutor.execute(buySignal({ order_ratio: Infinity }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 order_ratio')
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('order_ratio가 0이면 즉시 FAILED', async () => {
    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0 }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 order_ratio')
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('order_ratio가 1.01이면 즉시 FAILED (calcQty의 (0,1] 정책과 일관)', async () => {
    const result = await TradeExecutor.execute(buySignal({ order_ratio: 1.01 }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 order_ratio')
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('order_ratio가 음수이면 즉시 FAILED', async () => {
    const result = await TradeExecutor.execute(buySignal({ order_ratio: -0.5 }))

    expect(result.status).toBe('FAILED')
    expect(result.errorMessage).toContain('비정상 order_ratio')
    expect(Kis.getBalance).not.toHaveBeenCalled()
  })

  it('정상 시그널은 검증 통과 — KisService.getBalance 호출됨 (회귀 보호)', async () => {
    Kis.getBalance.mockResolvedValue({ orderableCash: 1000, totalCash: 1000, holdings: [] })
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 10, previousClose: 10 })
    Kis.placeOrder.mockResolvedValue({ orderId: 'OK', executedPrice: null, executedQty: 10 })

    const result = await TradeExecutor.execute(buySignal({ order_ratio: 0.1 }))

    expect(result.status).toBe('EXECUTED')
    expect(Kis.getBalance).toHaveBeenCalled()
    expect(Kis.placeOrder).toHaveBeenCalledWith('BUY', 'TSLA', 10)
  })

  it('TRADE_FAILED IPC 이벤트 발화 (validateSignal 실패 경로)', async () => {
    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValueOnce([
      { isDestroyed: () => false, webContents: { send: sendSpy } },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any)

    await TradeExecutor.execute(buySignal({ order_ratio: NaN }))

    expect(sendSpy).toHaveBeenCalledWith(
      IPC_CHANNELS.TRADE_FAILED,
      expect.objectContaining({
        status: 'FAILED',
        errorMessage: expect.stringContaining('비정상 order_ratio'),
      }),
    )
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
