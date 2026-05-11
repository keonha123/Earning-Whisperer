import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

// PricePoller 전체를 mock — 캐시/setHoldings 호출 검증을 위해 spy 가능한 vi.fn 으로 대체.
vi.mock('../../services/PricePoller', () => ({
  getCachedPrices: vi.fn(() => ({})),
  setHoldings: vi.fn(),
}))

// setup.ts 의 axios/electron mock 자동 적용. 이 테스트는 PricePoller mock 만 추가 의존.
import { registerPricesHandlers } from '../pricesHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { getCachedPrices, setHoldings } from '../../services/PricePoller'

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

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  vi.mocked(getCachedPrices).mockReset()
  vi.mocked(setHoldings).mockReset()
  // 디폴트: 빈 캐시 반환.
  vi.mocked(getCachedPrices).mockReturnValue({})
})

describe('pricesHandlers — PRICES_GET', () => {
  it('PricePoller.getCachedPrices() 결과를 그대로 반환', async () => {
    const fixture = {
      AAPL: { currentPrice: 200.5, lastUpdated: 1714400000 },
      MSFT: { currentPrice: 410.1, lastUpdated: 1714400001 },
    }
    vi.mocked(getCachedPrices).mockReturnValue(fixture)

    registerPricesHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.PRICES_GET)
    const result = await handler({} as never)

    expect(result).toEqual(fixture)
    expect(vi.mocked(getCachedPrices)).toHaveBeenCalledTimes(1)
  })

  it('빈 캐시 시 빈 객체 반환', async () => {
    vi.mocked(getCachedPrices).mockReturnValue({})

    registerPricesHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.PRICES_GET)
    const result = await handler({} as never)

    expect(result).toEqual({})
  })
})

describe('pricesHandlers — HOLDINGS_TICKERS_UPDATE', () => {
  it('정상 payload — setHoldings 에 ticker 배열 그대로 전달 + ok 응답', async () => {
    registerPricesHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE)
    const result = await handler({} as never, { tickers: ['AAPL', 'MSFT'] })

    expect(vi.mocked(setHoldings)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(setHoldings)).toHaveBeenCalledWith(['AAPL', 'MSFT'])
    expect(result).toEqual({ ok: true })
  })

  it('빈 배열 — setHoldings([]) 호출 (보유 0개 통보)', async () => {
    registerPricesHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE)
    const result = await handler({} as never, { tickers: [] })

    expect(vi.mocked(setHoldings)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(setHoldings)).toHaveBeenCalledWith([])
    expect(result).toEqual({ ok: true })
  })

  it('비정상 payload — null → setHoldings([]) (graceful)', async () => {
    registerPricesHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE)
    const result = await handler({} as never, null)

    // 현 구현은 Array.isArray 가 아니면 [] 로 graceful 통보.
    expect(vi.mocked(setHoldings)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(setHoldings)).toHaveBeenCalledWith([])
    expect(result).toEqual({ ok: true })
  })

  it('비정상 payload — { tickers: "string" } → setHoldings([]) (graceful)', async () => {
    registerPricesHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE)
    const result = await handler({} as never, { tickers: 'AAPL' as unknown as string[] })

    expect(vi.mocked(setHoldings)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(setHoldings)).toHaveBeenCalledWith([])
    expect(result).toEqual({ ok: true })
  })

  it('비정상 payload — {} → setHoldings([]) (graceful)', async () => {
    registerPricesHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE)
    const result = await handler({} as never, {})

    expect(vi.mocked(setHoldings)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(setHoldings)).toHaveBeenCalledWith([])
    expect(result).toEqual({ ok: true })
  })
})
