import { create } from 'zustand'

export type UserPlan = 'FREE' | 'PRO'

export interface UserSettings {
  tradingMode: 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'
  maxBuyRatio: number
  maxHoldingRatio: number
  cooldownMinutes: number
  /**
   * AI 매매 신호 임계치 (0.0 ~ 1.0). 점수가 이 값 이상일 때만 신호 발동.
   * TODO: emaThreshold 백엔드 영속화 (SETTINGS_UPDATE 확장 + BackendClient 수정).
   *       현재는 로컬 zustand 상태로만 유지되며 IPC 페이로드에 포함되지 않음.
   */
  emaThreshold: number
}

interface UserState {
  userId: number | null
  email: string | null
  nickname: string | null
  plan: UserPlan
  settings: UserSettings

  setUser: (user: { id: number; email: string; nickname: string; role: string }) => void
  setSettings: (settings: Partial<UserSettings>) => void
  setEmaThreshold: (value: number) => void
  clear: () => void
}

const defaultSettings: UserSettings = {
  tradingMode: 'MANUAL',
  maxBuyRatio: 0.1,
  maxHoldingRatio: 0.3,
  cooldownMinutes: 5,
  emaThreshold: 0.6,
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

  setEmaThreshold: (value) =>
    set((state) => ({ settings: { ...state.settings, emaThreshold: value } })),

  clear: () =>
    set({
      userId: null,
      email: null,
      nickname: null,
      plan: 'FREE',
      settings: defaultSettings,
    }),
}))
