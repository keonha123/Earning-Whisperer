import { ipcMain } from 'electron'
import { mainState } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { StompService } from '../services/StompService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerAuthHandlers() {
  ipcMain.handle(IPC_CHANNELS.AUTH_LOGIN, async (_e, { email, password }) => {
    const { token, user } = await BackendClient.login(email, password)
    mainState.setBackendToken(token)
    // 로그인 성공 후 WebSocket 연결
    StompService.connect()
    return { user }
  })

  ipcMain.handle(IPC_CHANNELS.AUTH_LOGOUT, () => {
    StompService.disconnect()
    mainState.clear()
  })
}
