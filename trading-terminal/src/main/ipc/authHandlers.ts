import { ipcMain } from 'electron'
import { mainState, TradingMode } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { StompService } from '../services/StompService'
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
      console.warn('[Auth] 설정 로드 실패, 기본값 사용:', e)
    }

    return { user, settings }
  })

  ipcMain.handle(IPC_CHANNELS.AUTH_LOGOUT, () => {
    StompService.disconnect()
    mainState.clear()
  })
}
