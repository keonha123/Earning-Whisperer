import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock — setup.ts에서 vi.mock('axios') 등록 + 매 테스트마다 reset.
import { kisHttpMock } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { kisLimiter } from '../KisRateLimiter'
import { mainState } from '../../store/mainState'
import { orderSuccessResponse, kisOrderRejectResponse } from '../../../test/fixtures/kisResponses'

const KEYTAR_SERVICE = 'EarningWhisperer'

/**
 * 활성 모드 기준 slot 에 시드. 모드 전환 케이스는 setPaperTrading 후 직접 다른 slot 에 set.
 */
async function seedCredentials(accountNo = '1234567801'): Promise<void> {
  const mode = mainState.isPaperTrading ? 'paper' : 'real'
  await keytar.setPassword(KEYTAR_SERVICE, `kis-appKey-${mode}`, 'app-key')
  await keytar.setPassword(KEYTAR_SERVICE, `kis-appSecret-${mode}`, 'app-secret')
  await keytar.setPassword(KEYTAR_SERVICE, `kis-accountNo-${mode}`, accountNo)
}

beforeEach(() => {
  mainState.clear()
  // mainState.clear() 는 isPaperTrading 을 유지하므로 모드 전환 테스트 leak 방지로 명시 reset
  mainState.setPaperTrading(true)
  // 토큰 미리 발급해둔 상태에서 placeOrder만 검증 (issueToken 흐름은 별도 테스트)
  mainState.setKisAccessToken('valid-token', 86400)
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
  vi.mocked(kisLimiter.acquire).mockClear()
})

