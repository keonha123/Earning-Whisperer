import { describe, it, expect, beforeEach } from 'vitest'

// 공유 axios mock — setup.ts 에서 vi.mock('axios') 등록.
import { kisHttpMock } from '../../../test/setup'
import { BackendClient } from '../BackendClient'

beforeEach(() => {
  kisHttpMock.get.mockReset()
})

/**
 * GET /api/v1/trades/pending — Terminal 재접속 시 미만료 PENDING 명령 복구.
 *
 * 응답은 STOMP /user/queue/signals 메시지와 동일 형식 (TradeCommandMessage 직렬화).
 * 비정상 응답(null/object/undefined) 은 항상 빈 배열로 정규화한다.
 */
describe('BackendClient.fetchPendingTrades', () => {
  it('정상 응답 — 그대로 반환', async () => {
    const fixture = [
      { trade_id: 7, action: 'BUY', order_ratio: 0.1, ticker: 'NVDA', ai_score: 0.85 },
      { trade_id: 8, action: 'SELL', order_ratio: 0.5, ticker: 'TSLA', ai_score: -0.7 },
    ]
    kisHttpMock.get.mockResolvedValueOnce({ data: fixture })

    const result = await BackendClient.fetchPendingTrades()

    expect(result).toEqual(fixture)
    expect(kisHttpMock.get).toHaveBeenCalledWith('/api/v1/trades/pending')
  })

  it('빈 배열 응답', async () => {
    kisHttpMock.get.mockResolvedValueOnce({ data: [] })
    expect(await BackendClient.fetchPendingTrades()).toEqual([])
  })

  it('data: null → []', async () => {
    kisHttpMock.get.mockResolvedValueOnce({ data: null })
    expect(await BackendClient.fetchPendingTrades()).toEqual([])
  })

  it('data: 객체 → []', async () => {
    kisHttpMock.get.mockResolvedValueOnce({ data: { error: 'oops' } })
    expect(await BackendClient.fetchPendingTrades()).toEqual([])
  })

  it('네트워크 오류 → throw (호출 측이 catch)', async () => {
    kisHttpMock.get.mockRejectedValueOnce(new Error('network down'))
    await expect(BackendClient.fetchPendingTrades()).rejects.toThrow('network down')
  })
})
