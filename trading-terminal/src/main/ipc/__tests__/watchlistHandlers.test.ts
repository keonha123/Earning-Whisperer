import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ipcMain, BrowserWindow } from 'electron'

// PricePoller.setWatchlist 호출 검증 — vi.fn 으로 대체.
vi.mock('../../services/PricePoller', () => ({
  setWatchlist: vi.fn(),
}))

// BackendClient mock — getWatchlist + addWatchlist + removeWatchlist.
vi.mock('../../services/BackendClient', () => ({
  BackendClient: {
    getWatchlist: vi.fn(),
    addWatchlist: vi.fn(),
    removeWatchlist: vi.fn(),
  },
}))

import {
  registerWatchlistHandlers,
  start,
  stop,
  __getCacheForTest,
} from '../watchlistHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { BackendClient, type WatchlistItem } from '../../services/BackendClient'
import { setWatchlist as setPricePollerWatchlist } from '../../services/PricePoller'

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

const FIXTURE: WatchlistItem[] = [
  { ticker: 'AAPL', companyName: 'Apple', sector: 'Tech' },
  { ticker: 'MSFT', companyName: 'Microsoft', sector: 'Tech' },
]

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  vi.mocked(BackendClient.getWatchlist).mockReset()
  vi.mocked(BackendClient.addWatchlist).mockReset()
  vi.mocked(BackendClient.removeWatchlist).mockReset()
  vi.mocked(setPricePollerWatchlist).mockReset()
  // BrowserWindow.getAllWindows 디폴트는 [] — 각 테스트에서 필요 시 재정의.
  vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([])
  // stop() 호출로 모듈 캐시/타이머 정리. (PricePoller mock 호출도 발생 → 다음 reset 으로 비움.)
  stop()
  vi.mocked(setPricePollerWatchlist).mockReset()
})

afterEach(() => {
  stop()
  vi.useRealTimers()
})

describe('watchlistHandlers — WATCHLIST_GET', () => {
  it('초기 상태 — 빈 배열 반환', async () => {
    registerWatchlistHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_GET)
    const result = await handler({} as never)

    expect(result).toEqual([])
  })

  it('refresh 후 캐시된 값 반환', async () => {
    vi.mocked(BackendClient.getWatchlist).mockResolvedValue(FIXTURE)
    registerWatchlistHandlers()

    const refreshHandler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REFRESH)
    await refreshHandler({} as never)

    const getHandler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_GET)
    const result = await getHandler({} as never)

    expect(result).toEqual(FIXTURE)
  })
})

describe('watchlistHandlers — WATCHLIST_REFRESH 정상', () => {
  it('백엔드 정상 응답 → 캐시 갱신 + setWatchlist 통보 + WATCHLIST_UPDATE broadcast + 응답으로 동일 데이터', async () => {
    vi.mocked(BackendClient.getWatchlist).mockResolvedValue(FIXTURE)
    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      {
        isDestroyed: () => false,
        webContents: { send: sendSpy },
      } as never,
    ])

    registerWatchlistHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REFRESH)
    const result = await handler({} as never)

    // 응답 = 백엔드 데이터 그대로
    expect(result).toEqual(FIXTURE)
    // 캐시 갱신
    expect(__getCacheForTest().items).toEqual(FIXTURE)
    // PricePoller 통보 — ticker 배열만
    expect(vi.mocked(setPricePollerWatchlist)).toHaveBeenCalledWith(['AAPL', 'MSFT'])
    // BrowserWindow broadcast — WATCHLIST_UPDATE 채널
    const updateCalls = sendSpy.mock.calls.filter(
      (c) => c[0] === IPC_CHANNELS.WATCHLIST_UPDATE,
    )
    expect(updateCalls).toHaveLength(1)
    expect(updateCalls[0][1]).toEqual(FIXTURE)
  })
})

describe('watchlistHandlers — WATCHLIST_REFRESH 백엔드 실패', () => {
  it('getWatchlist throws → console.warn + 캐시 유지 + setWatchlist 미호출 + 마지막 캐시 반환', async () => {
    // 1차: 정상 응답으로 캐시 시드.
    vi.mocked(BackendClient.getWatchlist).mockResolvedValueOnce(FIXTURE)
    registerWatchlistHandlers()
    const refreshHandler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REFRESH)
    await refreshHandler({} as never)
    expect(__getCacheForTest().items).toEqual(FIXTURE)
    // 시드 후 mock clear — 두 번째 호출 검증을 깔끔하게.
    vi.mocked(setPricePollerWatchlist).mockClear()

    // 2차: 실패.
    vi.mocked(BackendClient.getWatchlist).mockRejectedValueOnce(new Error('5xx'))
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    const result = await refreshHandler({} as never)

    // graceful — 마지막 성공 데이터 반환
    expect(result).toEqual(FIXTURE)
    // 캐시 유지
    expect(__getCacheForTest().items).toEqual(FIXTURE)
    // PricePoller 미통보 — 실패 시 ticker 변경 broadcast 안 함
    expect(vi.mocked(setPricePollerWatchlist)).not.toHaveBeenCalled()
    expect(warnSpy).toHaveBeenCalled()

    warnSpy.mockRestore()
  })
})