afterEach(() => {
  // 토큰 자동 발급 케이스에서 scheduleTokenRefresh 타이머가 누수될 수 있음
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('KisService.placeOrder', () => {
  it('BUY → tr_id=VTTT1002U 헤더로 호출', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD1') })

    await KisService.placeOrder('BUY', 'TSLA', 3)

    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)
    const [url, , config] = kisHttpMock.post.mock.calls[0]
    expect(url).toBe('/uapi/overseas-stock/v1/trading/order')
    expect(config.headers.tr_id).toBe('VTTT1002U')
  })

  it('SELL → tr_id=VTTT1006U 헤더로 호출', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD2') })

    await KisService.placeOrder('SELL', 'AAPL', 1)

    const [, , config] = kisHttpMock.post.mock.calls[0]
    expect(config.headers.tr_id).toBe('VTTT1006U')
  })

  it('주문 페이로드 구조 — 시장가/NASDAQ/qty 문자열 변환', async () => {
    await seedCredentials('1234567801')
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD3') })

    await KisService.placeOrder('BUY', 'TSLA', 7)

    const [, body] = kisHttpMock.post.mock.calls[0]
    expect(body).toMatchObject({
      ORD_DVSN: '00',
      ORD_QTY: '7',
      OVRS_EXCG_CD: 'NASD',
      PDNO: 'TSLA',
      OVRS_ORD_UNPR: '0',
    })
    expect(typeof body.ORD_QTY).toBe('string')
  })

  it('계좌번호 분해: 10자리 → CANO=앞8 / ACNT_PRDT_CD=뒤2', async () => {
    await seedCredentials('1234567899')
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD4') })

    await KisService.placeOrder('BUY', 'TSLA', 1)

    const [, body] = kisHttpMock.post.mock.calls[0]
    expect(body.CANO).toBe('12345678')
    expect(body.ACNT_PRDT_CD).toBe('99')
  })

  it('계좌번호 8자리: ACNT_PRDT_CD 기본값 "01"', async () => {
    await seedCredentials('12345678') // 정확히 8자리
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD5') })

    await KisService.placeOrder('BUY', 'TSLA', 1)

    const [, body] = kisHttpMock.post.mock.calls[0]
    expect(body.CANO).toBe('12345678')
    expect(body.ACNT_PRDT_CD).toBe('01')
  })

  it('응답 ODNO → orderId 매핑', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('K-987654') })

    const result = await KisService.placeOrder('BUY', 'TSLA', 1)

    expect(result.orderId).toBe('K-987654')
    expect(result.executedPrice).toBeNull()
    expect(result.executedQty).toBe(1)
  })

  it('응답에 ODNO 없을 때 빈 문자열 fallback', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: { rt_cd: '0', output: {} } })

    const result = await KisService.placeOrder('BUY', 'TSLA', 1)
    expect(result.orderId).toBe('')
  })

  it('토큰 미발급(invalid) 시 issueToken 자동 호출', async () => {
    mainState.clear() // 토큰 무효 상태
    await seedCredentials()
    // issueToken은 axios.post('/oauth2/tokenP', ...)를 호출함
    kisHttpMock.post.mockImplementation(async (url: string) => {
      if (url === '/oauth2/tokenP') {
        return { data: { access_token: 'fresh', token_type: 'Bearer', expires_in: 86400 } }
      }
      return { data: orderSuccessResponse('OD-AFTER-TOKEN') }
    })

    const result = await KisService.placeOrder('BUY', 'TSLA', 1)

    // 첫 호출: tokenP, 두번째: 주문
    expect(kisHttpMock.post.mock.calls[0][0]).toBe('/oauth2/tokenP')
    expect(kisHttpMock.post.mock.calls[1][0]).toBe('/uapi/overseas-stock/v1/trading/order')
    expect(result.orderId).toBe('OD-AFTER-TOKEN')
  })

  it('placeOrder — issueToken 단계: appKey/appSecret 둘 다 누락 시 issueToken 내부 가드에서 throw', async () => {
    // mainState 토큰 없음 (beforeEach에서 setKisAccessToken을 했지만 여기서 clear)
    // keytar에 자격증명도 없음 → ensureToken → issueToken → "KIS API 키가 등록되지 않았" throw
    mainState.clear()

    await expect(KisService.placeOrder('BUY', 'TSLA', 1)).rejects.toThrow(
      /KIS API 키가 등록되지 않았/,
    )
    // 주문 자체도 안 나가야 한다 (tokenP 호출조차 가지 않음 — keytar 단계에서 throw)
    expect(kisHttpMock.post).not.toHaveBeenCalled()
  })

  it('placeOrder — placeOrder 본체 가드: 토큰은 유효하나 accountNo만 누락', async () => {
    // 1. 자격증명 + 토큰 시드
    await seedCredentials() // appKey/appSecret/accountNo 모두 저장 (paper slot)
    // (토큰은 beforeEach에서 setKisAccessToken으로 valid 상태)
    // 2. accountNo만 삭제 → ensureToken은 통과, placeOrder 본체 가드에서 throw
    await keytar.deletePassword(KEYTAR_SERVICE, 'kis-accountNo-paper')

    // 3. 호출 → "자격 증명이 등록되지 않았" throw
    await expect(KisService.placeOrder('BUY', 'TSLA', 1)).rejects.toThrow(
      /자격 증명이 등록되지 않았/,
    )
    // 토큰이 유효하므로 issueToken 경로(/oauth2/tokenP)도, 주문 경로도 호출되지 않아야 한다
    expect(kisHttpMock.post).not.toHaveBeenCalled()
  })

  it('placeOrder — appKey만 있고 appSecret 누락 시 placeOrder 본체 가드에서 throw (토큰 유효)', async () => {
    // 토큰은 유효(beforeEach), appKey만 등록 — appSecret/accountNo 모두 누락
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-paper', 'app-key')

    await expect(KisService.placeOrder('BUY', 'TSLA', 1)).rejects.toThrow(
      /자격 증명이 등록되지 않았/,
    )
    expect(kisHttpMock.post).not.toHaveBeenCalled()
  })
})

