import { create } from 'zustand'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import type { Sp500Stock } from '../../lib/types/stockList'
import { isIpcError, type IpcErrorCode } from '../../lib/types/ipcError'

interface StockMarketState {
  list: Sp500Stock[]
  isLoaded: boolean
  /** 마지막 불러오기가 실패했으면 그 오류 코드. 실패와 "목록 없음" 을 화면에서 구분하는 데 쓴다. */
  error: IpcErrorCode | null
  loadList: () => Promise<void>
  invalidate: () => void
}

export const useStockMarketStore = create<StockMarketState>((set, get) => ({
  list: [],
  isLoaded: false,
  error: null,

  loadList: async () => {
    if (get().isLoaded) return
    try {
      const list = await ipc.invoke<Sp500Stock[]>(IPC_CHANNELS.STOCKS_SP500_GET)
      set({ list: Array.isArray(list) ? list : [], isLoaded: true, error: null })
    } catch (e) {
      console.error('[useStockMarketStore] SP500 리스트 로드 실패:', e)
      set({ isLoaded: true, error: isIpcError(e) ? e.code : 'UNKNOWN' })
    }
  },

  invalidate: () => set({ isLoaded: false }),
}))
