import { ipcMain } from 'electron'
import { mainState } from '../store/mainState'
import { BackendClient } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

export function registerSettingsHandlers() {
  ipcMain.handle(IPC_CHANNELS.SETTINGS_UPDATE, async (_e, settings) => {
    // Main 모드 캐시 업데이트
    if (settings.tradingMode) {
      // 진행 중인 주문이 없을 때만 전환
      if (!mainState.isOrderInProgress) {
        mainState.setTradingMode(settings.tradingMode)
      }
    }
    // 백엔드에 설정 저장
    await BackendClient.updateSettings({
      trading_mode: settings.tradingMode,
      max_buy_ratio: settings.maxBuyRatio,
      max_holding_ratio: settings.maxHoldingRatio,
      cooldown_minutes: settings.cooldownMinutes,
    })
  })
}