describe('KisService.placeOrder — KIS rt_cd 비즈니스 실패 처리', () => {
  it("rt_cd='1' (APBK0918 주문가능금액 부족) → throw + msg1 포함", async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({
      data: kisOrderRejectResponse('APBK0918', '주문가능금액이 부족합니다.'),
    })

    await expect(KisService.placeOrder('BUY', 'TSLA', 3)).rejects.toThrow(
      /주문가능금액이 부족합니다/,
    )
    // 호출 자체는 1회 (재시도 없음)
    expect(kisHttpMock.post).toHaveBeenCalledTimes(1)
  })

  it("rt_cd='1' (시장 휴장 등 임의 메시지) → throw + 메시지 전파", async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({
      data: kisOrderRejectResponse('APBK1234', '시장 휴장으로 주문이 거부되었습니다.'),
    })

    await expect(KisService.placeOrder('SELL', 'AAPL', 1)).rejects.toThrow(
      /시장 휴장/,
    )
  })

  it("rt_cd='1' + msg1 누락 시 msg_cd로 fallback", async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({
      data: { rt_cd: '1', msg_cd: 'APBK9999', output: {} },
    })

    await expect(KisService.placeOrder('BUY', 'TSLA', 1)).rejects.toThrow(
      /APBK9999/,
    )
  })

  it("rt_cd='0' + 정상 ODNO → 기존 동작 유지 (회귀 보호)", async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-OK') })

    const result = await KisService.placeOrder('BUY', 'TSLA', 1)

    expect(result.orderId).toBe('OD-OK')
    expect(result.executedQty).toBe(1)
    expect(result.executedPrice).toBeNull()
  })

  it('주문 + 체결조회 각각 acquire(HIGH) 호출 (총 2회)', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-LIM') })
    // inquireOrderFill 의 GET 도 HIGH 토큰 1개 사용. mock 안 하면 fallback 으로 빠지지만
    // 그 전에 acquire 는 호출됨.
    kisHttpMock.get.mockRejectedValueOnce(new Error('inquire skip'))

    await KisService.placeOrder('BUY', 'TSLA', 1)

    const acquireMock = vi.mocked(kisLimiter.acquire)
    const highCalls = acquireMock.mock.calls.filter((c) => c[0] === 'HIGH')
    expect(highCalls).toHaveLength(2)
  })
})

describe('KisService.placeOrder — TR_ID 모드별 분기 (C1)', () => {
  it('실전 모드(paper=false) BUY → tr_id=TTTT1002U 헤더로 호출', async () => {
    mainState.setPaperTrading(false)
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-REAL-BUY') })

    await KisService.placeOrder('BUY', 'TSLA', 1)

    const [, , config] = kisHttpMock.post.mock.calls[0]
    expect(config.headers.tr_id).toBe('TTTT1002U')
  })

  it('실전 모드(paper=false) SELL → tr_id=TTTT1006U 헤더로 호출', async () => {
    mainState.setPaperTrading(false)
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-REAL-SELL') })

    await KisService.placeOrder('SELL', 'AAPL', 1)

    const [, , config] = kisHttpMock.post.mock.calls[0]
    expect(config.headers.tr_id).toBe('TTTT1006U')
  })

  it('모의 모드(paper=true, 디폴트) BUY → tr_id=VTTT1002U 유지 (회귀 보호)', async () => {
    // 디폴트 paper=true (beforeEach에서 mainState.clear → setPaperTrading은 디폴트 true)
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-PAPER') })

    await KisService.placeOrder('BUY', 'TSLA', 1)

    const [, , config] = kisHttpMock.post.mock.calls[0]
    expect(config.headers.tr_id).toBe('VTTT1002U')
  })
})

