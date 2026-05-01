import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * useCompanyDetail hook 의 ipc 호출 helper 단위 테스트.
 *
 * vitest 가 node 환경이라 React useEffect/useState 자체는 검증하지 않고,
 * 추출된 fetchStockDetail (ipc.invoke wrapper) 의 정상 응답 / 에러 정규화 동작을 확인한다.
 */

// vi.mock 호이스팅: factory 안의 mockInvoke 는 vi.hoisted 로 같이 호이스트.
const { mockInvoke, mockOn } = vi.hoisted(() => ({
  mockInvoke: vi.fn(),
  mockOn: vi.fn(),
}))

vi.mock('../../lib/ipc', async () => {
  const actual = await vi.importActual<typeof import('../../../lib/ipcChannels')>(
    '../../../lib/ipcChannels',
  )
  return {
    ipc: {
      invoke: mockInvoke,
      on: mockOn,
    },
    IPC_CHANNELS: actual.IPC_CHANNELS,
  }
})

// import 는 mock 이후. ESM 정적 import 이 동일하게 동작하도록 await import 사용.
const { fetchStockDetail } = await import('../useCompanyDetail')
const { IPC_CHANNELS } = await import('../../../lib/ipcChannels')

beforeEach(() => {
  mockInvoke.mockReset()
})

describe('fetchStockDetail', () => {
  it('IPC 응답을 그대로 반환', async () => {
    const payload = {
      ticker: 'NVDA',
      companyName: 'NVIDIA Corp.',
      sector: 'Technology',
      active: true,
      basic: {
        marketCapUsd: 3.12e12,
        high52w: 138.07,
        low52w: 75.6,
        dividendYield: 0.0003,
      },
      chart30d: [{ date: '2026-04-01', close: 110, volume: null }],
      currentPrice: 125.5,
      earningsHistory: [],
      nextEarning: null,
      partial: false,
      ai: null,
    }
    mockInvoke.mockResolvedValueOnce(payload)

    const out = await fetchStockDetail('NVDA')

    expect(out).toEqual(payload)
    expect(mockInvoke).toHaveBeenCalledExactlyOnceWith(
      IPC_CHANNELS.STOCK_GET_DETAIL,
      { ticker: 'NVDA' },
    )
  })

  it('IPC 가 Error 를 reject 하면 그대로 throw', async () => {
    const err = new Error('invalid ticker')
    mockInvoke.mockRejectedValueOnce(err)

    await expect(fetchStockDetail('NVDA')).rejects.toBe(err)
  })

  it('IPC 가 비-Error 를 reject 하면 Error 로 정규화', async () => {
    mockInvoke.mockRejectedValueOnce('boom')

    const promise = fetchStockDetail('AAPL')

    await expect(promise).rejects.toBeInstanceOf(Error)
    await expect(promise).rejects.toMatchObject({ message: 'boom' })
  })

  it('IPC 가 number 를 reject 해도 Error 로 정규화', async () => {
    mockInvoke.mockRejectedValueOnce(500)

    await expect(fetchStockDetail('TSLA')).rejects.toMatchObject({ message: '500' })
  })

  it('동일 ticker 로 여러 번 호출하면 매번 invoke 발생 (renderer 캐시 없음)', async () => {
    mockInvoke.mockResolvedValue({
      ticker: 'AAPL',
      companyName: 'Apple Inc.',
      sector: null,
      active: true,
      basic: null,
      chart30d: [],
      currentPrice: null,
      earningsHistory: [],
      nextEarning: null,
      partial: true,
      ai: null,
    })

    await fetchStockDetail('AAPL')
    await fetchStockDetail('AAPL')

    expect(mockInvoke).toHaveBeenCalledTimes(2)
  })
})
