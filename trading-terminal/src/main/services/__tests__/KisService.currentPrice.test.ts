import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock — setup.ts에서 vi.mock('axios') 등록.
import { kisHttpMock } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { mainState } from '../../store/mainState'
import { currentPriceResponse, currentPriceUndefinedResponse } from '../../../test/fixtures/kisResponses'

const KEYTAR_SERVICE = 'EarningWhisperer'

async function seedCredentials(): Promise<void> {
  await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'app-key')
  await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'app-secret')
  await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', '1234567801')
}

beforeEach(() => {
  mainState.clear()
  mainState.setKisAccessToken('valid-token', 86400)
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
})

afterEach(() => {
  // 토큰 자동 발급 케이스에서 scheduleTokenRefresh 타이머가 누수될 수 있음
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('KisService.getCurrentPrice', () => {
  it('정상: data.output.last → 그 값을 number로 반환', async () => {
    await seedCredentials()
    kisHttpMock.get.mockResolvedValueOnce({ data: currentPriceResponse(245.1) })

    const price = await KisService.getCurrentPrice('TSLA')

    expect(price).toBe(245.1)
    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-price/v1/quotations/price',
      expect.objectContaining({
        headers: expect.objectContaining({ tr_id: 'HHDFS00000300' }),
        params: expect.objectContaining({ EXCD: 'NAS', SYMB: 'TSLA' }),
      }),
    )
  })

  it('last=0 → 0 반환 (호출측 가드 의도)', async () => {
    await seedCredentials()
    kisHttpMock.get.mockResolvedValueOnce({ data: currentPriceResponse(0) })

    expect(await KisService.getCurrentPrice('TSLA')).toBe(0)
  })

  it('last 음수 → 0 반환', async () => {
    await seedCredentials()
    kisHttpMock.get.mockResolvedValueOnce({ data: currentPriceResponse(-1.5) })

    expect(await KisService.getCurrentPrice('TSLA')).toBe(0)
  })

  it('last undefined → 0 반환', async () => {
    await seedCredentials()
    kisHttpMock.get.mockResolvedValueOnce({ data: currentPriceUndefinedResponse })

    expect(await KisService.getCurrentPrice('TSLA')).toBe(0)
  })

  it('HTTP 예외 → throw하지 않고 0 반환', async () => {
    await seedCredentials()
    kisHttpMock.get.mockRejectedValueOnce(new Error('500 Internal Server Error'))

    const price = await KisService.getCurrentPrice('TSLA')

    expect(price).toBe(0) // 호출측이 0 가드로 주문 진입 막음
  })

  it('토큰 무효 시 ensureToken으로 issueToken 자동 호출', async () => {
    mainState.clear()
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({
      data: { access_token: 'fresh', token_type: 'Bearer', expires_in: 86400 },
    })
    kisHttpMock.get.mockResolvedValueOnce({ data: currentPriceResponse(100) })

    const price = await KisService.getCurrentPrice('TSLA')

    expect(kisHttpMock.post).toHaveBeenCalledWith('/oauth2/tokenP', expect.any(Object))
    expect(price).toBe(100)
  })
})
