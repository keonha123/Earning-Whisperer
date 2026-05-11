import { create } from 'zustand'
import type { PriceEntry, PriceUpdate } from '../../lib/priceTypes'

/**
 * 시세 폴링 캐시 단건 — main 의 PricePoller 가 KIS 시세를 ticker 별로 캐싱한 결과.
 *
 * - currentPrice: KIS 응답 그대로의 외화 가격 (USD).
 * - lastUpdated: main 폴링 사이클에서 기록한 epoch (ms 또는 sec — main 정의 그대로 보존).
 *
 * Step 5 main-side 가 정의한 IPC 페이로드와 1:1 매핑.
 *
 * 타입 정의는 `src/lib/priceTypes.ts` 로 중앙화 — main/renderer 간 silent drift 방지.
 */
export type { PriceEntry } from '../../lib/priceTypes'

interface PricesState {
  /** ticker → 최신 시세. 없으면 폴러가 아직 가격을 받지 못한 상태. */
  prices: Record<string, PriceEntry>
  /** 첫 IPC 응답(빈 객체 포함) 도착 시 true. */
  isLoaded: boolean

  /** PRICES_GET 응답 처리용 — 통째 교체 + isLoaded=true. */
  setSnapshot: (snapshot: Record<string, PriceEntry>) => void
  /**
   * PRICES_UPDATE broadcast 처리용 — ticker 키로 머지.
   * 폴러가 항상 사이클 단위 최신값을 보내므로 변경 발견 시에만 새 객체 생성.
   *
   * Reference equality 보존:
   *  - 빈 batch & isLoaded=true → state 그대로 반환 (re-render skip)
   *  - 모든 ticker 가 prev 와 동일 (currentPrice/lastUpdated) → state 그대로 반환
   *  - 일부만 변경 → 변경된 ticker 만 갱신한 새 prices 반환 (나머지 entry reference 유지)
   */
  upsertBatch: (batch: PriceUpdate[]) => void
}

export const usePricesStore = create<PricesState>((set) => ({
  prices: {},
  isLoaded: false,

  setSnapshot: (snapshot) => set({ prices: { ...snapshot }, isLoaded: true }),

  upsertBatch: (batch) =>
    set((state) => {
      if (!batch || batch.length === 0) {
        // batch 비어도 isLoaded 는 true 로 마크 (폴러 응답 자체는 도달).
        return state.isLoaded ? state : { ...state, isLoaded: true }
      }

      let working: Record<string, PriceEntry> = state.prices
      let changed = false

      for (const entry of batch) {
        const prev = working[entry.ticker]
        if (
          !prev ||
          prev.currentPrice !== entry.currentPrice ||
          prev.previousClose !== entry.previousClose ||
          prev.lastUpdated !== entry.lastUpdated
        ) {
          if (!changed) {
            // 첫 변경 시점에 prices 객체를 새로 복제 (lazy clone).
            working = { ...state.prices }
            changed = true
          }
          working[entry.ticker] = {
            currentPrice: entry.currentPrice,
            previousClose: entry.previousClose,
            lastUpdated: entry.lastUpdated,
          }
        }
      }

      if (!changed) {
        // 모든 ticker 가 동일 값 — prices reference 보존, isLoaded 만 보정.
        return state.isLoaded ? state : { ...state, isLoaded: true }
      }
      return { prices: working, isLoaded: true }
    }),
}))
