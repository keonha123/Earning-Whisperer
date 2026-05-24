import { BrowserWindow } from 'electron'
import { KisService } from './KisService'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import type { PriceUpdate } from '../../lib/priceTypes'

/**
 * 관심종목 + 보유종목 시세 폴링 서비스.
 *
 * 책임:
 *  - holdings ∪ watchlist 의 ticker 집합에 대해 KisService.getCurrentPrice 사이클 호출
 *  - 사이클당 1회 batch 로 Renderer 에 PRICES_UPDATE push
 *  - 모의/실전 rate (1.5 / 18 req/s) 기준 LOW 예산 60% 사용 사이클 산출
 *  - 연속 5회 사이클 전체 실패 시 30초 일시중단
 *
 * 외부 진입점:
 *  - start() / stop() — lifecycle
 *  - setHoldings(tickers) / setWatchlist(tickers) — ticker 갱신
 *  - recalcAndRestart() — 진행 중 cycle cancel + 즉시 재실행
 *  - getCachedPrices() — Renderer 초기 로드용 마지막 batch 스냅샷
 */

/**
 * 내부 캐시/배치 단건. 공유 정의(`src/lib/priceTypes.ts`)의 PriceUpdate 와 동일 형태
 *  (ticker + PriceEntry 필드) 를 사용한다.
 */
type PriceEntry = PriceUpdate

const PAUSE_MS = 30_000
const MAX_CONSECUTIVE_FAILURES = 5
const IDLE_CYCLE_MS = 30_000
const MIN_CYCLE_MS = 5_000
const OFF_HOURS_CYCLE_MS = 180_000

function isUsMarketOpen(): boolean {
  const now = new Date()
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
    hour: 'numeric',
    minute: 'numeric',
    hour12: false,
  }).formatToParts(now)
  const weekday = parts.find((p) => p.type === 'weekday')?.value
  if (weekday === 'Sat' || weekday === 'Sun') return false
  const hour = parseInt(parts.find((p) => p.type === 'hour')?.value ?? '0')
  const minute = parseInt(parts.find((p) => p.type === 'minute')?.value ?? '0')
  const total = hour * 60 + minute
  return total >= 9 * 60 + 30 && total < 16 * 60
}

let currentHoldings: string[] = []
let currentWatchlist: string[] = []
let tickers: Set<string> = new Set<string>()
const cache: Map<string, PriceEntry> = new Map()

let cycleTimer: NodeJS.Timeout | null = null
let running = false
let consecutiveFailures = 0
let pausedUntil = 0
/**
 * 진행 중 사이클 cancellation 용 epoch.
 * tick 진입 시 캡처된 myEpoch 와 currentCycleEpoch 가 다르면 사이클이 외부에서 무효화됨.
 *  - recalcAndRestart() / stop() 가 currentCycleEpoch++ 하여 진행 중 tick 을 중단.
 *  - 한 사이클 내 await 직후마다 재확인 → KIS rate limit 사이클 중첩 방지.
 */
let currentCycleEpoch = 0
const stompCoveredTickers = new Set<string>()

function pushToRenderer(channel: string, payload: unknown): void {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

function recomputeTickers(): void {
  const next = new Set<string>()
  for (const t of currentHoldings) if (t) next.add(t)
  for (const t of currentWatchlist) if (t) next.add(t)
  tickers = next
}

function computeCycleMs(): number {
  const n = tickers.size
  if (n === 0) return IDLE_CYCLE_MS
  if (!isUsMarketOpen()) return OFF_HOURS_CYCLE_MS
  const safeRate = mainState.isPaperTrading ? 1.0 : 18
  const lowBudget = safeRate * 0.6
  return Math.max(MIN_CYCLE_MS, Math.ceil((n / lowBudget) * 1000))
}

function clearCycleTimer(): void {
  if (cycleTimer !== null) {
    clearTimeout(cycleTimer)
    cycleTimer = null
  }
}

function schedule(ms: number): void {
  clearCycleTimer()
  cycleTimer = setTimeout(() => {
    void tick()
  }, ms)
}

async function tick(): Promise<void> {
  if (!running) return
  // 사이클 epoch 캡처 — 진행 중 setHoldings/setWatchlist/stop 호출 시 epoch 증가로 cancel 감지.
  const myEpoch = ++currentCycleEpoch
  if (Date.now() < pausedUntil) {
    schedule(IDLE_CYCLE_MS)
    return
  }
  if (tickers.size === 0) {
    schedule(IDLE_CYCLE_MS)
    return
  }
  const batch: PriceEntry[] = []
  let cycleFailures = 0
  const snapshot = Array.from(tickers)

  for (const ticker of snapshot) {
    // 매 iteration 직전 epoch / running 재확인 — 사이클이 외부에서 무효화됐으면 즉시 종료.
    // batch push / pause 판정 / schedule 모두 skip → 새 사이클이 깨끗하게 시작되도록 함.
    if (myEpoch !== currentCycleEpoch || !running) return
    if (stompCoveredTickers.has(ticker)) continue
    try {
      const result = await KisService.getCurrentPrice(ticker)
      if (result.currentPrice > 0) {
        const entry: PriceEntry = {
          ticker,
          currentPrice: result.currentPrice,
          previousClose: result.previousClose,
          lastUpdated: Date.now(),
        }
        batch.push(entry)
        cache.set(ticker, entry)
      } else {
        cycleFailures++
      }
    } catch (e) {
      console.warn('[PricePoller]', ticker, e instanceof Error ? e.message : e)
      cycleFailures++
    }
  }

  // 사이클 정상 완료 시점에서도 한 번 더 epoch 재확인 — 마지막 await 직후 cancel 가능.
  if (myEpoch !== currentCycleEpoch || !running) return

  if (batch.length > 0) {
    pushToRenderer(IPC_CHANNELS.PRICES_UPDATE, batch)
  }

  if (snapshot.length > 0 && cycleFailures === snapshot.length) {
    consecutiveFailures++
  } else {
    consecutiveFailures = 0
  }

  if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
    pausedUntil = Date.now() + PAUSE_MS
    consecutiveFailures = 0
    console.warn('[PricePoller] 연속 5회 실패 — 30초 일시중단')
  }

  if (running) schedule(computeCycleMs())
}

