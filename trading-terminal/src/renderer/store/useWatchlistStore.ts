import { create } from 'zustand'

/**
 * 관심종목 ticker 항목 — main IPC 응답과 1:1 매핑.
 * 백엔드 record `WatchlistItemResponse(ticker, companyName, sector)` Spring 기본 직렬화 (camelCase).
 *
 * 가격 표시 (currentPrice/dailyChangePercent) 는 이번 작업 범위 외 — Step 5 에서 KIS 가격과 머지.
 */
export interface WatchlistItem {
  ticker: string
  companyName: string
  sector: string
}

interface WatchlistState {
  /** main 캐시에서 받은 ticker 목록. 백엔드 응답 순서를 그대로 보존. */
  items: WatchlistItem[]
  /** 첫 IPC 응답 (성공/빈 배열 무관) 도착 시 true. */
  isLoaded: boolean

  /** main 의 WATCHLIST_GET / WATCHLIST_UPDATE 양쪽에서 호출. 빈 배열도 isLoaded=true 로 마크. */
  setItems: (items: WatchlistItem[]) => void
  /** 로그아웃 시 초기화. */
  reset: () => void
}

export const useWatchlistStore = create<WatchlistState>((set) => ({
  items: [],
  isLoaded: false,
  setItems: (items) => set({ items, isLoaded: true }),
  reset: () => set({ items: [], isLoaded: false }),
}))
