import { create } from 'zustand'
import { useUserStore } from './useUserStore'

export type TradingMode = 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
export type SignalStatus = 'PENDING' | 'EXECUTED' | 'FAILED' | 'IGNORED' | 'REJECTED'

export interface TradeSignal {
  trade_id: string
  action: 'BUY' | 'SELL'
  /** 서버가 내려준 주문 비율. 실제 수량은 터미널이 현재가·잔고로 산출한다. */
  order_ratio: number
  ticker: string
  ai_score: number
}

export interface SignalFeedItem extends TradeSignal {
  receivedAt: number
  status: SignalStatus
}

export interface TradeResult {
  tradeId: string
  status: 'EXECUTED' | 'PENDING' | 'FAILED'
  orderId: string | null
  executedPrice: number | null
  executedQty: number
  errorMessage: string | null
}

interface TradingState {
  mode: TradingMode
  isForcedManual: boolean
  forcedManualReason: string | null
  activeSignal: TradeSignal | null
  pendingConfirm: TradeSignal | null
  lastExecutedTrade: TradeResult | null
  signalHistory: SignalFeedItem[]
  isSessionActive: boolean
  sessionTicker: string | null

  setMode: (mode: TradingMode) => void
  forceManual: (reason?: string) => void
  clearForcedManual: () => void
  receiveSignal: (signal: TradeSignal) => void
  setPendingConfirm: (signal: TradeSignal | null) => void
  updateSignalStatus: (tradeId: string, status: SignalStatus) => void
  setLastExecutedTrade: (result: TradeResult) => void
  setSession: (active: boolean, ticker?: string) => void
  /** 로그아웃 시 초기화 (useUserStore.clear() 가 호출). */
  reset: () => void
}

const MAX_HISTORY = 50

const initialState = {
  mode: 'MANUAL' as TradingMode,
  isForcedManual: false,
  forcedManualReason: null,
  activeSignal: null,
  pendingConfirm: null,
  lastExecutedTrade: null,
  signalHistory: [],
  isSessionActive: false,
  sessionTicker: null,
}

export const useTradingStore = create<TradingState>((set) => ({
  ...initialState,

  setMode: (mode) => set({ mode }),

  forceManual: (reason = '백엔드 연결이 끊겼습니다.') =>
    set({ mode: 'MANUAL', isForcedManual: true, forcedManualReason: reason }),

  clearForcedManual: () =>
    set({ isForcedManual: false, forcedManualReason: null }),

  receiveSignal: (signal) =>
    set((state) => {
      // 매매 모드의 단일 진실 원천은 useUserStore.settings.tradingMode 다.
      // (로그인 직후 AuthPage 는 setSettings 만 호출하므로 여기서 state.mode 를
      //  읽으면 사용자가 SEMI_AUTO 여도 신호가 IGNORED 로 떨어진다.)
      const mode: TradingMode =
        useUserStore.getState().settings?.tradingMode ?? 'MANUAL'

      const item: SignalFeedItem = {
        ...signal,
        receivedAt: Math.floor(Date.now() / 1000),
        status: mode === 'MANUAL' ? 'IGNORED' : 'PENDING',
      }
      const history = [item, ...state.signalHistory].slice(0, MAX_HISTORY)

      if (mode === 'SEMI_AUTO') {
        return { signalHistory: history, pendingConfirm: signal, activeSignal: signal }
      }
      return { signalHistory: history, activeSignal: signal }
    }),

  setPendingConfirm: (pendingConfirm) => set({ pendingConfirm }),

  updateSignalStatus: (tradeId, status) =>
    set((state) => ({
      signalHistory: state.signalHistory.map((s) =>
        s.trade_id === tradeId ? { ...s, status } : s,
      ),
    })),

  setLastExecutedTrade: (result) => set({ lastExecutedTrade: result }),

  setSession: (active, ticker) =>
    set({
      isSessionActive: active,
      sessionTicker: active && ticker ? ticker : null,
    }),

  reset: () => set({ ...initialState }),
}))
