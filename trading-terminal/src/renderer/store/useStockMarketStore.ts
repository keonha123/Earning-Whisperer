import { create } from 'zustand'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import type { Sp500Stock } from '../../lib/types/stockList'

interface StockMarketState {
  list: Sp500Stock[]
  isLoaded: boolean
  loadList: () => Promise<void>
  invalidate: () => void
}

export const useStockMarketStore = create<StockMarketState>((set, get) => ({
  list: [],
  isLoaded: false,

  loadList: async () => {
    if (get().isLoaded) return
    try {
      const list = await ipc.invoke<Sp500Stock[]>(IPC_CHANNELS.STOCKS_SP500_GET)
      set({ list: Array.isArray(list) ? list : [], isLoaded: true })
    } catch (e) {
      console.error('[useStockMarketStore] SP500 리스트 로드 실패:', e)
      set({ isLoaded: true })
    }
  },

  invalidate: () => set({ isLoaded: false }),
}))
