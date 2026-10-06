import { create } from 'zustand'

interface TradingState {
  isSessionActive: boolean
  sessionTicker: string | null
  /** 이 세션에서 시연 재생을 시작했는지. 메뉴의 열린 콜 자리가 시연 표시를 띄운다. */
  isDemo: boolean

  setSession: (active: boolean, ticker?: string) => void
  setDemo: (isDemo: boolean) => void
  /** 로그아웃 시 초기화 (useUserStore.clear() 가 호출). */
  reset: () => void
}

const initialState = {
  isSessionActive: false,
  sessionTicker: null,
  isDemo: false,
}

export const useTradingStore = create<TradingState>((set, get) => ({
  ...initialState,

  setSession: (active, ticker) => {
    const nextTicker = active && ticker ? ticker : null
    set({
      isSessionActive: active,
      sessionTicker: nextTicker,
      // 다른 종목으로 바뀌거나 세션이 끝나면 시연 표시도 내린다
      isDemo: nextTicker !== null && nextTicker === get().sessionTicker ? get().isDemo : false,
    })
  },

  setDemo: (isDemo) => set({ isDemo }),

  reset: () => set({ ...initialState }),
}))
