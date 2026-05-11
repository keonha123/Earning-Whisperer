import { create } from 'zustand'

/**
 * 글로벌 시장 지수 5종 (SPX/NDX/VIX/DXY/10Y) 클라이언트 상태.
 *
 * Backend Contract 4.4 (STOMP /topic/market/indices push) /
 *               7.7 (REST GET /api/v1/market/indices 초기 스냅샷) 와 1:1 매핑.
 * snake_case (`change_percent`) 는 hook 계층에서 camelCase 로 변환된 뒤 들어온다.
 */
export interface MarketIndexItem {
  /** 표시 심볼 (예: "SPX", "NDX", "VIX", "DXY", "10Y"). */
  symbol: string
  /** 미포맷 가격값 (지수 수치 또는 % 원본값). */
  price: number
  /** 등락률(%) — 양수=상승, 음수=하락. */
  changePercent: number
  /** pip 색 결정용 트렌드. */
  trend: 'up' | 'down' | 'neutral'
  /** 가격 표시 포맷터 (지수 / 퍼센트). */
  format: 'index' | 'percent'
  /** 백엔드가 보낸 epoch seconds (또는 ms — 백엔드 정의 그대로 사용). */
  timestamp: number
}

interface MarketIndicesState {
  /** symbol 알파벳 정렬을 유지하는 5종 지수 배열. */
  indices: MarketIndexItem[]
  /** 가장 최근에 갱신된 데이터의 timestamp (양수만 반영, 단조 증가). */
  lastUpdatedAt: number | null
  /** REST/STOMP 어느 쪽이든 첫 데이터 도착 시 true. 빈 배열 setIndices 는 false 유지. */
  isLoaded: boolean

  /** REST 초기 스냅샷용 — 배열 통째 교체. 비어있으면 isLoaded=false 유지. */
  setIndices: (items: MarketIndexItem[]) => void
  /** STOMP 단건 push 용 — symbol 매칭 후 교체 / 없으면 append + 정렬 유지. */
  upsertIndex: (item: MarketIndexItem) => void
  /** 로그아웃/연결 해제 시 초기화. */
  reset: () => void
}

function sortBySymbol(items: MarketIndexItem[]): MarketIndexItem[] {
  // locale 명시 — 환경별 ICU 차이로 인한 정렬 비결정성 방지.
  return [...items].sort((a, b) => a.symbol.localeCompare(b.symbol, 'en'))
}

export const useMarketIndicesStore = create<MarketIndicesState>((set) => ({
  indices: [],
  lastUpdatedAt: null,
  isLoaded: false,

  setIndices: (items) =>
    set((state) => {
      if (items.length === 0) {
        // Contract 7.7: 빈 캐시 시 200 [] — placeholder 유지를 위해 isLoaded=false.
        return { indices: [], lastUpdatedAt: null, isLoaded: false }
      }
      const sorted = sortBySymbol(items)
      const latest = sorted.reduce(
        (acc, it) => (it.timestamp > acc ? it.timestamp : acc),
        0,
      )
      // timestamp > 0 일 때만 lastUpdatedAt 갱신, 단조 증가 (역행 방지).
      const nextLastUpdatedAt =
        latest > 0
          ? Math.max(state.lastUpdatedAt ?? 0, latest)
          : state.lastUpdatedAt
      return {
        indices: sorted,
        lastUpdatedAt: nextLastUpdatedAt,
        isLoaded: true,
      }
    }),

  upsertIndex: (item) =>
    set((state) => {
      const idx = state.indices.findIndex((i) => i.symbol === item.symbol)
      const existing = idx >= 0 ? state.indices[idx] : undefined

      // Stale-drop: out-of-order push 무시 (양쪽 모두 양수 timestamp 이고 신규가 더 과거).
      if (
        existing &&
        item.timestamp > 0 &&
        existing.timestamp > 0 &&
        item.timestamp < existing.timestamp
      ) {
        return state
      }

      let next: MarketIndexItem[]
      if (idx >= 0) {
        next = [...state.indices]
        next[idx] = item
      } else {
        next = [...state.indices, item]
      }
      // 정렬 결정성: append/replace 모두 항상 sortBySymbol 적용.
      next = sortBySymbol(next)

      // timestamp > 0 일 때만 lastUpdatedAt 갱신, 단조 증가.
      const nextLastUpdatedAt =
        item.timestamp > 0
          ? Math.max(state.lastUpdatedAt ?? 0, item.timestamp)
          : state.lastUpdatedAt

      return {
        indices: next,
        lastUpdatedAt: nextLastUpdatedAt,
        isLoaded: true,
      }
    }),

  reset: () => set({ indices: [], lastUpdatedAt: null, isLoaded: false }),
}))
