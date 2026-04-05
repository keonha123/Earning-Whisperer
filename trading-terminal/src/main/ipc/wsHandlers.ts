import { ipcMain } from 'electron'
import { StompService } from '../services/StompService'
import { BackendClient } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerWsHandlers() {
  ipcMain.handle(IPC_CHANNELS.WS_CONNECT, () => {
    StompService.connect()
  })

  ipcMain.handle(IPC_CHANNELS.WS_DISCONNECT, () => {
    StompService.disconnect()
  })

  ipcMain.handle(IPC_CHANNELS.TRADES_GET, async (_e, { page, size }) => {
    return BackendClient.getTrades(page, size)
  })
}
