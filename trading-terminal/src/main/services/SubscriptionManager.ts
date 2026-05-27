import { KisWebSocketService, MAX_TICKERS } from './KisWebSocketService'

/**
 * KIS WebSocket 구독 슬롯 관리.
 * 우선순위: 1=ActiveSession ticker, 2=Holdings, 3=Watchlist
 * MAX_TICKERS(20) 초과 시 낮은 우선순위 ticker 부터 evict.
 */

let activeTicker: string | null = null
let holdingTickers: string[] = []
let watchlistTickers: string[] = []
let currentlySubscribed = new Set<string>()

function recompute(): void {
  const desired = new Set<string>()

  // Priority 1: active session ticker
  if (activeTicker) desired.add(activeTicker)

  // Priority 2: holdings
  for (const t of holdingTickers) {
    if (desired.size >= MAX_TICKERS) break
    desired.add(t)
  }

  // Priority 3: watchlist
  for (const t of watchlistTickers) {
    if (desired.size >= MAX_TICKERS) break
    desired.add(t)
  }

  // Unsubscribe tickers no longer needed
  for (const t of currentlySubscribed) {
    if (!desired.has(t)) {
      KisWebSocketService.unsubscribe(t)
      currentlySubscribed.delete(t)
    }
  }

  // Subscribe new tickers
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

  setWatchlist(tickers: string[]): void {
    watchlistTickers = tickers
    recompute()
  },

  reset(): void {
    activeTicker = null
    holdingTickers = []
    watchlistTickers = []
    currentlySubscribed.clear()
  },
}
