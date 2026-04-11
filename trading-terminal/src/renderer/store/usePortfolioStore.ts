import { create } from 'zustand'

export interface Holding {
  ticker: string
  qty: number
  avgPrice: number
  currentPrice: number
}

interface PortfolioState {
  orderableCash: number  // 즉시 주문가능 외화금액
  totalCash: number      // 외화 총 보유금액 (포트폴리오 표시용)
  holdings: Holding[]
  lastSyncedAt: number | null
  isSyncing: boolean
  error: string | null

  setBalance: (orderableCash: number, totalCash: number, holdings: Holding[]) => void
  startSync: () => void
  setSyncing: (v: boolean) => void
  setError: (msg: string | null) => void
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  orderableCash: 0,
  totalCash: 0,
  holdings: [],
  lastSyncedAt: null,
  isSyncing: false,
  error: null,

  setBalance: (orderableCash, totalCash, holdings) =>
    set({ orderableCash, totalCash, holdings, lastSyncedAt: Math.floor(Date.now() / 1000), error: null }),

  startSync: () => set({ isSyncing: true, error: null }),

  setSyncing: (isSyncing) => set({ isSyncing }),

  setError: (error) => set({ error }),
}))
