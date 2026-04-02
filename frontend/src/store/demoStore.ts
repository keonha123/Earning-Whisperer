import { create } from "zustand";
import { EmaDataPoint, SignalEntry } from "@/types/demo";

const MAX_TEXT_CHUNKS = 30;
const MAX_EMA_HISTORY = 50;
const MAX_SIGNALS = 20;

interface DemoState {
  // WebSocket 연결 상태
  connected: boolean;

  // AI 이벤트 데이터
  ticker: string;
  currentText: string;
  textHistory: string[];
  rawScore: number;
  emaScore: number;
  emaHistory: EmaDataPoint[];
  signals: SignalEntry[];
  isSessionEnd: boolean;

  // 주가 데이터
  currentPrice: number;
  priceChange: number;
  priceChangePercent: number;

  // 액션
  setConnected: (connected: boolean) => void;
  receiveSignal: (msg: {
    ticker: string;
    text_chunk: string;
    raw_score: number;
    ema_score: number;
    rationale: string;
    action: "BUY" | "SELL" | "HOLD";
    timestamp: number;
    is_session_end: boolean;
  }) => void;
  receivePrice: (msg: {
    price: number;
    change: number;
    change_percent: number;
  }) => void;
  reset: () => void;
}

export const useDemoStore = create<DemoState>((set) => ({
  connected: false,
  ticker: "NVDA",
  currentText: "",
  textHistory: [],
  rawScore: 0,
  emaScore: 0,
  emaHistory: [],
  signals: [],
  isSessionEnd: false,
  currentPrice: 0,
  priceChange: 0,
  priceChangePercent: 0,

  setConnected: (connected) => set({ connected }),

  receiveSignal: (msg) =>
    set((state) => {
      const newHistory = [
        ...state.textHistory,
        msg.text_chunk,
      ].slice(-MAX_TEXT_CHUNKS);

      const newEmaPoint: EmaDataPoint = {
        time: msg.timestamp,
        ema: msg.ema_score,
        raw: msg.raw_score,
      };
      const newEmaHistory = [...state.emaHistory, newEmaPoint].slice(
        -MAX_EMA_HISTORY
      );

      const newSignals =
        msg.action !== "HOLD"
          ? [
              {
                action: msg.action,
                emaScore: msg.ema_score,
                rationale: msg.rationale,
                timestamp: msg.timestamp,
              },
              ...state.signals,
            ].slice(0, MAX_SIGNALS)
          : state.signals;

      return {
        ticker: msg.ticker,
        currentText: msg.text_chunk,
        textHistory: newHistory,
        rawScore: msg.raw_score,
        emaScore: msg.ema_score,
        emaHistory: newEmaHistory,
        signals: newSignals,
        isSessionEnd: msg.is_session_end,
      };
    }),

  receivePrice: (msg) =>
    set({
      currentPrice: msg.price,
      priceChange: msg.change,
      priceChangePercent: msg.change_percent,
    }),

  reset: () =>
    set({
      currentText: "",
      textHistory: [],
      rawScore: 0,
      emaScore: 0,
      emaHistory: [],
      signals: [],
      isSessionEnd: false,
    }),
}));
