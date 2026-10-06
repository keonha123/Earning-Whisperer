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

interface UserState {
  userId: number | null
  email: string | null
  nickname: string | null
  plan: UserPlan
  accountType: AccountType | null

  setUser: (user: { id: number; email: string; nickname: string; role: string }) => void
  setAccountType: (accountType: AccountType) => void
  clear: () => void
}

export const useUserStore = create<UserState>((set) => ({
  userId: null,
  email: null,
  nickname: null,
  plan: 'FREE',
  accountType: null,

  setUser: (user) =>
    set({
      userId: user.id,
      email: user.email,
      nickname: user.nickname,
      plan: user.role === 'PRO' ? 'PRO' : 'FREE',
    }),

  setAccountType: (accountType) => set({ accountType }),

  clear: () => {
    set({
      userId: null,
      email: null,
      nickname: null,
      plan: 'FREE',
      accountType: null,
    })
    // 로그아웃 시 cross-store reset — 이전 계정의 잔여 상태(보유종목/시세/
    // 트랜스크립트 등)가 재로그인 화면에 노출되면 안 된다.
    useMarketIndicesStore.getState().reset()
    useTradingStore.getState().reset()
    usePortfolioStore.getState().reset()
    useWatchlistStore.getState().reset()
    usePricesStore.getState().reset()
    useTranscriptStore.getState().reset()
    useDrawerStore.getState().reset()
  },
}))
