import { describe, it, expect, beforeEach } from 'vitest'

// 공유 axios mock — setup.ts 에서 vi.mock('axios') 등록.
import { kisHttpMock } from '../../../test/setup'
import { BackendClient } from '../BackendClient'

beforeEach(() => {
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
})

/**
 * Backend Contract 7.7 — GET /api/v1/market/indices.
 *
 * 정상 케이스: 5종 snake_case 배열을 그대로 반환.
 * 비정상 케이스: 응답이 배열이 아니더라도 호출자가 항상 배열을 받도록 [] 정규화
 *   (axios 의 200 응답 본문이 null/object/undefined 인 fallback 시나리오).
 */
describe('BackendClient.getMarketIndices', () => {
  it('정상 5종 배열 응답 — 그대로 반환', async () => {
    const fixture = [
      { symbol: '10Y', price: 4.32, change_percent: -0.05, trend: 'down', format: 'percent', timestamp: 1714400000 },
      { symbol: 'DXY', price: 105.21, change_percent: 0.12, trend: 'up', format: 'index', timestamp: 1714400000 },
      { symbol: 'NDX', price: 17800.55, change_percent: 0.34, trend: 'up', format: 'index', timestamp: 1714400000 },
      { symbol: 'SPX', price: 5123.4, change_percent: 0.21, trend: 'up', format: 'index', timestamp: 1714400000 },
      { symbol: 'VIX', price: 13.6, change_percent: -1.1, trend: 'down', format: 'index', timestamp: 1714400000 },
    ]
    kisHttpMock.get.mockResolvedValueOnce({ data: fixture })

    const result = await BackendClient.getMarketIndices()

    expect(result).toEqual(fixture)
    expect(kisHttpMock.get).toHaveBeenCalledWith('/api/v1/market/indices')
  })

  it('data: null → []', async () => {
    kisHttpMock.get.mockResolvedValueOnce({ data: null })
    const result = await BackendClient.getMarketIndices()
    expect(result).toEqual([])
  })

  it('data: { error: ... } 객체 → []', async () => {
    kisHttpMock.get.mockResolvedValueOnce({
      data: { error: 'cache-miss', message: 'no data' },
    })
    const result = await BackendClient.getMarketIndices()
    expect(result).toEqual([])
  })

  it('data: undefined → []', async () => {
    kisHttpMock.get.mockResolvedValueOnce({ data: undefined })
    const result = await BackendClient.getMarketIndices()
    expect(result).toEqual([])
  })
})
