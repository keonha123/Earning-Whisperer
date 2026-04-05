import { create } from 'zustand'

export type WsStatus = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING'
export type KisTokenStatus = 'VALID' | 'EXPIRED' | 'UNKNOWN'

interface ConnectionState {
  wsStatus: WsStatus
  kisTokenStatus: KisTokenStatus
  hasCredentials: boolean
  isAuthenticated: boolean

  setWsStatus: (s: WsStatus) => void
  setKisTokenStatus: (s: KisTokenStatus) => void
  setHasCredentials: (v: boolean) => void
  setAuthenticated: (v: boolean) => void
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  wsStatus: 'DISCONNECTED',
  kisTokenStatus: 'UNKNOWN',
  hasCredentials: false,
  isAuthenticated: false,

  setWsStatus: (wsStatus) => set({ wsStatus }),
  setKisTokenStatus: (kisTokenStatus) => set({ kisTokenStatus }),
  setHasCredentials: (hasCredentials) => set({ hasCredentials }),
  setAuthenticated: (isAuthenticated) => set({ isAuthenticated }),
}))
