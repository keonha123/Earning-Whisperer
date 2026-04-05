import { ipcMain } from 'electron'
import { KisService } from '../services/KisService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerVaultHandlers() {
  ipcMain.handle(IPC_CHANNELS.VAULT_SAVE, async (_e, { appKey, appSecret, accountNo }) => {
    await KisService.saveCredentials(appKey, appSecret, accountNo)
    return { success: true }
  })

  ipcMain.handle(IPC_CHANNELS.VAULT_HAS, async () => {
    return KisService.hasCredentials()
  })

  ipcMain.handle(IPC_CHANNELS.VAULT_DELETE, async () => {
    await KisService.deleteCredentials()
    return { success: true }
  })
}
