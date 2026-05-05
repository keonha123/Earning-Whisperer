import { create } from 'zustand'

export type WsStatus = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING'
export type KisTokenStatus = 'VALID' | 'EXPIRED' | 'UNKNOWN'

/**
 * KIS 자격증명 등록 여부 — 모드별로 분리.
 * A2 단계에서 paper/real slot 분리 저장으로 전환되면서 boolean 단일 값은 의미가 모호해짐
 * (어느 모드 키가 등록되어 있는가? "있다/없다"로는 활성 모드 기준 UX 결정 불가).
 *
 * 호출자 사용 패턴:
 *   - 진입 가드 (양쪽 중 하나라도 등록): `hasCredentials.paper || hasCredentials.real`
 *   - 활성 모드 기준 UX (등록됨/삭제 가능 등): `hasCredentials[isPaperTrading ? 'paper' : 'real']`
 */
export interface CredentialsState {
  paper: boolean
  real: boolean
}

interface ConnectionState {
  wsStatus: WsStatus
  kisTokenStatus: KisTokenStatus
  hasCredentials: CredentialsState
  isAuthenticated: boolean

  setWsStatus: (s: WsStatus) => void
  setKisTokenStatus: (s: KisTokenStatus) => void
  setHasCredentials: (v: CredentialsState) => void
  setAuthenticated: (v: boolean) => void
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  wsStatus: 'DISCONNECTED',
  kisTokenStatus: 'UNKNOWN',
  hasCredentials: { paper: false, real: false },
  isAuthenticated: false,

  setWsStatus: (wsStatus) => set({ wsStatus }),
  setKisTokenStatus: (kisTokenStatus) => set({ kisTokenStatus }),
  setHasCredentials: (hasCredentials) => set({ hasCredentials }),
  setAuthenticated: (isAuthenticated) => set({ isAuthenticated }),
}))

/** 양쪽 모드 중 하나라도 등록되어 있는지 — 진입 가드용 derive 헬퍼. */
export function hasAnyCredentials(c: CredentialsState): boolean {
  return c.paper || c.real
}
