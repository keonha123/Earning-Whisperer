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

  ipcMain.handle(IPC_CHANNELS.TRADE_CANCEL, async (_e, { tradeId, reason }: { tradeId: string; reason: string }) => {
    await BackendClient.sendCallback(tradeId, {
      status: 'FAILED',
      broker_order_id: null,
      executed_price: null,
      executed_qty: 0,
      error_message: reason,
    })
  })
}
