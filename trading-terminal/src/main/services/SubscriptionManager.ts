import { KisWebSocketService, MAX_TICKERS } from './KisWebSocketService'

/**
 * KIS WebSocket 구독 슬롯 관리.
 *
 * 우선순위 (높을수록 한도 내에서 우선 유지):
 *  1. ActiveSession  — Trading Room 진입 종목
 *  2. Holdings       — 현재 보유 종목
 *  3. Earnings(Tier2)— 어닝콜 T-30분 ~ T+60분 구간 종목 (5분 폴링으로 갱신)
 *  4. Watchlist      — 관심 종목
 *
 * MAX_TICKERS(20) 초과 시 낮은 우선순위 ticker 부터 evict.
 */

let activeTicker: string | null = null
let holdingTickers: string[] = []
let earningsTickers: string[] = []
let watchlistTickers: string[] = []
let currentlySubscribed = new Set<string>()

function recompute(): void {
  const desired = new Set<string>()

  if (activeTicker) desired.add(activeTicker)

  for (const t of holdingTickers) {
    if (desired.size >= MAX_TICKERS) break
    desired.add(t)
  }

  for (const t of earningsTickers) {
    if (desired.size >= MAX_TICKERS) break
    desired.add(t)
  }

  for (const t of watchlistTickers) {
    if (desired.size >= MAX_TICKERS) break
    desired.add(t)
  }

  for (const t of currentlySubscribed) {
    if (!desired.has(t)) {
      KisWebSocketService.unsubscribe(t)
      currentlySubscribed.delete(t)
    }
  }

  for (const t of desired) {
    if (!currentlySubscribed.has(t)) {
      KisWebSocketService.subscribe(t)
      currentlySubscribed.add(t)
    }
  }
}

export const SubscriptionManager = {
  setActiveSession(ticker: string | null): void {
    activeTicker = ticker
    recompute()
  },

  setHoldings(tickers: string[]): void {
    holdingTickers = tickers
    recompute()
  },

  /**
   * 어닝콜 T-30분 ~ T+60분 구간 종목 갱신 (5분 폴링 주기로 호출).
   * 빈 배열 전달 시 Tier 2 구독 전부 해제.
   */
  setEarningsTickers(tickers: string[]): void {
    earningsTickers = tickers
    recompute()
  },

  setWatchlist(tickers: string[]): void {
    watchlistTickers = tickers
    recompute()
  },

  reset(): void {
    activeTicker = null
    holdingTickers = []
    earningsTickers = []
    watchlistTickers = []
    currentlySubscribed.clear()
  },
}
