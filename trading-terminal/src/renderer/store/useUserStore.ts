import { create } from 'zustand'
import { useMarketIndicesStore } from './useMarketIndicesStore'

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
    // 로그아웃 시 cross-store reset — 시장 지수는 stale 상태가 남으면 안 됨.
    // (다른 store 도 향후 동일 패턴으로 합류 가능.)
    useMarketIndicesStore.getState().reset()
  },
}))
