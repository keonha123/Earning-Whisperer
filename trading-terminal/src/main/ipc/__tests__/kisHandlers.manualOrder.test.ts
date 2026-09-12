import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

// KIS 해외주식 매수에는 시장가 코드가 없다. UI 의 "즉시 체결"(price=null) 이
// 0달러 지정가로 나가지 않고 현재가 기준 버퍼 지정가로 환산되는지 검증한다.
vi.mock('../../services/KisService', () => ({
  KisService: {
    getCurrentPrice: vi.fn(),
    placeOrder: vi.fn(),
    getBalance: vi.fn().mockRejectedValue(new Error('테스트에서 미사용')),
  },
}))
vi.mock('../../services/BackendClient', () => ({
  BackendClient: {
    recordManualTrade: vi.fn().mockResolvedValue(undefined),
    syncPortfolio: vi.fn().mockResolvedValue(undefined),
    getAssetHistory: vi.fn().mockResolvedValue([]),
  },
}))

import { registerKisHandlers } from '../kisHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { mainState } from '../../store/mainState'
import { KisService } from '../../services/KisService'
import { BackendClient } from '../../services/BackendClient'
import { deserializeIpcError } from '../../../lib/types/ipcError'

const Kis = KisService as unknown as {
  getCurrentPrice: ReturnType<typeof vi.fn>
  placeOrder: ReturnType<typeof vi.fn>
}
const Backend = BackendClient as unknown as {
  recordManualTrade: ReturnType<typeof vi.fn>
}

function handler() {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find(
    (c) => c[0] === IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER,
  )
  if (!call) throw new Error('채널 미등록')
  return call[1] as (e: unknown, payload: unknown) => Promise<any>
}

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  mainState.clear()
  Kis.getCurrentPrice.mockReset()
  Kis.placeOrder.mockReset()
  Backend.recordManualTrade.mockReset()
  Backend.recordManualTrade.mockResolvedValue(undefined)
  registerKisHandlers()
})

describe('KIS_PLACE_MANUAL_ORDER — 즉시 체결 지정가 환산', () => {
  it('price=null 매수는 현재가 +1% 지정가로 나간다 (0달러 아님)', async () => {
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 100, previousClose: 99 })
    Kis.placeOrder.mockResolvedValue({ orderId: 'O1', executedPrice: 101, executedQty: 2 })

    const res = await handler()({}, { side: 'BUY', ticker: 'WMT', qty: 2, price: null })

    expect(Kis.placeOrder).toHaveBeenCalledWith('BUY', 'WMT', 2, 101)
    expect(res.status).toBe('EXECUTED')
  })

  it('price=null 매도는 현재가 -1% 지정가로 나간다', async () => {
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 100, previousClose: 99 })
    Kis.placeOrder.mockResolvedValue({ orderId: 'O2', executedPrice: 99, executedQty: 1 })

    await handler()({}, { side: 'SELL', ticker: 'WMT', qty: 1, price: null })

    expect(Kis.placeOrder).toHaveBeenCalledWith('SELL', 'WMT', 1, 99)
  })

  it('명시 지정가는 그대로 전달하고 현재가를 조회하지 않는다', async () => {
    Kis.placeOrder.mockResolvedValue({ orderId: 'O3', executedPrice: 90, executedQty: 1 })

    await handler()({}, { side: 'BUY', ticker: 'WMT', qty: 1, price: 90 })

    expect(Kis.getCurrentPrice).not.toHaveBeenCalled()
    expect(Kis.placeOrder).toHaveBeenCalledWith('BUY', 'WMT', 1, 90)
  })

  it('KIS 현재가가 비어 오면 시세 캐시로 폴백한다', async () => {
    // KIS 모의투자 계좌는 해외주식 시세가 비어 오는 경우가 있다.
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 0, previousClose: 0 })
    mainState.updatePricesCache({ WMT: 106.5 })
    Kis.placeOrder.mockResolvedValue({ orderId: 'O5', executedPrice: null, executedQty: 0 })

    await handler()({}, { side: 'BUY', ticker: 'WMT', qty: 1, price: null })

    // 106.5 * 1.01 = 107.565 → 올림 107.57
    expect(Kis.placeOrder).toHaveBeenCalledWith('BUY', 'WMT', 1, 107.57)
  })

  it('KIS 현재가도 캐시도 없으면 주문을 보내지 않고 실패한다', async () => {
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 0, previousClose: 0 })

    let err: ReturnType<typeof deserializeIpcError> = null
    try {
      await handler()({}, { side: 'BUY', ticker: 'WMT', qty: 1, price: null })
    } catch (e) {
      err = deserializeIpcError(e)
    }

    expect(err?.code).toBe('KIS_ERROR')
    expect(Kis.placeOrder).not.toHaveBeenCalled()
    expect(mainState.isOrderInProgress).toBe(false)
    // 존재하지 않는 "$0 지정가 주문" 을 감사 기록에 남기지 않는다 —
    // 가격 확정 전에 실패했으므로 원래 의도(MARKET)로 기록된다.
    expect(Backend.recordManualTrade).toHaveBeenCalledWith(
      expect.objectContaining({ order_type: 'MARKET', price: 0, status: 'FAILED' }),
    )
  })

  it('명시 지정가 주문이 KIS 거부로 실패하면 그 지정가가 기록된다', async () => {
    Kis.placeOrder.mockRejectedValue(new Error('KIS 주문 거부: APBK0918'))

    try {
      await handler()({}, { side: 'BUY', ticker: 'WMT', qty: 1, price: 90 })
    } catch {
      // 핸들러는 에러를 다시 던진다 — 기록 payload 만 확인한다.
    }

    expect(Backend.recordManualTrade).toHaveBeenCalledWith(
      expect.objectContaining({ order_type: 'LIMIT', price: 90, status: 'FAILED' }),
    )
  })

  it('백엔드에는 실제로 나간 지정가와 LIMIT 이 기록된다', async () => {
    Kis.getCurrentPrice.mockResolvedValue({ currentPrice: 97.35, previousClose: 96 })
    Kis.placeOrder.mockResolvedValue({ orderId: 'O4', executedPrice: null, executedQty: 0 })

    await handler()({}, { side: 'BUY', ticker: 'WMT', qty: 1, price: null })

    expect(Backend.recordManualTrade).toHaveBeenCalledWith(
      expect.objectContaining({ order_type: 'LIMIT', price: 98.33, status: 'PENDING' }),
    )
  })
})
