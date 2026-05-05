import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock — setup.ts에서 vi.mock('axios') 등록.
import { kisHttpMock } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { kisLimiter } from '../KisRateLimiter'
import { mainState } from '../../store/mainState'
import {
  balanceWithHoldings,
  balanceEmpty,
  psAmountSuccess,
  kisBalanceRejectResponse,
  kisPsamountRejectResponse,
} from '../../../test/fixtures/kisResponses'

const KEYTAR_SERVICE = 'EarningWhisperer'

async function seedCredentials(): Promise<void> {
  const mode = mainState.isPaperTrading ? 'paper' : 'real'
  await keytar.setPassword(KEYTAR_SERVICE, `kis-appKey-${mode}`, 'app-key')
  await keytar.setPassword(KEYTAR_SERVICE, `kis-appSecret-${mode}`, 'app-secret')
  await keytar.setPassword(KEYTAR_SERVICE, `kis-accountNo-${mode}`, '1234567801')
}

beforeEach(() => {
  mainState.clear()
  // mainState.clear() 는 isPaperTrading 을 유지하므로 leak 방지로 명시 reset
  mainState.setPaperTrading(true)
  mainState.setKisAccessToken('valid-token', 86400)
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
  vi.mocked(kisLimiter.acquire).mockClear()
})

afterEach(() => {
  // mainState.setKisAccessToken으로 등록된 setTimeout(scheduleTokenRefresh)이나
  // _getBalanceImpl 내부의 1100ms 지연 setTimeout이 누수되지 않도록 정리
  vi.clearAllTimers()
  vi.useRealTimers()
})

/**
 * VTTS3012R(잔고) → 1100ms 지연 → VTTS3007R(주문가능외화) 순서.
 * 단위 테스트는 fakeTimers로 지연을 즉시 통과시킨다.
 */
async function runBalanceWithFakeTimers<T>(fn: () => Promise<T>): Promise<T> {
  vi.useFakeTimers()
  try {
    const promise = fn()
    // 마이크로태스크 큐 비우고 → 1100ms 진행
    await vi.advanceTimersByTimeAsync(1200)
    return await promise
  } finally {
    vi.useRealTimers()
  }
}

describe('KisService.getBalance — 정상 응답 파싱', () => {
  it('output1 배열 → holdings 매핑 (ticker/qty/avgPrice/currentPrice)', async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockResolvedValueOnce({ data: psAmountSuccess })

    const result = await runBalanceWithFakeTimers(() => KisService.getBalance())

    expect(result.orderableCash).toBe(12345.67)
    expect(result.totalCash).toBe(12345.67)
    expect(result.holdings).toEqual([
      { ticker: 'TSLA', qty: 10, avgPrice: 230.55, currentPrice: 245.1 },
      { ticker: 'AAPL', qty: 5, avgPrice: 185, currentPrice: 190.2 },
    ])
  })

  it('output1 빈 배열 → holdings=[]', async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceEmpty })
      .mockResolvedValueOnce({ data: psAmountSuccess })

    const result = await runBalanceWithFakeTimers(() => KisService.getBalance())

    expect(result.holdings).toEqual([])
    expect(result.orderableCash).toBe(12345.67)
  })

  it('VTTS3007R 실패 → orderableCash=0이지만 holdings는 정상 반환', async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockRejectedValueOnce(new Error('VTTS3007R 5xx'))

    const result = await runBalanceWithFakeTimers(() => KisService.getBalance())

    expect(result.orderableCash).toBe(0)
    expect(result.holdings).toHaveLength(2)
    expect(result.holdings[0].ticker).toBe('TSLA')
  })
})

