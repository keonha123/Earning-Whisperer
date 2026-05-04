import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { usePricesStore, type PriceEntry } from '../store/usePricesStore'
import { showIpcErrorToast } from '../components/common/Toast'

/**
 * PRICES_UPDATE batch 단건 가드.
 * main 이 항상 정상 페이로드를 보내지만, 형식 불일치로 인한 store 오염 방지.
 */
function isValidBatchItem(
  p: unknown,
): p is { ticker: string; currentPrice: number; lastUpdated: number } {
  if (!p || typeof p !== 'object') return false
  const o = p as Record<string, unknown>
  return (
    typeof o.ticker === 'string' &&
    typeof o.currentPrice === 'number' &&
    typeof o.lastUpdated === 'number'
  )
}

function filterBatch(
  payload: unknown,
): Array<{ ticker: string; currentPrice: number; lastUpdated: number }> {
  return Array.isArray(payload) ? payload.filter(isValidBatchItem) : []
}

/**
 * PRICES_GET 응답 (Record<ticker, PriceEntry>) 가드.
 * 비정상 응답 (배열/null/엔트리 형식 불일치) 은 빈 snapshot 으로 안전 fallback.
 */
function filterSnapshot(payload: unknown): Record<string, PriceEntry> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return {}
  }
  const out: Record<string, PriceEntry> = {}
  for (const [ticker, entry] of Object.entries(payload as Record<string, unknown>)) {
    if (!entry || typeof entry !== 'object') continue
    const o = entry as Record<string, unknown>
    if (typeof o.currentPrice === 'number' && typeof o.lastUpdated === 'number') {
      out[ticker] = {
        currentPrice: o.currentPrice,
        lastUpdated: o.lastUpdated,
      }
    }
  }
  return out
}

/**
 * usePrices — 시세 폴링 캐시 사이드이펙트 + 데이터 반환 훅.
 *
 * - 마운트 시:
 *   1) PRICES_GET invoke → main 캐시 (없으면 {}) 를 store 에 setSnapshot.
 *   2) PRICES_UPDATE 구독 → 폴러 사이클당 1회 batch 수신 → upsertBatch.
 * - refresh 함수 미제공: 폴러가 자동으로 push 하므로 호출자 트리거 불필요.
 * - 언마운트 시 구독 해제.
 *
 * dailyChangePercent 는 별도 데이터(전일 종가) 가 필요 — 이번 PR 범위 외.
 */
export function usePrices() {
  const prices = usePricesStore((s) => s.prices)
  const isLoaded = usePricesStore((s) => s.isLoaded)
  const setSnapshot = usePricesStore((s) => s.setSnapshot)
  const upsertBatch = usePricesStore((s) => s.upsertBatch)

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      try {
        const cached = await ipc.invoke<unknown>(IPC_CHANNELS.PRICES_GET)
        if (cancelled) return
        setSnapshot(filterSnapshot(cached))
      } catch (e) {
        // graceful: store 변경 없이 placeholder 유지.
        console.error('[usePrices] 초기 캐시 조회 실패:', e)
        showIpcErrorToast(e)
      }
    })()

    const unsubscribe = ipc.on(IPC_CHANNELS.PRICES_UPDATE, (payload: unknown) => {
      upsertBatch(filterBatch(payload))
    })

    return () => {
      cancelled = true
      unsubscribe()
    }
    // setSnapshot/upsertBatch 는 zustand 가 동일 reference 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { prices, isLoaded }
}
