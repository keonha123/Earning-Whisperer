import { ipcMain } from 'electron'
import { KisService } from '../services/KisService'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerVaultHandlers() {
  ipcMain.handle(IPC_CHANNELS.VAULT_SAVE, async (_e, { appKey, appSecret, accountNo }) => {
    await KisService.saveCredentials(appKey, appSecret, accountNo)
    // 최초 등록 직후 토큰 발급 시도 (실패해도 저장은 완료)
    try {
      await KisService.issueToken()
    } catch (e) {
      console.warn('[Vault] 자격증명 저장 후 KIS 토큰 발급 실패:', e instanceof Error ? e.message : 'unknown error')
    }
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
