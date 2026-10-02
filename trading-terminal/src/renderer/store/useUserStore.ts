import { create } from 'zustand'
import { useMarketIndicesStore } from './useMarketIndicesStore'
import { useTradingStore } from './useTradingStore'
import { usePortfolioStore } from './usePortfolioStore'
import { useWatchlistStore } from './useWatchlistStore'
import { usePricesStore } from './usePricesStore'
import { useTranscriptStore } from './useTranscriptStore'
import { useDrawerStore } from './useDrawerStore'

export type UserPlan = 'FREE' | 'PRO'
export type AccountType = 'KIS_REAL' | 'KIS_PAPER' | 'SELF_PAPER'

export interface UserSettings {
  tradingMode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
  maxBuyRatio: number
  maxHoldingRatio: number
  cooldownMinutes: number
  /** AI 매매 신호 임계치 (0.0 ~ 1.0). 점수가 이 값 이상일 때만 신호 발동. */
  aiScoreThreshold: number
}

interface UserState {
  userId: number | null
  email: string | null
  nickname: string | null
  plan: UserPlan
  settings: UserSettings
  accountType: AccountType | null

  setUser: (user: { id: number; email: string; nickname: string; role: string }) => void
  setSettings: (settings: Partial<UserSettings>) => void
  setAiScoreThreshold: (value: number) => void
  setAccountType: (accountType: AccountType) => void
  clear: () => void
}

const defaultSettings: UserSettings = {
  tradingMode: 'MANUAL',
  maxBuyRatio: 0.1,
  maxHoldingRatio: 0.3,
  cooldownMinutes: 5,
  aiScoreThreshold: 0.6,
}

export const useUserStore = create<UserState>((set) => ({
  userId: null,
  email: null,
  nickname: null,
  plan: 'FREE',
  settings: defaultSettings,
  accountType: null,

  setUser: (user) =>
    set({
      userId: user.id,
      email: user.email,
      nickname: user.nickname,
      plan: user.role === 'PRO' ? 'PRO' : 'FREE',
    }),

  setSettings: (partial) =>
    set((state) => ({ settings: { ...state.settings, ...partial } })),

  setAiScoreThreshold: (value) =>
    set((state) => ({ settings: { ...state.settings, aiScoreThreshold: value } })),

  setAccountType: (accountType) => set({ accountType }),

  clear: () => {
    set({
      userId: null,
      email: null,
      nickname: null,
      plan: 'FREE',
      settings: defaultSettings,
      accountType: null,
    })
    // 로그아웃 시 cross-store reset — 이전 계정의 잔여 상태(보유종목/신호/시세/
    // 트랜스크립트 등)가 재로그인 화면에 노출되면 안 된다.
    // useTradingStore 는 useUserStore 를 import 하므로 순환 import 가 되지만,
    // 참조가 런타임(clear 호출 시점)에만 일어나므로 안전하다.
    useMarketIndicesStore.getState().reset()
    useTradingStore.getState().reset()
    usePortfolioStore.getState().reset()
    useWatchlistStore.getState().reset()
    usePricesStore.getState().reset()
    useTranscriptStore.getState().reset()
    useDrawerStore.getState().reset()
  },
}))
