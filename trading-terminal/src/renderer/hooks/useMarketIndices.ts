import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import {
  useMarketIndicesStore,
  type MarketIndexItem,
} from '../store/useMarketIndicesStore'
import { showIpcErrorToast } from '../components/common/Toast'

/**
 * Backend 가 내려주는 snake_case payload (Contract 4.4 STOMP / 7.7 REST 동일 스키마).
 */
export interface RawMarketIndexPayload {
  symbol: string
  price: number
  change_percent: number
  trend: 'up' | 'down' | 'neutral'
  format: 'index' | 'percent'
  timestamp: number
}

/**
 * snake_case payload → camelCase store item 변환.
 * 단위 테스트를 위해 export — 외부 모듈에서 import 가능.
 */
export function toCamel(p: RawMarketIndexPayload): MarketIndexItem {
  return {
    symbol: p.symbol,
    price: p.price,
    changePercent: p.change_percent,
    trend: p.trend,
    format: p.format,
    timestamp: p.timestamp,
  }
}

/**
 * Backend payload 6필드 모두 typeof 가드. 누락/타입불일치 시 false.
 * REST/STOMP 양쪽에서 동일하게 적용해 비정상 메시지로 인한 store 오염 방지.
 */
export function isValidPayload(p: unknown): p is RawMarketIndexPayload {
  if (!p || typeof p !== 'object') return false
  const o = p as Record<string, unknown>
  return (
    typeof o.symbol === 'string' &&
    typeof o.price === 'number' &&
    typeof o.change_percent === 'number' &&
    typeof o.trend === 'string' &&
    typeof o.format === 'string' &&
    typeof o.timestamp === 'number'
  )
}

/**
 * useMarketIndices — 글로벌 시장 지수 5종 사이드이펙트 + 데이터 반환 훅.
 *
 * - 마운트 시:
 *   1) MARKET_INDICES_GET invoke → 초기 스냅샷을 store 에 setIndices.
 *      비배열/누락 필드는 필터링 후 통과한 항목만 setIndices.
 *   2) MARKET_INDICES_UPDATE 구독 → 6필드 가드 통과 시 upsertIndex.
 * - 언마운트 시 구독 해제.
 *
 * REST 실패 시 main 의 marketHandlers 가 빈 배열로 graceful fallback 하지만
 * renderer 에서도 try-catch 로 추가 방어한다. 실패해도 store 는 그대로 두어
 * placeholder 가 유지되도록 한다 (Contract 7.7).
 *
 * 반환값: 호출 측은 hook 반환값만 사용해도 충분 (store selector 직접 호출 불필요).
 */
export function useMarketIndices() {
  const setIndices = useMarketIndicesStore((s) => s.setIndices)
  const upsertIndex = useMarketIndicesStore((s) => s.upsertIndex)
  const indices = useMarketIndicesStore((s) => s.indices)
  const isLoaded = useMarketIndicesStore((s) => s.isLoaded)
  const lastUpdatedAt = useMarketIndicesStore((s) => s.lastUpdatedAt)

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      try {
        const snapshot = await ipc.invoke<unknown>(
          IPC_CHANNELS.MARKET_INDICES_GET,
        )
        if (cancelled) return
        const items = Array.isArray(snapshot)
          ? snapshot.filter(isValidPayload)
          : []
        setIndices(items.map(toCamel))
      } catch (e) {
        // graceful: store 변경 없이 placeholder 유지.
        console.error('[useMarketIndices] 초기 스냅샷 조회 실패:', e)
        showIpcErrorToast(e)
      }
    })()

    const unsubscribe = ipc.on(
      IPC_CHANNELS.MARKET_INDICES_UPDATE,
      (payload: unknown) => {
        if (!isValidPayload(payload)) {
          console.warn(
            '[useMarketIndices] STOMP push 페이로드 형식 불일치 — 스킵:',
            payload,
          )
          return
        }
        upsertIndex(toCamel(payload))
      },
    )

    return () => {
      cancelled = true
      unsubscribe()
    }
    // setIndices/upsertIndex 는 zustand 가 동일 reference 를 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { indices, isLoaded, lastUpdatedAt }
}