export function start(): void {
  if (running) return
  running = true
  consecutiveFailures = 0
  pausedUntil = 0
  schedule(0)
}

export function stop(): void {
  running = false
  // 진행 중 tick 즉시 break — 다음 await 후 epoch mismatch 로 종료.
  currentCycleEpoch++
  clearCycleTimer()
  consecutiveFailures = 0
  pausedUntil = 0
  // 다른 사용자 로그인 시 이전 ticker 가격이 노출되지 않도록 캐시 강제 비움
  cache.clear()
}

export function recalcAndRestart(): void {
  if (!running) return
  // epoch 증가 → 진행 중 사이클은 다음 await 후 batch push 없이 종료.
  // 그 후 schedule(0) 으로 새 사이클 즉시 시작.
  currentCycleEpoch++
  clearCycleTimer()
  schedule(0)
}

/**
 * 모드 전환 등으로 옛 baseURL 의 가격이 더이상 유효하지 않을 때 호출.
 * 캐시를 비우고 진행 중 사이클을 cancel 한다 (running 이면 새 사이클 즉시 시작).
 * stop() 과 달리 running 자체는 유지하여 모드 전환 흐름 단순화.
 */
export function clearCache(): void {
  cache.clear()
  if (running) {
    currentCycleEpoch++
    clearCycleTimer()
    schedule(0)
  }
}

export function setHoldings(holdings: string[]): void {
  const sorted = [...holdings].sort()
  if (
    sorted.length === currentHoldings.length &&
    sorted.every((t, i) => t === currentHoldings[i])
  ) {
    return
  }
  currentHoldings = sorted
  recomputeTickers()
  recalcAndRestart()
}

export function setWatchlist(watchlist: string[]): void {
  const sorted = [...watchlist].sort()
  if (
    sorted.length === currentWatchlist.length &&
    sorted.every((t, i) => t === currentWatchlist[i])
  ) {
    return
  }
  currentWatchlist = sorted
  recomputeTickers()
  recalcAndRestart()
}

export function getCachedPrices(): Record<string, { currentPrice: number; previousClose: number; lastUpdated: number }> {
  const result: Record<string, { currentPrice: number; previousClose: number; lastUpdated: number }> = {}
  for (const [ticker, entry] of cache.entries()) {
    result[ticker] = { currentPrice: entry.currentPrice, previousClose: entry.previousClose, lastUpdated: entry.lastUpdated }
  }
  return result
}

/** STOMP로 수신된 ticker를 covered로 등록 — KIS 폴링 스킵 대상. */
export function markStompCovered(tickers: string[]): void {
  for (const t of tickers) stompCoveredTickers.add(t)
}

/** STOMP 끊김 시 호출 — KIS fallback 재개. */
export function clearStompCovered(): void {
  stompCoveredTickers.clear()
  if (running) recalcAndRestart()
}

/** 테스트 전용 — 내부 상태 초기화. */
export function __resetForTest(): void {
  stop()
  currentHoldings = []
  currentWatchlist = []
  tickers = new Set<string>()
  cache.clear()
}

/** 테스트 전용 — 내부 상태 노출. */
export function __getStateForTest(): {
  running: boolean
  pausedUntil: number
  consecutiveFailures: number
  tickers: string[]
} {
  return {
    running,
    pausedUntil,
    consecutiveFailures,
    tickers: Array.from(tickers),
  }
}
