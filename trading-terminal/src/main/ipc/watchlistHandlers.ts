import { BrowserWindow, ipcMain } from 'electron'
import { BackendClient, type WatchlistItem } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { setWatchlist as setPricePollerWatchlist } from '../services/PricePoller'

/**
 * 관심종목 IPC handler.
 *
 * - WATCHLIST_GET (invoke): 모듈 스코프 캐시 반환 (없으면 []).
 * - WATCHLIST_REFRESH (invoke): 백엔드 즉시 재조회 → 캐시 갱신 → broadcast → 호출자에게도 반환.
 * - WATCHLIST_UPDATE (push): 캐시 갱신 시 모든 BrowserWindow 로 broadcast.
 *
 * 동작:
 *  - 5분 주기 자동 폴링 (start/stop 으로 lifecycle 제어).
 *  - 실패 시 console.warn + 캐시 유지 (UI 측은 마지막 성공 데이터 계속 표시).
 *  - 가격 폴링은 이번 작업 범위 외 — Step 5 에서 ticker 목록과 머지 예정.
 */

const POLL_INTERVAL_MS = 5 * 60 * 1000

let cachedWatchlist: WatchlistItem[] = []
let lastFetchAt: number = 0
let pollTimer: NodeJS.Timeout | null = null

function pushToRenderer(channel: string, payload: unknown): void {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (!win.isDestroyed()) win.webContents.send(channel, payload)
  })
}

async function fetchAndCache(): Promise<WatchlistItem[]> {
  const items = await BackendClient.getWatchlist()
  cachedWatchlist = items
  lastFetchAt = Date.now()
  pushToRenderer(IPC_CHANNELS.WATCHLIST_UPDATE, cachedWatchlist)
  setPricePollerWatchlist(cachedWatchlist.map((i) => i.ticker))
  return cachedWatchlist
}

export function registerWatchlistHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.WATCHLIST_GET, (): WatchlistItem[] => {
    return cachedWatchlist
  })

  ipcMain.handle(IPC_CHANNELS.WATCHLIST_REFRESH, async (): Promise<WatchlistItem[]> => {
    try {
      return await fetchAndCache()
    } catch (e) {
      console.warn(
        '[WatchlistHandlers] watchlist sync 실패:',
        e instanceof Error ? e.message : 'unknown error',
      )
      // 캐시 유지 — 호출자에게는 마지막 성공 데이터 반환 (없으면 []).
      return cachedWatchlist
    }
  })
}

/**
 * 5분 주기 자동 동기화 시작. 즉시 1회 + setInterval.
 * 로그인 직후 또는 app ready 시 호출. 토큰 없을 때 실패는 silent (warn only).
 */
export function start(): void {
  if (pollTimer !== null) return

  void (async () => {
    try {
      await fetchAndCache()
    } catch (e) {
      console.warn(
        '[WatchlistHandlers] watchlist sync 실패:',
        e instanceof Error ? e.message : 'unknown error',
      )
    }
  })()

  pollTimer = setInterval(() => {
    void (async () => {
      try {
        await fetchAndCache()
      } catch (e) {
        console.warn(
          '[WatchlistHandlers] watchlist sync 실패:',
          e instanceof Error ? e.message : 'unknown error',
        )
      }
    })()
  }, POLL_INTERVAL_MS)
}

/** 폴링 중지 + 캐시 초기화. 로그아웃/앱 종료 시 호출. */
export function stop(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  cachedWatchlist = []
  lastFetchAt = 0
  setPricePollerWatchlist([])
}

/** 테스트 전용 — 캐시 상태 노출 (production 코드에서는 사용 금지). */
export function __getCacheForTest(): { items: WatchlistItem[]; lastFetchAt: number } {
  return { items: cachedWatchlist, lastFetchAt }
}
