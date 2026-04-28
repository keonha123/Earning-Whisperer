import { ipcMain } from 'electron'
import { mainState, TradingMode } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { StompService } from '../services/StompService'
import { KisService } from '../services/KisService'
import { OAuthService, OAuthProvider } from '../services/OAuthService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerAuthHandlers() {
  ipcMain.handle(IPC_CHANNELS.AUTH_LOGIN, async (_e, { email, password }) => {
    const { token } = await BackendClient.login(email, password)
    mainState.setBackendToken(token)

    // 유저 정보 조회 (필수)
    const user = await BackendClient.getMe()

    // 포트폴리오 설정 조회 (선택 — 실패해도 기본값으로 로그인 진행)
    let settings = null
    try {
      settings = await BackendClient.getSettings()
      if (settings.tradingMode) {
        mainState.setTradingMode(settings.tradingMode as TradingMode)
      }
    } catch (e) {
      console.warn('[Auth] 설정 로드 실패, 기본값 사용:', e instanceof Error ? e.message : 'unknown error')
    }

    // KIS 토큰 복원 (선택 — 실패해도 로그인 진행)
    try {
      await KisService.loadSavedToken()
    } catch (e) {
      console.warn('[Auth] KIS 토큰 복원 실패:', e instanceof Error ? e.message : 'unknown error')
    }

    return { user, settings }
  })

  ipcMain.handle(IPC_CHANNELS.AUTH_LOGOUT, () => {
    StompService.disconnect()
    mainState.clear()
  })

  /**
   * OAuth (Google / Kakao) 로그인 — Loopback Localhost Server 흐름.
   * Renderer 가 invoke 한 단일 Promise 가 콜백 수신/실패/타임아웃까지 대기한다.
   * 결과 형식은 AUTH_LOGIN 과 동일 ({ user, settings }) — Renderer 의 onSuccess 재사용 보장.
   */
  ipcMain.handle(IPC_CHANNELS.AUTH_OAUTH_START, async (_e, payload: { provider: OAuthProvider }) => {
    if (!payload || (payload.provider !== 'google' && payload.provider !== 'kakao')) {
      throw new Error('지원하지 않는 OAuth provider 입니다.')
    }
    return OAuthService.start(payload.provider)
  })
}
