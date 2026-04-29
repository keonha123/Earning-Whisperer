import { ipcMain } from 'electron'
import { BackendClient, type MarketIndexPayload } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'

/**
 * 글로벌 시장 지수 IPC handler.
 *
 * - MARKET_INDICES_GET (invoke): 초기 스냅샷 조회.
 *   Backend Contract 7.7 — 빈 캐시 시 200 [].
 *   네트워크/서버 에러 시 throw 대신 빈 배열을 반환해 UI 가 placeholder 로 graceful 표시되도록 한다.
 *
 * - MARKET_INDICES_UPDATE (push): StompService 가 직접 webContents.send 로 전달.
 *   여기서 등록할 invoke handler 는 없음.
 */
export function registerMarketHandlers() {
  ipcMain.handle(IPC_CHANNELS.MARKET_INDICES_GET, async (): Promise<MarketIndexPayload[]> => {
    try {
      return await BackendClient.getMarketIndices()
    } catch (e) {
      // Contract 상 200 [] 와 동일한 의미로 취급 — 호출자(renderer)는 항상 배열을 받음.
      console.error('[marketHandlers] 시장 지수 조회 실패:', e)
      return []
    }
  })
}