describe('KisService.placeOrder — 체결조회로 executedQty 정확화', () => {
  function buildCcnlResponse(odno: string, totQty: string, avgPrice: string) {
    return {
      data: {
        rt_cd: '0',
        msg1: '정상',
        output: [
          { odno, tot_ccld_qty: totQty, avg_prvs: avgPrice, pdno: 'TSLA' },
        ],
      },
    }
  }

  it('정상 체결 (요청 = 체결) → 정확한 executedQty/executedPrice 반환', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-FILL') })
    kisHttpMock.get.mockResolvedValueOnce(buildCcnlResponse('OD-FILL', '10', '125.50'))

    const result = await KisService.placeOrder('BUY', 'TSLA', 10)

    expect(result.orderId).toBe('OD-FILL')
    expect(result.executedQty).toBe(10)
    expect(result.executedPrice).toBe(125.50)
    // inquireCcnl 호출 검증
    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      expect.objectContaining({
        headers: expect.objectContaining({ tr_id: 'VTTS3035R' }),
      }),
    )
  })

  it('부분 체결 (요청 10 > 체결 7) → executedQty=7 반환', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-PART') })
    kisHttpMock.get.mockResolvedValueOnce(buildCcnlResponse('OD-PART', '7', '124.30'))

    const result = await KisService.placeOrder('BUY', 'TSLA', 10)

    expect(result.executedQty).toBe(7)
    expect(result.executedPrice).toBe(124.30)
  })

  it('미체결 (executedQty=0) → executedQty=0, executedPrice=null', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-NONE') })
    kisHttpMock.get.mockResolvedValueOnce(buildCcnlResponse('OD-NONE', '0', '0'))

    const result = await KisService.placeOrder('BUY', 'TSLA', 10)

    expect(result.executedQty).toBe(0)
    expect(result.executedPrice).toBeNull()
  })

  it('inquire-ccnl rt_cd 실패 → fallback (executedQty=qty 가정, 회귀 없음)', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-FB1') })
    kisHttpMock.get.mockResolvedValueOnce({
      data: { rt_cd: '1', msg1: '조회 실패' },
    })

    const result = await KisService.placeOrder('BUY', 'TSLA', 10)

    expect(result.executedQty).toBe(10) // fallback
    expect(result.executedPrice).toBeNull()
  })

  it('inquire-ccnl 네트워크 오류 → fallback', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-FB2') })
    kisHttpMock.get.mockRejectedValueOnce(new Error('network down'))

    const result = await KisService.placeOrder('BUY', 'TSLA', 5)

    expect(result.executedQty).toBe(5)
    expect(result.executedPrice).toBeNull()
  })

  it('inquire-ccnl 응답에 ODNO 매칭 row 없음 → fallback', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-MISS') })
    kisHttpMock.get.mockResolvedValueOnce(buildCcnlResponse('OTHER-ODNO', '10', '125.0'))

    const result = await KisService.placeOrder('BUY', 'TSLA', 10)

    expect(result.executedQty).toBe(10)
    expect(result.executedPrice).toBeNull()
  })

  it('ODNO 빈 문자열 → 체결조회 skip + fallback (호출 자체 안 함)', async () => {
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: { rt_cd: '0', output: {} } })

    const result = await KisService.placeOrder('BUY', 'TSLA', 3)

    expect(result.orderId).toBe('')
    expect(result.executedQty).toBe(3)
    expect(kisHttpMock.get).not.toHaveBeenCalled()
  })

  it('실전 모드 → tr_id=TTTS3035R 로 체결조회', async () => {
    mainState.setPaperTrading(false)
    await seedCredentials()
    kisHttpMock.post.mockResolvedValueOnce({ data: orderSuccessResponse('OD-REAL') })
    kisHttpMock.get.mockResolvedValueOnce(buildCcnlResponse('OD-REAL', '5', '200.0'))

    await KisService.placeOrder('BUY', 'TSLA', 5)

    expect(kisHttpMock.get).toHaveBeenCalledWith(
      '/uapi/overseas-stock/v1/trading/inquire-ccnl',
      expect.objectContaining({
        headers: expect.objectContaining({ tr_id: 'TTTS3035R' }),
      }),
    )
  })
})
