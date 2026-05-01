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
const TICKER_PATTERN = /^[A-Z0-9.\-]{1,10}$/

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
  // PricePoller 통보를 broadcast 보다 먼저 수행 — renderer 가 WATCHLIST_UPDATE 수신 직후
  // PRICES_GET 으로 가격을 묻는 시점에 PricePoller 가 신규 ticker 를 이미 폴링 대상에 포함하고
  // 있어야 빈 가격 노출이 줄어든다. 두 호출 모두 동기지만 향후 비동기화 가능성 대비.
  setPricePollerWatchlist(cachedWatchlist.map((i) => i.ticker))
  pushToRenderer(IPC_CHANNELS.WATCHLIST_UPDATE, cachedWatchlist)
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

  /**
   * 관심종목 추가 — POST /api/v1/watchlist body { ticker }.
   * - ticker 정규식 검증 실패 시 throw 'invalid ticker' (Electron reject).
   * - 백엔드 정상 응답 → 캐시 갱신 + WATCHLIST_UPDATE broadcast +
   *   PricePoller.setWatchlist 통보 (신규 ticker 폴링 시작).
   * - 백엔드 throw 는 catch 하지 않고 그대로 propagate
   *   (UI 가 토스트 등으로 사용자에게 노출).
   */
  ipcMain.handle(
    IPC_CHANNELS.WATCHLIST_ADD,
    async (_e, payload: { ticker: string } | undefined): Promise<WatchlistItem> => {
      const ticker = payload?.ticker
      if (typeof ticker !== 'string' || !TICKER_PATTERN.test(ticker)) {
        throw new Error('invalid ticker')
      }

      const item = await BackendClient.addWatchlist(ticker)

      // 중복 ticker 가 캐시에 이미 있는 경우 (백엔드가 idempotent 응답) 덮어쓰기.
      const idx = cachedWatchlist.findIndex((w) => w.ticker === item.ticker)
      if (idx >= 0) {
        cachedWatchlist = [...cachedWatchlist.slice(0, idx), item, ...cachedWatchlist.slice(idx + 1)]
      } else {
        cachedWatchlist = [...cachedWatchlist, item]
      }
      lastFetchAt = Date.now()
      // PricePoller 통보 → broadcast 순서. 신규 ticker 가 폴링 대상에 등록된 후에
      // renderer 가 WATCHLIST_UPDATE 를 받도록 보장.
      setPricePollerWatchlist(cachedWatchlist.map((i) => i.ticker))
      pushToRenderer(IPC_CHANNELS.WATCHLIST_UPDATE, cachedWatchlist)
      return item
    },
  )

  /**
   * 관심종목 제거 — DELETE /api/v1/watchlist/{ticker}.
   * - ticker 정규식 검증 실패 시 throw.
   * - 백엔드 정상 응답 → 캐시에서 ticker 제거 + broadcast + PricePoller 통보.
   * - 캐시에 없던 ticker 라도 idempotent 하게 진행.
   */
  ipcMain.handle(
    IPC_CHANNELS.WATCHLIST_REMOVE,
    async (_e, payload: { ticker: string } | undefined): Promise<void> => {
      const ticker = payload?.ticker
      if (typeof ticker !== 'string' || !TICKER_PATTERN.test(ticker)) {
        throw new Error('invalid ticker')
      }

      await BackendClient.removeWatchlist(ticker)

      cachedWatchlist = cachedWatchlist.filter((w) => w.ticker !== ticker)
      lastFetchAt = Date.now()
      // PricePoller 통보 → broadcast 순서로 일관성 유지 (add/refresh 와 동일 패턴).
      setPricePollerWatchlist(cachedWatchlist.map((i) => i.ticker))
      pushToRenderer(IPC_CHANNELS.WATCHLIST_UPDATE, cachedWatchlist)
    },
  )
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
