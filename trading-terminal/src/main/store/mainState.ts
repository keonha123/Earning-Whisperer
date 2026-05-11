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
  /** KIS 토큰 만료 시각 (Unix ms, UI 표시용) */
  kisTokenExpiresAt: number | null
  /**
   * 토큰 발급 시 캡처한 monotonic 시각 (performance.now() 기준 ms).
   * isKisTokenValid 의 만료 판정은 시계 어긋남(NTP 점프)에 영향받지 않도록
   * Date.now() 가 아닌 이 값 + 수명으로 계산한다. wall-clock 은 UI 표시 전용.
   */
  kisTokenIssuedAtMono: number | null
  /** 토큰 수명(초). 발급 시점의 expiresIn 을 그대로 보존. */
  kisTokenLifetimeSec: number | null
  /** 현재 트레이딩 모드 — Renderer store와 동기화 */
  tradingMode: TradingMode
  /** 진행 중인 주문 여부 — 모드 전환 레이스 컨디션 방지 */
  isOrderInProgress: boolean
  /** 모의투자(true) / 실전투자(false) 환경 — 토큰/baseURL/rate limit 분기 */
  isPaperTrading: boolean
}

const state: MainState = {
  backendToken: null,
  kisAccessToken: null,
  kisTokenExpiresAt: null,
  kisTokenIssuedAtMono: null,
  kisTokenLifetimeSec: null,
  tradingMode: 'MANUAL',
  isOrderInProgress: false,
  isPaperTrading: true,
}

const TOKEN_VALIDITY_MARGIN_SEC = 60

export const mainState = {
  get backendToken() { return state.backendToken },
  setBackendToken(token: string | null) { state.backendToken = token },

  get kisAccessToken() { return state.kisAccessToken },
  setKisAccessToken(token: string | null, expiresIn?: number) {
    state.kisAccessToken = token
    if (token && expiresIn) {
      state.kisTokenExpiresAt = Date.now() + expiresIn * 1000
      state.kisTokenIssuedAtMono = performance.now()
      state.kisTokenLifetimeSec = expiresIn
    } else {
      state.kisTokenExpiresAt = null
      state.kisTokenIssuedAtMono = null
      state.kisTokenLifetimeSec = null
    }
  },

  get kisTokenExpiresAt() { return state.kisTokenExpiresAt },
  /**
   * monotonic 시계 기반 만료 판정 — Date.now() 가 NTP 동기화로 점프해도 안전.
   * 발급 시점의 수명에서 elapsed (performance.now diff) 를 빼 만료 여부를 본다.
   */
  isKisTokenValid(): boolean {
    if (
      !state.kisAccessToken ||
      state.kisTokenIssuedAtMono === null ||
      state.kisTokenLifetimeSec === null
    ) {
      return false
    }
    const elapsedSec = (performance.now() - state.kisTokenIssuedAtMono) / 1000
    return elapsedSec < state.kisTokenLifetimeSec - TOKEN_VALIDITY_MARGIN_SEC
  },

  get tradingMode() { return state.tradingMode },
  setTradingMode(mode: TradingMode) { state.tradingMode = mode },

  get isOrderInProgress() { return state.isOrderInProgress },
  setOrderInProgress(v: boolean) { state.isOrderInProgress = v },

  get isPaperTrading() { return state.isPaperTrading },
  setPaperTrading(value: boolean) { state.isPaperTrading = value },

  /**
   * 앱 종료 및 로그아웃 시 민감 데이터 소거.
   * isPaperTrading은 사용자 환경 선택값이므로 유지한다.
   */
  clear() {
    state.backendToken = null
    state.kisAccessToken = null
    state.kisTokenExpiresAt = null
    state.kisTokenIssuedAtMono = null
    state.kisTokenLifetimeSec = null
    state.tradingMode = 'MANUAL'
    state.isOrderInProgress = false
  },
}
