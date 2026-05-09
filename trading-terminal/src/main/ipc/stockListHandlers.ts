import { BackendClient } from '../services/BackendClient'
import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { registerHandler } from './registerHandler'
import type { Sp500Stock, StockPriceEntry } from '../../lib/types/stockList'

const CACHE_TTL_MS = 5 * 60 * 1000

let sp500Cache: Sp500Stock[] | null = null
let sp500CachedAt = 0

export function registerStockListHandlers(): void {
  registerHandler(IPC_CHANNELS.STOCKS_SP500_GET, async () => {
    if (sp500Cache && Date.now() - sp500CachedAt < CACHE_TTL_MS) {
      return sp500Cache
    }
    try {
      const list = await BackendClient.getSp500List()
      sp500Cache = list
      sp500CachedAt = Date.now()
      return list
    } catch (e) {
      console.warn('[StockListHandlers] SP500 리스트 조회 실패:', e)
      return sp500Cache ?? []
    }
  })

  registerHandler(IPC_CHANNELS.STOCK_PRICES_SNAPSHOT_GET, async (): Promise<StockPriceEntry[]> => {
    try {
      return await BackendClient.getStockPricesSnapshot()
    } catch (e) {
      console.warn('[StockListHandlers] 주가 스냅샷 조회 실패:', e)
      return []
    }
  })
}
