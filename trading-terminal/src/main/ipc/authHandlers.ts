import { ipcMain } from 'electron'
import { mainState } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { StompService } from '../services/StompService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerAuthHandlers() {
  ipcMain.handle(IPC_CHANNELS.AUTH_LOGIN, async (_e, { email, password }) => {
    const { token } = await BackendClient.login(email, password)
    mainState.setBackendToken(token)
    // 유저 정보(role/plan) + 포트폴리오 설정 병렬 조회
    const [user, settings] = await Promise.all([
      BackendClient.getMe(),
      BackendClient.getSettings(),
    ])
    // mainState에 트레이딩 모드 동기화
    if (settings.tradingMode) {
      mainState.setTradingMode(settings.tradingMode as any)
    }
    return { user, settings }
  })

  ipcMain.handle(IPC_CHANNELS.AUTH_LOGOUT, () => {
    StompService.disconnect()
    mainState.clear()
  })
}
