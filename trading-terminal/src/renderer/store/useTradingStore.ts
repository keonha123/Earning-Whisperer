import { create } from 'zustand'

export type TradingMode = 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
export type SignalStatus = 'PENDING' | 'EXECUTED' | 'FAILED' | 'IGNORED' | 'REJECTED'

export interface TradeSignal {
  trade_id: string
  action: 'BUY' | 'SELL'
  target_qty: number
  ticker: string
  ai_score: number
}

export interface SignalFeedItem extends TradeSignal {
  receivedAt: number
  status: SignalStatus
}

export interface TradeResult {
  tradeId: string
  status: 'EXECUTED' | 'FAILED'
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

  setMode: (mode: TradingMode) => void
  forceManual: (reason?: string) => void
  clearForcedManual: () => void
  receiveSignal: (signal: TradeSignal) => void
  setPendingConfirm: (signal: TradeSignal | null) => void
  updateSignalStatus: (tradeId: string, status: SignalStatus) => void
  setLastExecutedTrade: (result: TradeResult) => void
}

const MAX_HISTORY = 50

export const useTradingStore = create<TradingState>((set) => ({
  mode: 'MANUAL',
  isForcedManual: false,
  forcedManualReason: null,
  activeSignal: null,
  pendingConfirm: null,
  lastExecutedTrade: null,
  signalHistory: [],

  setMode: (mode) => set({ mode }),

  forceManual: (reason = '백엔드 연결이 끊겼습니다.') =>
    set({ mode: 'MANUAL', isForcedManual: true, forcedManualReason: reason }),

  clearForcedManual: () =>
    set({ isForcedManual: false, forcedManualReason: null }),

  receiveSignal: (signal) =>
    set((state) => {
      const item: SignalFeedItem = {
        ...signal,
        receivedAt: Math.floor(Date.now() / 1000),
        status: state.mode === 'MANUAL' ? 'IGNORED' : 'PENDING',
      }
      const history = [item, ...state.signalHistory].slice(0, MAX_HISTORY)

      if (state.mode === 'SEMI_AUTO') {
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
}))
