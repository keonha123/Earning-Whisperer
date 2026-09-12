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

  it('실전: NYSE 종목(JPM) 체결 조회 → OVRS_EXCG_CD=NYSE, PDNO 로 좁힌다', async () => {
    mainState.setPaperTrading(false)
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-CCNL-NYS') })
    kisHttpMock.get.mockResolvedValueOnce(ccnlResponse('OD-CCNL-NYS', 'JPM'))

    const result = await KisService.placeOrder('BUY', 'JPM', 1)

    expect(result.executedQty).toBe(1)
    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      expect.objectContaining({
        params: expect.objectContaining({ OVRS_EXCG_CD: 'NYSE', PDNO: 'JPM', SORT_SQN: 'DS' }),
      }),
    )
  })

  it('실전: NASDAQ 종목(AAPL) 체결 조회 → OVRS_EXCG_CD=NASD', async () => {
    mainState.setPaperTrading(false)
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

  it('모의: 종목코드/거래소코드/정렬순서를 빈 값으로 보낸다', async () => {
    // 모의투자는 이 세 파라미터를 지원하지 않는다. 값을 채워 보내면 조건에 맞는 주문이
    // 있어도 응답이 0건으로 온다 — 실제로 체결된 주문이 미체결로 보고됐다.
    mainState.setPaperTrading(true)
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-PAPER') })
    kisHttpMock.get.mockResolvedValueOnce(ccnlResponse('OD-PAPER', 'WMT'))

    const result = await KisService.placeOrder('BUY', 'WMT', 1)

    expect(result.executedQty).toBe(1)
    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      expect.objectContaining({
        params: expect.objectContaining({
          PDNO: '',
          OVRS_EXCG_CD: '',
          SORT_SQN: '',
          SLL_BUY_DVSN: '00',
          CCLD_NCCS_DVSN: '00',
        }),
      }),
    )
  })

  it('0 패딩이 다른 ODNO 도 같은 주문으로 매칭한다', async () => {
    // 주문 API 는 0000044600, 체결조회는 44600 으로 준다. 문자열 정확 비교로는
    // 영원히 안 맞아서, 체결된 주문이 계속 미체결로 보고됐다.
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('0000044600') })
    kisHttpMock.get.mockResolvedValueOnce({
      data: {
        rt_cd: '0',
        output: [{ odno: '44600', tot_ccld_qty: '1', avg_prvs: '107.47', pdno: 'WMT' }],
      },
    })

    const result = await KisService.placeOrder('BUY', 'WMT', 1)

    expect(result.executedQty).toBe(1)
    expect(result.executedPrice).toBe(107.47)
  })

  it('패딩만 다른 다른 주문번호는 섞지 않는다', async () => {
    // 0 제거 후 비교하므로 44600 과 4460 이 섞이지 않는지 확인한다.
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('0000044600') })
    kisHttpMock.get.mockResolvedValueOnce({
      data: {
        rt_cd: '0',
        output: [{ odno: '4460', tot_ccld_qty: '9', avg_prvs: '1.00', pdno: 'WMT' }],
      },
    })

    const result = await KisService.placeOrder('BUY', 'WMT', 1)

    expect(result.executedQty).toBe(0)
  })

  it('ODNO 는 빈 값으로 보내고 응답에서 직접 매칭한다', async () => {
    // 문서 규격상 ODNO 는 빈 값이다. 모의에서는 종목으로도 좁힐 수 없으므로 어차피
    // 클라이언트 필터가 필요하다 — 다른 종목 row 가 섞여 와도 골라내야 한다.
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-MINE') })
    kisHttpMock.get.mockResolvedValueOnce({
      data: {
        rt_cd: '0',
        output: [
          { odno: 'OD-OTHER', tot_ccld_qty: '5', avg_prvs: '1.00', pdno: 'AAPL' },
          { odno: 'OD-MINE', tot_ccld_qty: '2', avg_prvs: '107.47', pdno: 'WMT' },
        ],
      },
    })

    const result = await KisService.placeOrder('BUY', 'WMT', 2)

    expect(result.executedQty).toBe(2)
    expect(result.executedPrice).toBe(107.47)
    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      expect.objectContaining({ params: expect.objectContaining({ ODNO: '' }) }),
    )
  })
})
