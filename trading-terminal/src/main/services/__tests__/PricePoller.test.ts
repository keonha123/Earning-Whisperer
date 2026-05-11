import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { BrowserWindow } from 'electron'

import { KisService } from '../KisService'
import { mainState } from '../../store/mainState'
import {
  start,
  stop,
  setHoldings,
  setWatchlist,
  getCachedPrices,
  clearCache,
  __resetForTest,
  __getStateForTest,
} from '../PricePoller'
import { flushMicrotasks } from '../../../test/setup'

vi.mock('../KisService', () => ({
  KisService: {
    getCurrentPrice: vi.fn(),
  },
}))

const getCurrentPriceMock = vi.mocked(KisService.getCurrentPrice)

beforeEach(() => {
  __resetForTest()
  mainState.clear()
  // 디폴트: 모의투자 (paper=true). mainState 의 디폴트 자체가 true 이지만 명시.
  mainState.setPaperTrading(true)
  getCurrentPriceMock.mockReset()
  vi.useFakeTimers()
})

afterEach(() => {
  __resetForTest()
  vi.clearAllTimers()
  vi.useRealTimers()
})

/**
 * tick() 내부의 await 체인을 fake timer 환경에서 끝까지 진행시키기 위한 헬퍼.
 * ticker N개 → await N번 + schedule 까지 안정적으로 흘려 보낸다.
 */
async function flushCycle(n: number): Promise<void> {
  for (let i = 0; i < n + 5; i++) {
    await flushMicrotasks()
  }
}

describe('PricePoller — 사이클 공식', () => {
  it('holdings 3 + watchlist 2 → 첫 tick 에서 5건 모두 호출 + batch 5건 push', async () => {
    getCurrentPriceMock.mockImplementation(async (ticker: string) => {
      const map: Record<string, number> = { A: 10, B: 20, C: 30, D: 40, E: 50 }
      return map[ticker] ?? 0
    })

    setHoldings(['A', 'B', 'C'])
    setWatchlist(['D', 'E'])
    start()

    // schedule(0) → tick — setTimeout 0 만큼 진행 + 사이클 내부 await 모두 흘림.
    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(5)

    expect(getCurrentPriceMock).toHaveBeenCalledTimes(5)
    const calledTickers = getCurrentPriceMock.mock.calls.map((c) => c[0]).sort()
    expect(calledTickers).toEqual(['A', 'B', 'C', 'D', 'E'])

    stop()
  })
})

describe('PricePoller — 부분 0 처리', () => {
  it('단건 0 반환은 batch 제외, 다른 건은 push (cycleFailures 누적되지 않아 정상)', async () => {
    getCurrentPriceMock.mockImplementation(async (ticker: string) => {
      if (ticker === 'B') return 0
      return 100
    })

    setHoldings(['A', 'B', 'C'])
    start()

    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(3)

    expect(getCurrentPriceMock).toHaveBeenCalledTimes(3)
    // A, C 는 정상 가격. B 는 0 → batch 미포함. 부분 실패이므로 consecutiveFailures=0 유지.
    const state = __getStateForTest()
    expect(state.consecutiveFailures).toBe(0)
    expect(state.pausedUntil).toBe(0)

    stop()
  })
})

describe('PricePoller — 연속 실패 가드', () => {
  it('연속 5 cycle 전체 실패 → pausedUntil 미래값 + consecutiveFailures 리셋', async () => {
    // 항상 0 반환 → 모든 cycle 전체 실패 처리.
    getCurrentPriceMock.mockResolvedValue(0)

    setHoldings(['A', 'B'])
    start()

    // cycle 5 회 진행. cycleMs = max(5000, ceil(2 / 0.9 * 1000)) = 5000ms.
    for (let i = 0; i < 5; i++) {
      // 첫 tick 은 schedule(0) 이므로 0ms, 그 이후는 5000ms.
      await vi.advanceTimersByTimeAsync(i === 0 ? 0 : 5000)
      await flushCycle(2)
    }

    const state = __getStateForTest()
    expect(state.pausedUntil).toBeGreaterThan(Date.now())
    expect(state.consecutiveFailures).toBe(0) // pausedUntil 트리거 후 리셋됨

    stop()
  })
})

