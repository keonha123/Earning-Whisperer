import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain, BrowserWindow } from 'electron'

// KIS 체결통보 → 미체결 재확인 → Trading Room 주문 패널 알림 경로를 검증한다.
vi.mock('../../services/KisService', () => ({
  KisService: {
    inquireFill: vi.fn(),
    getCurrentPrice: vi.fn(),
    placeOrder: vi.fn(),
    getBalance: vi.fn().mockRejectedValue(new Error('테스트에서 미사용')),
  },
}))
vi.mock('../../services/BackendClient', () => ({
  BackendClient: {
    getTrades: vi.fn(),
    sendCallback: vi.fn().mockResolvedValue(undefined),
    recordManualTrade: vi.fn().mockResolvedValue(undefined),
    syncPortfolio: vi.fn().mockResolvedValue(undefined),
    getAssetHistory: vi.fn().mockResolvedValue([]),
  },
}))

import { registerKisHandlers, onFillNotice, __resetRecentNoticesForTest } from '../kisHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { mainState } from '../../store/mainState'
import { KisService } from '../../services/KisService'
import { BackendClient } from '../../services/BackendClient'

const Kis = KisService as unknown as {
  inquireFill: ReturnType<typeof vi.fn>
  placeOrder: ReturnType<typeof vi.fn>
}
const Backend = BackendClient as unknown as {
  getTrades: ReturnType<typeof vi.fn>
  sendCallback: ReturnType<typeof vi.fn>
  recordManualTrade: ReturnType<typeof vi.fn>
}

const send = vi.fn()

function notice(orderId = '0000044600') {
  return { orderId, ticker: 'WMT', executedQty: 2, executedPrice: 99.5 }
}

function reconciledPushes() {
  return send.mock.calls.filter((c) => c[0] === IPC_CHANNELS.TRADES_RECONCILED)
}

function placeManualOrder() {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find((c) => c[0] === IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER)
  if (!call) throw new Error('채널 미등록')
  return (call[1] as (e: unknown, payload: unknown) => Promise<unknown>)({}, {
    side: 'BUY',
    ticker: 'WMT',
    qty: 2,
    price: 100,
  })
}

/** 마이크로태스크와 타이머 없는 Promise 체인을 모두 흘려보낸다. */
async function flush() {
  for (let i = 0; i < 10; i++) await Promise.resolve()
}

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  mainState.clear()
  __resetRecentNoticesForTest()
  send.mockReset()
  vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
    { isDestroyed: () => false, webContents: { send } } as never,
  ])
  Kis.inquireFill.mockReset()
  Kis.placeOrder.mockReset()
  Backend.getTrades.mockReset()
  Backend.sendCallback.mockReset()
  Backend.sendCallback.mockResolvedValue(undefined)
  Backend.recordManualTrade.mockReset()
  Backend.recordManualTrade.mockResolvedValue(undefined)
  registerKisHandlers()
})

describe('onFillNotice — 체결통보 반영', () => {
  it('재확인으로 체결을 확정하면 화면에 확정 건수를 알린다', async () => {
    Backend.getTrades.mockResolvedValue({
      content: [{ id: 10, ticker: 'WMT', status: 'PENDING', brokerOrderId: '0000044600' }],
    })
    Kis.inquireFill.mockResolvedValue({ executedQty: 2, avgPrice: 99.5 })

    await onFillNotice(notice())

    expect(Backend.sendCallback).toHaveBeenCalledTimes(1)
    expect(reconciledPushes()).toEqual([[IPC_CHANNELS.TRADES_RECONCILED, { reconciled: 1 }]])
  })

  it('확정한 것이 없어도 알린다 — 다른 경로가 먼저 확정했으면 패널만 남아 있다', async () => {
    Backend.getTrades.mockResolvedValue({ content: [] })

    await onFillNotice(notice())

    expect(reconciledPushes()).toEqual([[IPC_CHANNELS.TRADES_RECONCILED, { reconciled: 0 }]])
  })

  it('재확인이 실패하면 알리지 않고 예외도 밖으로 내보내지 않는다', async () => {
    Backend.getTrades.mockRejectedValue(new Error('백엔드 다운'))

    await expect(onFillNotice(notice())).resolves.toBeUndefined()
    expect(reconciledPushes()).toHaveLength(0)
  })

  it('닫힌 창에는 보내지 않는다', async () => {
    const closedSend = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => true, webContents: { send: closedSend } } as never,
    ])
    Backend.getTrades.mockResolvedValue({ content: [] })

    await onFillNotice(notice())

    expect(closedSend).not.toHaveBeenCalled()
  })

  it('통보가 연달아 와도 진행 중인 재확인을 함께 기다려 백엔드 조회는 한 번이다', async () => {
    Backend.getTrades.mockResolvedValue({ content: [] })

    await Promise.all([onFillNotice(notice('0000044600')), onFillNotice(notice('0000044601'))])

    expect(Backend.getTrades).toHaveBeenCalledTimes(1)
  })
})

describe('수동 주문 기록과 체결통보의 순서 역전', () => {
  it('주문 기록보다 먼저 온 통보는 PENDING 기록이 끝난 뒤 재확인을 다시 돌린다', async () => {
    // 통보 시점에는 백엔드에 PENDING 행이 없다
    Backend.getTrades.mockResolvedValueOnce({ content: [] })
    await onFillNotice(notice('0000044600'))
    expect(Backend.sendCallback).not.toHaveBeenCalled()

    // 주문 결과는 KIS 가 앞자리 0 을 뗀 번호로 줄 수도 있다
    Kis.placeOrder.mockResolvedValue({ orderId: '44600', executedPrice: null, executedQty: 0 })
    Backend.getTrades.mockResolvedValueOnce({
      content: [{ id: 11, ticker: 'WMT', status: 'PENDING', brokerOrderId: '44600' }],
    })
    Kis.inquireFill.mockResolvedValue({ executedQty: 2, avgPrice: 99.5 })

    await placeManualOrder()
    await flush()

    expect(Backend.recordManualTrade).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'PENDING', broker_order_id: '44600' }),
    )
    expect(Backend.sendCallback).toHaveBeenCalledWith('11', expect.objectContaining({ status: 'EXECUTED' }))
    expect(reconciledPushes().at(-1)).toEqual([IPC_CHANNELS.TRADES_RECONCILED, { reconciled: 1 }])
  })

  it('통보를 받은 적 없는 PENDING 주문은 기록 뒤 재확인하지 않는다', async () => {
    Kis.placeOrder.mockResolvedValue({ orderId: '0000044700', executedPrice: null, executedQty: 0 })

    await placeManualOrder()
    await flush()

    expect(Backend.getTrades).not.toHaveBeenCalled()
    expect(reconciledPushes()).toHaveLength(0)
  })
})
