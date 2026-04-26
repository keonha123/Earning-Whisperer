import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 공유 axios mock — setup.ts에서 vi.mock('axios') 등록.
import { kisHttpMock } from '../../../test/setup'

import keytar from 'keytar'
import { KisService } from '../KisService'
import { mainState } from '../../store/mainState'
import { balanceWithHoldings, balanceEmpty, psAmountSuccess } from '../../../test/fixtures/kisResponses'

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

describe('KisService.getBalance — VTTS3012R/VTTS3007R 사이 지연', () => {
  it('첫 호출 직후 1100ms 진행 전엔 두 번째 호출 미발생', async () => {
    await seedCredentials()
    kisHttpMock.get
      .mockResolvedValueOnce({ data: balanceWithHoldings })
      .mockResolvedValueOnce({ data: psAmountSuccess })

    vi.useFakeTimers()
    try {
      const promise = KisService.getBalance()

      // 마이크로태스크만 비움 — VTTS3012R 응답까지는 진행
      await vi.advanceTimersByTimeAsync(0)
      // 첫 호출만 트리거된 상태여야 한다
      expect(kisHttpMock.get).toHaveBeenCalledTimes(1)

      // 1100ms 지연 통과 후 두 번째 호출
      await vi.advanceTimersByTimeAsync(1200)
      await promise

      expect(kisHttpMock.get).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })
})
