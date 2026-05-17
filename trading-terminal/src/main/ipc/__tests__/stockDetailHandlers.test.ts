import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ipcMain } from 'electron'

// BackendClient.getStockDetail 만 mock — 나머지 메서드는 본 테스트 대상 외.
vi.mock('../../services/BackendClient', () => ({
  BackendClient: {
    getStockDetail: vi.fn(),
  },
}))

import {
  registerStockDetailHandlers,
  __resetCacheForTest,
  __getCacheSizeForTest,
} from '../stockDetailHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import {
  BackendClient,
  type StockDetailResponsePayload,
} from '../../services/BackendClient'
import { expectIpcError } from '../../../test/ipcErrorTestUtils'

type IpcInvokeHandler = (
  event: unknown,
  ...args: unknown[]
) => unknown | Promise<unknown>

function getRegisteredHandler(channel: string): IpcInvokeHandler {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find((c) => c[0] === channel)
  if (!call) throw new Error(`channel ${channel} 미등록`)
  return call[1] as IpcInvokeHandler
}

function makeFixture(ticker: string): StockDetailResponsePayload {
  return {
    ticker,
    companyName: `${ticker} Inc.`,
    sector: 'Tech',
    active: true,
    basic: {
      marketCapUsd: 3_000_000_000_000,
      high52w: 250.0,
      low52w: 150.0,
      dividendYield: 0.0049,
    },
    chart30d: [{ date: '2026-04-01', close: 200.5, volume: 12345 }],
    currentPrice: 205.1,
    earningsHistory: [],
    nextEarning: null,
    partial: false,
    ai: null,
  }
}

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  vi.mocked(BackendClient.getStockDetail).mockReset()
  __resetCacheForTest()
})

afterEach(() => {
  __resetCacheForTest()
  vi.useRealTimers()
})

describe('stockDetailHandlers — ticker validation', () => {
  it('payload 가 undefined 면 throw', async () => {
    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expect(handler({} as never, undefined)).rejects.toThrow('invalid ticker')
    expect(vi.mocked(BackendClient.getStockDetail)).not.toHaveBeenCalled()
  })

  it('ticker 가 빈 문자열이면 throw', async () => {
    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expect(handler({} as never, { ticker: '' })).rejects.toThrow('invalid ticker')
    expect(vi.mocked(BackendClient.getStockDetail)).not.toHaveBeenCalled()
  })

  it('ticker 가 lowercase 면 throw (대문자/숫자/.- 만 허용)', async () => {
    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expect(handler({} as never, { ticker: 'aapl' })).rejects.toThrow('invalid ticker')
  })

  it('ticker 가 11자 이상이면 throw', async () => {
    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expect(handler({} as never, { ticker: 'A'.repeat(11) })).rejects.toThrow(
      'invalid ticker',
    )
  })

  it('ticker 가 공백 등 허용 외 문자 포함 시 throw', async () => {
    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expect(handler({} as never, { ticker: 'AA PL' })).rejects.toThrow('invalid ticker')
  })

  it('정규식 위반 시 IpcError code=VALIDATION 으로 분류', async () => {
    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expectIpcError(
      handler({} as never, { ticker: 'aapl' }) as Promise<unknown>,
      'VALIDATION',
      /invalid ticker/,
    )
  })
})

describe('stockDetailHandlers — 캐시 동작', () => {
  it('cache miss → getStockDetail 1회 호출 + 응답 그대로 반환', async () => {
    const fixture = makeFixture('AAPL')
    vi.mocked(BackendClient.getStockDetail).mockResolvedValueOnce(fixture)

    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)
    const result = await handler({} as never, { ticker: 'AAPL' })

    expect(result).toEqual(fixture)
    expect(vi.mocked(BackendClient.getStockDetail)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(BackendClient.getStockDetail)).toHaveBeenCalledWith('AAPL')
    expect(__getCacheSizeForTest()).toBe(1)
  })

  it('30s 이내 재호출 — getStockDetail 추가 호출 없이 캐시 hit', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-01T00:00:00Z'))

    const fixture = makeFixture('AAPL')
    vi.mocked(BackendClient.getStockDetail).mockResolvedValueOnce(fixture)

    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    const first = await handler({} as never, { ticker: 'AAPL' })
    expect(first).toEqual(fixture)

    // TTL 미만 (29s) 진행 후 재호출.
    vi.advanceTimersByTime(29_000)
    const second = await handler({} as never, { ticker: 'AAPL' })

    expect(second).toEqual(fixture)
    expect(vi.mocked(BackendClient.getStockDetail)).toHaveBeenCalledTimes(1)
  })

  it('30s 만료 후 재호출 — getStockDetail 1회 추가 호출 + 새 응답 캐시', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-01T00:00:00Z'))

    const first = makeFixture('AAPL')
    const second = { ...makeFixture('AAPL'), currentPrice: 210.0 }
    vi.mocked(BackendClient.getStockDetail)
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second)

    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await handler({} as never, { ticker: 'AAPL' })
    // TTL 초과 — 30_001ms 진행.
    vi.advanceTimersByTime(30_001)
    const result = await handler({} as never, { ticker: 'AAPL' })

    expect(result).toEqual(second)
    expect(vi.mocked(BackendClient.getStockDetail)).toHaveBeenCalledTimes(2)
  })

  it('다른 ticker 는 독립 캐시 — 각각 1회씩 호출', async () => {
    const aapl = makeFixture('AAPL')
    const msft = makeFixture('MSFT')
    vi.mocked(BackendClient.getStockDetail).mockImplementation(async (t: string) => {
      if (t === 'AAPL') return aapl
      if (t === 'MSFT') return msft
      throw new Error('unexpected')
    })

    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    const r1 = await handler({} as never, { ticker: 'AAPL' })
    const r2 = await handler({} as never, { ticker: 'MSFT' })
    // AAPL 재요청 — 캐시 hit.
    const r3 = await handler({} as never, { ticker: 'AAPL' })

    expect(r1).toEqual(aapl)
    expect(r2).toEqual(msft)
    expect(r3).toEqual(aapl)
    expect(vi.mocked(BackendClient.getStockDetail)).toHaveBeenCalledTimes(2)
    expect(__getCacheSizeForTest()).toBe(2)
  })
})

describe('stockDetailHandlers — 백엔드 에러 propagate', () => {
  it('getStockDetail throw — handler 가 그대로 reject + 캐시 미저장', async () => {
    vi.mocked(BackendClient.getStockDetail).mockRejectedValueOnce(new Error('500'))

    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expect(handler({} as never, { ticker: 'AAPL' })).rejects.toThrow('500')
    // 캐시에 저장 안 됨 — 다음 호출이 다시 백엔드 시도.
    expect(__getCacheSizeForTest()).toBe(0)
  })

  it('1차 throw 후 2차 정상 — 정상 응답 캐시', async () => {
    vi.mocked(BackendClient.getStockDetail)
      .mockRejectedValueOnce(new Error('503'))
      .mockResolvedValueOnce(makeFixture('AAPL'))

    registerStockDetailHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.STOCK_GET_DETAIL)

    await expect(handler({} as never, { ticker: 'AAPL' })).rejects.toThrow('503')
    const second = await handler({} as never, { ticker: 'AAPL' })

    expect(second).toEqual(makeFixture('AAPL'))
    expect(vi.mocked(BackendClient.getStockDetail)).toHaveBeenCalledTimes(2)
    expect(__getCacheSizeForTest()).toBe(1)
  })
})
