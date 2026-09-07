import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock — setup.ts에서 vi.mock('axios') 등록.
import { kisHttpMock } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { kisLimiter } from '../KisRateLimiter'
import { mainState } from '../../store/mainState'
import { currentPriceResponse, orderSuccessResponse } from '../../../test/fixtures/kisResponses'

const KEYTAR_SERVICE = 'EarningWhisperer'

async function seedCredentials(): Promise<void> {
  const mode = mainState.isPaperTrading ? 'paper' : 'real'
  await keytar.setPassword(KEYTAR_SERVICE, `kis-appKey-${mode}`, 'app-key')
  await keytar.setPassword(KEYTAR_SERVICE, `kis-appSecret-${mode}`, 'app-secret')
  await keytar.setPassword(KEYTAR_SERVICE, `kis-accountNo-${mode}`, '1234567801')
}

beforeEach(() => {
  mainState.clear()
  mainState.setPaperTrading(true)
  mainState.setKisAccessToken('valid-token', 86400)
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
  vi.mocked(kisLimiter.acquire).mockClear()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('거래소 코드 티커별 해석', () => {
  it('getCurrentPrice: NYSE 종목(JPM) → EXCD=NYS', async () => {
    await seedCredentials()
    kisHttpMock.get.mockResolvedValueOnce({ data: currentPriceResponse(210.5) })

    await KisService.getCurrentPrice('JPM')

    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-price/v1/quotations/price',
      expect.objectContaining({
        params: expect.objectContaining({ EXCD: 'NYS', SYMB: 'JPM' }),
      }),
    )
  })

  it('getCurrentPrice: NASDAQ 종목(AAPL) → EXCD=NAS', async () => {
    await seedCredentials()
    kisHttpMock.get.mockResolvedValueOnce({ data: currentPriceResponse(190.1) })

    await KisService.getCurrentPrice('AAPL')

    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-price/v1/quotations/price',
      expect.objectContaining({
        params: expect.objectContaining({ EXCD: 'NAS', SYMB: 'AAPL' }),
      }),
    )
  })

  it('placeOrder: NYSE 종목(JPM) → OVRS_EXCG_CD=NYSE', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-NYS') })

    await KisService.placeOrder('BUY', 'JPM', 1)

    const [, body] = kisHttpMock.post.mock.calls[0]
    expect(body.OVRS_EXCG_CD).toBe('NYSE')
    expect(body.PDNO).toBe('JPM')
  })

  it('placeOrder: NASDAQ 종목(AAPL) → OVRS_EXCG_CD=NASD', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-NAS') })

    await KisService.placeOrder('BUY', 'AAPL', 1)

    const [, body] = kisHttpMock.post.mock.calls[0]
    expect(body.OVRS_EXCG_CD).toBe('NASD')
    expect(body.PDNO).toBe('AAPL')
  })
})

describe('체결 조회(inquire-ccnl) 거래소 코드', () => {
  function ccnlResponse(odno: string, ticker: string) {
    return {
      data: {
        rt_cd: '0',
        msg1: '정상',
        output: [{ odno, tot_ccld_qty: '1', avg_prvs: '100.00', pdno: ticker }],
      },
    }
  }

  it('NYSE 종목(JPM) 주문 후 체결 조회 → OVRS_EXCG_CD=NYSE', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-CCNL-NYS') })
    kisHttpMock.get.mockResolvedValueOnce(ccnlResponse('OD-CCNL-NYS', 'JPM'))

    const result = await KisService.placeOrder('BUY', 'JPM', 1)

    expect(result.executedQty).toBe(1)
    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      expect.objectContaining({
        params: expect.objectContaining({ OVRS_EXCG_CD: 'NYSE', PDNO: 'JPM' }),
      }),
    )
  })

  it('NASDAQ 종목(AAPL) 주문 후 체결 조회 → OVRS_EXCG_CD=NASD', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-CCNL-NAS') })
    kisHttpMock.get.mockResolvedValueOnce(ccnlResponse('OD-CCNL-NAS', 'AAPL'))

    const result = await KisService.placeOrder('BUY', 'AAPL', 1)

    expect(result.executedQty).toBe(1)
    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      expect.objectContaining({
        params: expect.objectContaining({ OVRS_EXCG_CD: 'NASD', PDNO: 'AAPL' }),
      }),
    )
  })
})
