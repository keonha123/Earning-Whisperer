/**
 * Main 프로세스 메모리 상태.
 * JWT 토큰, KIS access_token 등 보안 민감 데이터는 이 객체에만 존재한다.
 * 디스크(electron-store, 파일)에 기록하지 않는다.
 */

export type TradingMode = 'MANUAL' | 'SEMI_AUTO' | 'AUTO_PILOT'

interface MainState {
  /** EarningWhisperer 백엔드 JWT 액세스 토큰 */
  backendToken: string | null
  /** KIS OAuth access_token */
  kisAccessToken: string | null
  /** KIS 토큰 만료 시각 (Unix ms) */
  kisTokenExpiresAt: number | null
  /** 현재 트레이딩 모드 — Renderer store와 동기화 */
  tradingMode: TradingMode
  /** 진행 중인 주문 여부 — 모드 전환 레이스 컨디션 방지 */
  isOrderInProgress: boolean
}

const state: MainState = {
  backendToken: null,
  kisAccessToken: null,
  kisTokenExpiresAt: null,
  tradingMode: 'MANUAL',
  isOrderInProgress: false,
}

export const mainState = {
  get backendToken() { return state.backendToken },
  setBackendToken(token: string | null) { state.backendToken = token },

  get kisAccessToken() { return state.kisAccessToken },
  setKisAccessToken(token: string | null, expiresIn?: number) {
    state.kisAccessToken = token
    state.kisTokenExpiresAt = token && expiresIn
      ? Date.now() + expiresIn * 1000
      : null
  },

  get kisTokenExpiresAt() { return state.kisTokenExpiresAt },
  isKisTokenValid(): boolean {
    if (!state.kisAccessToken || !state.kisTokenExpiresAt) return false
    return Date.now() < state.kisTokenExpiresAt - 60_000 // 1분 여유
  },

  get tradingMode() { return state.tradingMode },
  setTradingMode(mode: TradingMode) { state.tradingMode = mode },

  get isOrderInProgress() { return state.isOrderInProgress },
  setOrderInProgress(v: boolean) { state.isOrderInProgress = v },

  /** 앱 종료 및 로그아웃 시 민감 데이터 소거 */
  clear() {
    state.backendToken = null
    state.kisAccessToken = null
    state.kisTokenExpiresAt = null
    state.tradingMode = 'MANUAL'
    state.isOrderInProgress = false
  },
}
