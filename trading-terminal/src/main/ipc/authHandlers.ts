import { ipcMain } from 'electron'
import { mainState } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { StompService } from '../services/StompService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerAuthHandlers() {
  ipcMain.handle(IPC_CHANNELS.AUTH_LOGIN, async (_e, { email, password }) => {
    const { token } = await BackendClient.login(email, password)
    mainState.setBackendToken(token)
    // 유저 정보(role/plan 포함) 조회
    const user = await BackendClient.getMe()
    return { user }
  })

  ipcMain.handle(IPC_CHANNELS.AUTH_LOGOUT, () => {
    StompService.disconnect()
    mainState.clear()
  })
}