describe('watchlistHandlers — start/stop lifecycle', () => {
  it('start() — 즉시 1회 fetchAndCache + 5분 setInterval 등록', async () => {
    vi.useFakeTimers()
    vi.mocked(BackendClient.getWatchlist).mockResolvedValue(FIXTURE)

    start()

    // 즉시 1회: 마이크로태스크 흘려보내 fetchAndCache 의 await 진행.
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
    expect(vi.mocked(BackendClient.getWatchlist)).toHaveBeenCalledTimes(1)

    // 5분 진행 → setInterval tick.
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)
    expect(vi.mocked(BackendClient.getWatchlist)).toHaveBeenCalledTimes(2)
  })

  it('stop() — clearInterval + 캐시 비우기 + PricePoller.setWatchlist([]) 통보', async () => {
    vi.useFakeTimers()
    vi.mocked(BackendClient.getWatchlist).mockResolvedValue(FIXTURE)

    start()
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
    expect(__getCacheForTest().items).toEqual(FIXTURE)

    // setWatchlist 호출 카운트 — start 의 fetchAndCache 1회 후 stop 의 [] 통보 = 총 2회.
    vi.mocked(setPricePollerWatchlist).mockClear()

    stop()

    // 캐시 비움 + PricePoller 에 빈 배열 통보
    expect(__getCacheForTest().items).toEqual([])
    expect(vi.mocked(setPricePollerWatchlist)).toHaveBeenCalledWith([])

    // 추가 시간 진행해도 setInterval tick 발생 안 함.
    vi.mocked(BackendClient.getWatchlist).mockClear()
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000)
    expect(vi.mocked(BackendClient.getWatchlist)).not.toHaveBeenCalled()
  })
})

describe('watchlistHandlers — WATCHLIST_ADD', () => {
  it('payload.ticker 누락 → throw + addWatchlist 미호출', async () => {
    registerWatchlistHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_ADD)

    await expect(handler({} as never, undefined)).rejects.toThrow('invalid ticker')
    expect(vi.mocked(BackendClient.addWatchlist)).not.toHaveBeenCalled()
  })

  it('ticker 정규식 불일치 (lowercase) → throw', async () => {
    registerWatchlistHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_ADD)

    await expect(handler({} as never, { ticker: 'aapl' })).rejects.toThrow('invalid ticker')
    expect(vi.mocked(BackendClient.addWatchlist)).not.toHaveBeenCalled()
  })

  it('정상 — addWatchlist 호출 + 캐시 추가 + WATCHLIST_UPDATE broadcast + setWatchlist 통보', async () => {
    const newItem: WatchlistItem = { ticker: 'GOOGL', companyName: 'Alphabet', sector: 'Tech' }
    vi.mocked(BackendClient.addWatchlist).mockResolvedValue(newItem)
    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => false, webContents: { send: sendSpy } } as never,
    ])

    registerWatchlistHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_ADD)
    const result = await handler({} as never, { ticker: 'GOOGL' })

    expect(result).toEqual(newItem)
    expect(vi.mocked(BackendClient.addWatchlist)).toHaveBeenCalledWith('GOOGL')
    expect(__getCacheForTest().items).toEqual([newItem])
    // WATCHLIST_UPDATE broadcast 1회.
    const updateCalls = sendSpy.mock.calls.filter(
      (c) => c[0] === IPC_CHANNELS.WATCHLIST_UPDATE,
    )
    expect(updateCalls).toHaveLength(1)
    expect(updateCalls[0][1]).toEqual([newItem])
    // PricePoller 통보 — 신규 ticker 포함.
    expect(vi.mocked(setPricePollerWatchlist)).toHaveBeenCalledWith(['GOOGL'])
  })

  it('기존 캐시에 추가 — 기존 항목 유지하며 신규 ticker append', async () => {
    // 시드: refresh 로 [AAPL, MSFT] 시드.
    vi.mocked(BackendClient.getWatchlist).mockResolvedValueOnce(FIXTURE)
    registerWatchlistHandlers()
    const refreshHandler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REFRESH)
    await refreshHandler({} as never)
    vi.mocked(setPricePollerWatchlist).mockClear()

    const newItem: WatchlistItem = { ticker: 'NVDA', companyName: 'Nvidia', sector: 'Tech' }
    vi.mocked(BackendClient.addWatchlist).mockResolvedValue(newItem)

    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_ADD)
    await handler({} as never, { ticker: 'NVDA' })

    expect(__getCacheForTest().items).toEqual([...FIXTURE, newItem])
    expect(vi.mocked(setPricePollerWatchlist)).toHaveBeenCalledWith(['AAPL', 'MSFT', 'NVDA'])
  })

  it('addWatchlist throw → handler reject + 캐시 미변경', async () => {
    // 시드 캐시.
    vi.mocked(BackendClient.getWatchlist).mockResolvedValueOnce(FIXTURE)
    registerWatchlistHandlers()
    const refreshHandler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REFRESH)
    await refreshHandler({} as never)
    vi.mocked(setPricePollerWatchlist).mockClear()

    vi.mocked(BackendClient.addWatchlist).mockRejectedValueOnce(new Error('409'))
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_ADD)

    await expect(handler({} as never, { ticker: 'NVDA' })).rejects.toThrow('409')
    // 캐시 미변경 + setWatchlist 미호출.
    expect(__getCacheForTest().items).toEqual(FIXTURE)
    expect(vi.mocked(setPricePollerWatchlist)).not.toHaveBeenCalled()
  })
})

