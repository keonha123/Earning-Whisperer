import { ipcMain } from 'electron'
import { KisService } from '../services/KisService'
import { TradeExecutor } from '../services/TradeExecutor'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerKisHandlers() {
  ipcMain.handle(IPC_CHANNELS.KIS_ISSUE_TOKEN, async () => {
    try {
      await KisService.issueToken()
      return KisService.getTokenStatus()
    } catch (e) {
      throw new Error(e instanceof Error ? e.message : 'KIS 토큰 발급 실패')
    }
  })

  ipcMain.handle(IPC_CHANNELS.KIS_GET_TOKEN_STATUS, () => {
    return KisService.getTokenStatus()
  })

  ipcMain.handle(IPC_CHANNELS.KIS_GET_BALANCE, async () => {
    try {
      return await KisService.getBalance()
    } catch (e) {
      throw new Error(e instanceof Error ? e.message : '잔고 조회 실패')
    }
  })

  ipcMain.handle(IPC_CHANNELS.KIS_PLACE_ORDER, async (_e, signal) => {
    try {
      return await TradeExecutor.execute(signal)
    } catch (e) {
      throw new Error(e instanceof Error ? e.message : '주문 실패')
    }
  })
}
