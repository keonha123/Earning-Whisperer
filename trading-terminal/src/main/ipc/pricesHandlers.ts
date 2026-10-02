import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { getCachedPrices, setHoldings } from '../services/PricePoller'
import { SubscriptionManager } from '../services/SubscriptionManager'
import { registerHandler } from './registerHandler'

/**
 * 시세 폴링 IPC handler.
 *
 * - PRICES_GET (invoke): PricePoller 가 보유한 마지막 batch 캐시 반환.
 *   Renderer 마운트 시 초기 로드용. 빈 캐시는 {} 반환.
 * - HOLDINGS_TICKERS_UPDATE (invoke): Renderer 가 KIS_GET_BALANCE 응답에서
 *   추출한 보유 ticker 목록을 PricePoller 에 전달. PRICES_UPDATE broadcast 는
 *   PricePoller 가 직접 push 하므로 여기에 등록하지 않는다.
 */
export function registerPricesHandlers(): void {
  registerHandler(IPC_CHANNELS.PRICES_GET, () => {
    return getCachedPrices()
  })

  registerHandler<{ tickers: string[] }, { ok: true }>(
    IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE,
    (_e, payload) => {
      const tickers = Array.isArray(payload?.tickers) ? payload.tickers : []
      setHoldings(tickers)
      SubscriptionManager.setHoldings(tickers)
      return { ok: true }
    },
  )
}
