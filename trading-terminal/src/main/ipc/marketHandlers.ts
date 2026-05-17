import { BackendClient, type MarketIndexPayload } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { isIpcError } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'

/**
 * 글로벌 시장 지수 IPC handler.
 *
 * - MARKET_INDICES_GET (invoke): 초기 스냅샷 조회.
 *   Backend Contract 7.7 — 빈 캐시 시 200 [].
 *   5xx/네트워크 에러 시 빈 배열로 graceful fallback (placeholder 표시).
 *   AUTH_EXPIRED 만 rethrow — 토큰 만료 신호를 다른 IPC 와 일관되게 사용자에게 노출.
 *
 * - MARKET_INDICES_UPDATE (push): StompService 가 직접 webContents.send 로 전달.
 *   여기서 등록할 invoke handler 는 없음.
 */
export function registerMarketHandlers() {
  registerHandler<undefined, MarketIndexPayload[]>(
    IPC_CHANNELS.MARKET_INDICES_GET,
    async () => {
      try {
        return await BackendClient.getMarketIndices()
      } catch (e) {
        if (isIpcError(e) && e.code === 'AUTH_EXPIRED') throw e
        console.error('[marketHandlers] 시장 지수 조회 실패:', e)
        return []
      }
    },
  )
}