describe('KisService.getBalance — 동시 호출 (in-flight)', () => {
  it('같은 시점 getBalance() 두 번 호출 → axios.get은 각 엔드포인트 1번씩만', async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockResolvedValueOnce({ data: psAmountSuccess })

    vi.useFakeTimers()
    try {
      const p1 = KisService.getBalance()
      const p2 = KisService.getBalance() // in-flight 재사용

      await vi.advanceTimersByTimeAsync(1200)
      const [r1, r2] = await Promise.all([p1, p2])

      // 동일 객체 참조여야 in-flight 재사용으로 간주
      expect(r1).toBe(r2)
      // 잔고 1번 + ps 1번 = 총 2번 (재사용 시 4번이 아니라 2번이어야 함)
      expect(kisHttpMock.get).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('KisService.getBalance — KIS rt_cd 비즈니스 실패 처리', () => {
  it("VTTS3012R rt_cd='1' → throw (잔고 부정확 시 SELL 위험 차단)", async () => {
    await seedCredentials()
    kisHttpMock.get.mockResolvedValueOnce({
      data: kisBalanceRejectResponse('OPSP0002', '계좌 조회 권한이 없습니다.'),
    })

    // VTTS3012R가 rt_cd='1'로 즉시 throw되므로 1100ms 대기에 도달하지 않는다.
    // → fake timers 불필요. real timers로 직접 await하여 unhandled rejection 경고 방지.
    await expect(KisService.getBalance()).rejects.toThrow(/계좌 조회 권한이 없습니다/)

    // VTTS3012R 1회만 호출되고 VTTS3007R로 진입하지 않아야 한다
    expect(kisHttpMock.get).toHaveBeenCalledTimes(1)
  })

  it("VTTS3007R rt_cd='1' → orderableCash=0이지만 holdings는 정상 반환 (부분 fallback)", async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockResolvedValueOnce({
        data: kisPsamountRejectResponse('APBK0001', '주문가능금액 조회 일시 오류'),
      })

    const result = await runBalanceWithFakeTimers(() => KisService.getBalance())

    expect(result.orderableCash).toBe(0)
    expect(result.totalCash).toBe(0)
    expect(result.holdings).toHaveLength(2)
    expect(result.holdings[0].ticker).toBe('TSLA')
    expect(result.holdings[1].ticker).toBe('AAPL')
  })
})

describe('KisService.getBalance — KisRateLimiter 통합', () => {
  it('VTTS3012R/VTTS3007R 호출 직전 acquire(MEDIUM) 2회 호출', async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockResolvedValueOnce({ data: psAmountSuccess })

    await KisService.getBalance()

    // 잔고 조회 두 단계 각각 acquire('MEDIUM')
    const acquireMock = vi.mocked(kisLimiter.acquire)
    const mediumCalls = acquireMock.mock.calls.filter((c) => c[0] === 'MEDIUM')
    expect(mediumCalls).toHaveLength(2)
    expect(kisHttpMock.get).toHaveBeenCalledTimes(2)
  })
})

describe('KisService.getBalance — TR_ID 모드별 분기 (C1)', () => {
  it('실전 모드(paper=false) → 잔고=TTTS3012R / 주문가능=TTTS3007R 헤더로 호출', async () => {
    mainState.setPaperTrading(false)
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockResolvedValueOnce({ data: psAmountSuccess })

    await runBalanceWithFakeTimers(() => KisService.getBalance())

    // 1번째 호출: 잔고
    const [, balanceConfig] = kisHttpMock.get.mock.calls[0]
    expect(balanceConfig.headers.tr_id).toBe('TTTS3012R')

    // 2번째 호출: 주문가능외화
    const [, psConfig] = kisHttpMock.get.mock.calls[1]
    expect(psConfig.headers.tr_id).toBe('TTTS3007R')
  })

  it('모의 모드(paper=true, 디폴트) → VTTS3012R / VTTS3007R 유지 (회귀 보호)', async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockResolvedValueOnce({ data: psAmountSuccess })

    await runBalanceWithFakeTimers(() => KisService.getBalance())

    const [, balanceConfig] = kisHttpMock.get.mock.calls[0]
    expect(balanceConfig.headers.tr_id).toBe('VTTS3012R')
    const [, psConfig] = kisHttpMock.get.mock.calls[1]
    expect(psConfig.headers.tr_id).toBe('VTTS3007R')
  })
})