describe('watchlistHandlers — WATCHLIST_REMOVE', () => {
  it('payload.ticker 누락 → throw + removeWatchlist 미호출', async () => {
    registerWatchlistHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REMOVE)

    await expect(handler({} as never, undefined)).rejects.toThrow('invalid ticker')
    expect(vi.mocked(BackendClient.removeWatchlist)).not.toHaveBeenCalled()
  })

  it('ticker 정규식 불일치 (특수문자) → throw', async () => {
    registerWatchlistHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REMOVE)

    await expect(handler({} as never, { ticker: 'AA*PL' })).rejects.toThrow('invalid ticker')
    expect(vi.mocked(BackendClient.removeWatchlist)).not.toHaveBeenCalled()
  })

  it('정상 — removeWatchlist 호출 + 캐시 제거 + broadcast + setWatchlist 통보', async () => {
    // 시드 [AAPL, MSFT].
    vi.mocked(BackendClient.getWatchlist).mockResolvedValueOnce(FIXTURE)
    const sendSpy = vi.fn()
    vi.mocked(BrowserWindow.getAllWindows).mockReturnValue([
      { isDestroyed: () => false, webContents: { send: sendSpy } } as never,
    ])

    registerWatchlistHandlers()
    const refreshHandler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REFRESH)
    await refreshHandler({} as never)
    vi.mocked(setPricePollerWatchlist).mockClear()
    sendSpy.mockClear()

    vi.mocked(BackendClient.removeWatchlist).mockResolvedValue(undefined)
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REMOVE)
    const result = await handler({} as never, { ticker: 'AAPL' })

    expect(result).toBeUndefined()
    expect(vi.mocked(BackendClient.removeWatchlist)).toHaveBeenCalledWith('AAPL')
    // 캐시에서 AAPL 제거.
    expect(__getCacheForTest().items).toEqual([
      { ticker: 'MSFT', companyName: 'Microsoft', sector: 'Tech' },
    ])
    // broadcast.
    const updateCalls = sendSpy.mock.calls.filter(
      (c) => c[0] === IPC_CHANNELS.WATCHLIST_UPDATE,
    )
    expect(updateCalls).toHaveLength(1)
    expect(updateCalls[0][1]).toEqual([{ ticker: 'MSFT', companyName: 'Microsoft', sector: 'Tech' }])
    // PricePoller 통보.
    expect(vi.mocked(setPricePollerWatchlist)).toHaveBeenCalledWith(['MSFT'])
  })

  it('removeWatchlist throw → handler reject + 캐시 미변경', async () => {
    vi.mocked(BackendClient.getWatchlist).mockResolvedValueOnce(FIXTURE)
    registerWatchlistHandlers()
    const refreshHandler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REFRESH)
    await refreshHandler({} as never)
    vi.mocked(setPricePollerWatchlist).mockClear()

    vi.mocked(BackendClient.removeWatchlist).mockRejectedValueOnce(new Error('404'))
    const handler = getRegisteredHandler(IPC_CHANNELS.WATCHLIST_REMOVE)

    await expect(handler({} as never, { ticker: 'AAPL' })).rejects.toThrow('404')
    expect(__getCacheForTest().items).toEqual(FIXTURE)
    expect(vi.mocked(setPricePollerWatchlist)).not.toHaveBeenCalled()
  })
})