describe('PricePoller — stop() 캐시 정리 (H7)', () => {
  it('start → tick 1회로 캐시 채워짐 → stop → getCachedPrices() 빈 객체', async () => {
    getCurrentPriceMock.mockResolvedValue(123)

    setHoldings(['A', 'B'])
    start()

    // 첫 tick: 2건 캐시
    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(2)

    const beforeStop = getCachedPrices()
    expect(Object.keys(beforeStop).sort()).toEqual(['A', 'B'])
    expect(beforeStop.A.currentPrice).toBe(123)

    stop()

    // 다른 사용자 로그인 시 이전 ticker 가격 노출 방지 — cache 비어있어야 함
    const afterStop = getCachedPrices()
    expect(afterStop).toEqual({})
  })
})

describe('PricePoller — clearCache (모드 전환)', () => {
  it('clearCache() 후 캐시는 빈 상태이고 running 이면 사이클이 재시작된다', async () => {
    getCurrentPriceMock.mockResolvedValue(123)

    setHoldings(['A', 'B'])
    start()

    // 첫 tick: 2건 캐시
    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(2)
    expect(Object.keys(getCachedPrices()).sort()).toEqual(['A', 'B'])

    // 모드 전환 시뮬레이션 — 새 가격 반환하도록 mock 변경
    getCurrentPriceMock.mockResolvedValue(999)
    clearCache()

    // clearCache 직후 캐시는 비어있어야 함 (옛 모드 가격 노출 방지)
    expect(getCachedPrices()).toEqual({})

    // running 유지 + 새 사이클이 즉시 schedule(0) 으로 시작 → 다음 tick 에 새 가격 채워짐
    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(2)
    const after = getCachedPrices()
    expect(after.A.currentPrice).toBe(999)
    expect(after.B.currentPrice).toBe(999)
  })

  it('running=false 상태에서 clearCache() 는 캐시만 비우고 사이클은 시작하지 않는다', async () => {
    getCurrentPriceMock.mockResolvedValue(123)

    setHoldings(['A'])
    start()
    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(1)
    expect(getCachedPrices().A?.currentPrice).toBe(123)

    stop()
    expect(__getStateForTest().running).toBe(false)

    getCurrentPriceMock.mockClear()
    clearCache()

    expect(getCachedPrices()).toEqual({})
    // 새 사이클이 시작되지 않으므로 mock 호출 없음
    await vi.advanceTimersByTimeAsync(60_000)
    expect(getCurrentPriceMock).not.toHaveBeenCalled()
  })
})

describe('PricePoller — recalcAndRestart (setHoldings 즉시 반영)', () => {
  it('진행 중 setHoldings 호출 시 새 ticker 가 다음 tick 에 즉시 반영', async () => {
    getCurrentPriceMock.mockResolvedValue(100)

    setHoldings(['A'])
    setWatchlist(['B'])
    start()

    // 첫 tick: A, B 호출
    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(2)
    expect(getCurrentPriceMock).toHaveBeenCalledTimes(2)
    const firstCallTickers = getCurrentPriceMock.mock.calls.map((c) => c[0]).sort()
    expect(firstCallTickers).toEqual(['A', 'B'])

    getCurrentPriceMock.mockClear()

    // setHoldings 변경 → recalcAndRestart 가 즉시 schedule(0) 으로 재시작.
    setHoldings(['A', 'C'])

    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(3)

    // A, B, C 3건 호출됨 (변경된 ticker 즉시 반영).
    expect(getCurrentPriceMock).toHaveBeenCalledTimes(3)
    const secondCallTickers = getCurrentPriceMock.mock.calls.map((c) => c[0]).sort()
    expect(secondCallTickers).toEqual(['A', 'B', 'C'])

    stop()
  })
})

