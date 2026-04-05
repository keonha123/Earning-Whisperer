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

  setBalance: (cash: number, holdings: Holding[]) => void
  setSyncing: (v: boolean) => void
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  cash: 0,
  holdings: [],
  lastSyncedAt: null,
  isSyncing: false,

  setBalance: (cash, holdings) =>
    set({ cash, holdings, lastSyncedAt: Math.floor(Date.now() / 1000) }),

  setSyncing: (isSyncing) => set({ isSyncing }),
}))
