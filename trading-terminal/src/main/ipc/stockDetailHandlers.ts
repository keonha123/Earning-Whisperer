import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError } from '../../lib/types/ipcError'
import { BackendClient, type StockDetailResponsePayload } from '../services/BackendClient'
import { registerHandler } from './registerHandler'

/**
 * 종목 상세 IPC handler.
 *
 * - STOCK_GET_DETAIL (invoke): payload `{ ticker }`.
 *   - ticker 정규식 검증 실패 시 IpcError(VALIDATION) throw.
 *   - 캐시 hit (30s TTL) 시 백엔드 호출 없이 캐시된 payload 반환.
 *   - miss/만료 시 BackendClient.getStockDetail 호출 → 캐시 갱신 → 응답.
 *   - axios error 는 BackendClient interceptor 가 IpcError 로 변환 → 그대로 propagate.
 *
 * 캐시 정책:
 *   - ticker별 독립 entry, 30s TTL (full) / 5s TTL (partial).
 *   - partial=true 응답은 백엔드 lazy fetch 가 일부 단계 실패한 상태 → 빠른 재시도 가치가
 *     있어 짧은 TTL 적용. 캐시 자체를 skip 하면 사용자가 drawer 닫고 바로 재오픈 시
 *     불필요한 호출 burst 발생하므로 5s 정도가 절충.
 *   - 만료 시 silent 재호출 (push 갱신 없음, drawer 단기 재오픈 시 한정 효과).
 *   - 사이즈 무제한 — S&P 500 + 보유종목 합쳐 수백 ticker 로 수렴, 메모리 부담 미미.
 *   - 로그아웃 시 캐시 클리어는 본 phase 미반영. 후속 PR 에서 AUTH_LOGOUT IPC 시 cache.clear()
 *     훅을 다는 방식으로 인계 (현재는 같은 사용자 세션 가정 → token 만 바뀌면 안 됨).
 */

const TICKER_PATTERN = /^[A-Z0-9.\-]{1,10}$/

interface CacheEntry {
  payload: StockDetailResponsePayload
  fetchedAt: number
}

const FULL_TTL_MS = 30_000
const PARTIAL_TTL_MS = 5_000
const cache = new Map<string, CacheEntry>()

function ttlFor(payload: StockDetailResponsePayload): number {
  return payload.partial ? PARTIAL_TTL_MS : FULL_TTL_MS
}

export function registerStockDetailHandlers(): void {
  registerHandler<{ ticker: string } | undefined, StockDetailResponsePayload>(
    IPC_CHANNELS.STOCK_GET_DETAIL,
    async (_e, payload) => {
      const ticker = payload?.ticker
      if (typeof ticker !== 'string' || !TICKER_PATTERN.test(ticker)) {
        throw new IpcError('VALIDATION', 'invalid ticker')
      }

      const cached = cache.get(ticker)
      if (cached && Date.now() - cached.fetchedAt < ttlFor(cached.payload)) {
        return cached.payload
      }

      const fresh = await BackendClient.getStockDetail(ticker)
      cache.set(ticker, { payload: fresh, fetchedAt: Date.now() })
      return fresh
    },
  )
}

/**
 * 캐시 초기화. AUTH_LOGOUT 시점에 호출 — 사용자 전환 시 이전 사용자의 응답이
 * 다음 사용자에게 노출되는 것을 막는다.
 */
export function clearCache(): void {
  cache.clear()
}

/** 테스트 전용 — clearCache 와 동일 동작 (의미 명시). */
export function __resetCacheForTest(): void {
  clearCache()
}

/** 테스트 전용 — 캐시 사이즈 조회. production 코드에서는 사용 금지. */
export function __getCacheSizeForTest(): number {
  return cache.size
}