describe('PricePoller — C2 cycle cancellation (epoch counter)', () => {
  it('진행 중 사이클 도중 setHoldings → 진행 사이클은 batch push 없이 종료, 새 사이클이 변경된 ticker 로 진행', async () => {
    // BrowserWindow 가 broadcast 대상 — pushToRenderer 호출 카운트로 batch 발신 여부 검증.
    const sendSpy = vi.fn()
    const getAllWindowsMock = vi.mocked(BrowserWindow.getAllWindows)
    getAllWindowsMock.mockReturnValue([
      {
        isDestroyed: () => false,
        webContents: { send: sendSpy },
      } as never,
    ])

    // 첫 ticker(A) 의 await 를 외부에서 풀 수 있도록 deferred Promise 사용.
    let releaseA: ((v: number) => void) | null = null
    const aPromise = new Promise<number>((resolve) => {
      releaseA = resolve
    })
    getCurrentPriceMock.mockImplementation(async (ticker: string) => {
      if (ticker === 'A') return aPromise
      // B/NEW 는 즉시 resolve.
      return 999
    })

    setHoldings(['A', 'B'])
    start()

    // schedule(0) → tick 진입 → A 의 await 에 막혀 대기.
    await vi.advanceTimersByTimeAsync(0)
    await flushMicrotasks()

    // 이 시점에서 사이클 1 은 A 의 await 에 머물러 있음.
    // setHoldings 로 새 ticker 셋 통보 → epoch++ → 사이클 1 은 다음 iteration 에서 종료.
    setHoldings(['NEW'])

    // A await 해제 → 사이클 1 은 epoch mismatch 로 batch push 안 하고 즉시 return.
    releaseA?.(123)
    await flushMicrotasks()

    // 사이클 1 은 batch 발신 안 했어야 한다.
    const updateCallsAfterRelease = sendSpy.mock.calls.filter(
      (c) => c[0] === 'terminal:prices:update',
    )
    expect(updateCallsAfterRelease).toHaveLength(0)

    // 새 사이클 (recalcAndRestart 의 schedule(0)) 진행 — NEW ticker 호출.
    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(1)

    // NEW 호출 확인. (A/B 호출은 이미 사이클 1 에서 발생했을 수 있으나 핵심은 NEW 호출 여부.)
    const calledTickers = getCurrentPriceMock.mock.calls.map((c) => c[0])
    expect(calledTickers).toContain('NEW')

    // 새 사이클 이 정상 batch push 1회 발신.
    const updateCallsAfterNew = sendSpy.mock.calls.filter(
      (c) => c[0] === 'terminal:prices:update',
    )
    expect(updateCallsAfterNew).toHaveLength(1)
    const batch = updateCallsAfterNew[0][1] as { ticker: string }[]
    expect(batch.map((b) => b.ticker)).toEqual(['NEW'])

    stop()
    getAllWindowsMock.mockReturnValue([])
  })

  it('정상 사이클은 epoch 재확인이 batch push 를 막지 않는다', async () => {
    const sendSpy = vi.fn()
    const getAllWindowsMock = vi.mocked(BrowserWindow.getAllWindows)
    getAllWindowsMock.mockReturnValue([
      {
        isDestroyed: () => false,
        webContents: { send: sendSpy },
      } as never,
    ])

    getCurrentPriceMock.mockResolvedValue(50)

    setHoldings(['A', 'B'])
    start()

    await vi.advanceTimersByTimeAsync(0)
    await flushCycle(2)

    // 사이클 도중 외부 변경 없음 → 정상 batch push.
    const updateCalls = sendSpy.mock.calls.filter((c) => c[0] === 'terminal:prices:update')
    expect(updateCalls).toHaveLength(1)
    const batch = updateCalls[0][1] as { ticker: string }[]
    expect(batch.map((b) => b.ticker).sort()).toEqual(['A', 'B'])

    stop()
    getAllWindowsMock.mockReturnValue([])
  })

  it('진행 중 사이클 도중 stop() → 즉시 종료, 이후 schedule 발생 안 함', async () => {
    const sendSpy = vi.fn()
    const getAllWindowsMock = vi.mocked(BrowserWindow.getAllWindows)
    getAllWindowsMock.mockReturnValue([
      {
        isDestroyed: () => false,
        webContents: { send: sendSpy },
      } as never,
    ])

    let releaseA: ((v: number) => void) | null = null
    const aPromise = new Promise<number>((resolve) => {
      releaseA = resolve
    })
    getCurrentPriceMock.mockImplementation(async (ticker: string) => {
      if (ticker === 'A') return aPromise
      return 100
    })

    setHoldings(['A', 'B'])
    start()

    await vi.advanceTimersByTimeAsync(0)
    await flushMicrotasks()

    // 사이클 1 이 A await 에 머무는 동안 stop() 호출.
    stop()

    // A await 해제 → 사이클 1 은 epoch mismatch + running=false 로 즉시 return, batch 미발신.
    releaseA?.(777)
    await flushMicrotasks()

    const updateCalls = sendSpy.mock.calls.filter((c) => c[0] === 'terminal:prices:update')
    expect(updateCalls).toHaveLength(0)

    // 추가 timer 진행해도 새 사이클이 schedule 되지 않아야 함.
    getCurrentPriceMock.mockClear()
    await vi.advanceTimersByTimeAsync(60_000)
    await flushMicrotasks()
    expect(getCurrentPriceMock).not.toHaveBeenCalled()

    getAllWindowsMock.mockReturnValue([])
  })
})
