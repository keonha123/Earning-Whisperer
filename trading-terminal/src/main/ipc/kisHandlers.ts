import { ipcMain } from 'electron'
import { KisService } from '../services/KisService'
import { TradeExecutor } from '../services/TradeExecutor'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerKisHandlers() {
  ipcMain.handle(IPC_CHANNELS.KIS_ISSUE_TOKEN, async () => {
    await KisService.issueToken()
    return KisService.getTokenStatus()
  })

  ipcMain.handle(IPC_CHANNELS.KIS_GET_TOKEN_STATUS, () => {
    return KisService.getTokenStatus()
  })

  ipcMain.handle(IPC_CHANNELS.KIS_GET_BALANCE, async () => {
    return KisService.getBalance()
  })

  ipcMain.handle(IPC_CHANNELS.KIS_PLACE_ORDER, async (_e, signal) => {
    return TradeExecutor.execute(signal)
  })
}
