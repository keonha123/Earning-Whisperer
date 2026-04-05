import { create } from 'zustand'

export type UserPlan = 'FREE' | 'PRO'

export interface UserSettings {
  tradingMode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
  maxBuyRatio: number
  maxHoldingRatio: number
  cooldownMinutes: number
}

interface UserState {
  userId: number | null
  email: string | null
  nickname: string | null
  plan: UserPlan
  settings: UserSettings

  setUser: (user: { id: number; email: string; nickname: string; role: string }) => void
  setSettings: (settings: Partial<UserSettings>) => void
  clear: () => void
}

const defaultSettings: UserSettings = {
  tradingMode: 'MANUAL',
  maxBuyRatio: 0.1,
  maxHoldingRatio: 0.3,
  cooldownMinutes: 5,
}

export const useUserStore = create<UserState>((set) => ({
  userId: null,
  email: null,
  nickname: null,
  plan: 'FREE',
  settings: defaultSettings,

  setUser: (user) =>
    set({
      userId: user.id,
      email: user.email,
      nickname: user.nickname,
      plan: user.role === 'PRO' ? 'PRO' : 'FREE',
    }),

  setSettings: (partial) =>
    set((state) => ({ settings: { ...state.settings, ...partial } })),

  clear: () =>
    set({
      userId: null,
      email: null,
      nickname: null,
      plan: 'FREE',
      settings: defaultSettings,
    }),
}))
