import { create } from 'zustand'

interface TradingState {
  isSessionActive: boolean
  sessionTicker: string | null

  setSession: (active: boolean, ticker?: string) => void
  /** 로그아웃 시 초기화 (useUserStore.clear() 가 호출). */
  reset: () => void
}

const initialState = {
  isSessionActive: false,
  sessionTicker: null,
}

export const useTradingStore = create<TradingState>((set) => ({
  ...initialState,

  setSession: (active, ticker) =>
    set({
      isSessionActive: active,
      sessionTicker: active && ticker ? ticker : null,
    }),

  reset: () => set({ ...initialState }),
}))
