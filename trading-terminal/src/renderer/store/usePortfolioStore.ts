import { create } from 'zustand'

export interface Holding {
  ticker: string
  qty: number
  avgPrice: number
  currentPrice: number
}

interface PortfolioState {
  cash: number
  holdings: Holding[]
  lastSyncedAt: number | null
  isSyncing: boolean
  error: string | null

  setBalance: (cash: number, holdings: Holding[]) => void
  startSync: () => void
  setSyncing: (v: boolean) => void
  setError: (msg: string | null) => void
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  cash: 0,
  holdings: [],
  lastSyncedAt: null,
  isSyncing: false,
  error: null,

  setBalance: (cash, holdings) =>
    set({ cash, holdings, lastSyncedAt: Math.floor(Date.now() / 1000), error: null }),

  startSync: () => set({ isSyncing: true, error: null }),

  setSyncing: (isSyncing) => set({ isSyncing }),

  setError: (error) => set({ error }),
}))
