import { useCallback, useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useWatchlistStore, type WatchlistItem } from '../store/useWatchlistStore'
import { showIpcErrorToast } from '../components/common/Toast'

/**
 * payload 가드 — main 이 항상 camelCase 배열을 보내지만 형식 불일치 메시지로 인한 store 오염 방지.
 */
function isValidItem(p: unknown): p is WatchlistItem {
  if (!p || typeof p !== 'object') return false
  const o = p as Record<string, unknown>
  return (
    typeof o.ticker === 'string' &&
    typeof o.companyName === 'string' &&
    typeof o.sector === 'string'
  )
}

function filterValid(payload: unknown): WatchlistItem[] {
  return Array.isArray(payload) ? payload.filter(isValidItem) : []
}

/**
 * useWatchlist — 관심종목 ticker 목록 사이드이펙트 + 데이터 반환 훅.
 *
 * - 마운트 시:
 *   1) WATCHLIST_GET invoke → main 캐시 (없으면 []) 를 store 에 setItems.
 *   2) WATCHLIST_UPDATE 구독 → 5분 폴링/refresh broadcast 시 store 자동 갱신.
 * - refresh(): 호출 즉시 main 이 백엔드 재조회 → store 갱신.
 * - 언마운트 시 구독 해제.
 *
 * 가격 표시는 이번 작업 범위 외 (Step 5).
 */
export function useWatchlist() {
  const items = useWatchlistStore((s) => s.items)
  const isLoaded = useWatchlistStore((s) => s.isLoaded)
  const setItems = useWatchlistStore((s) => s.setItems)

  const refresh = useCallback(async () => {
    try {
      const fresh = await ipc.invoke<unknown>(IPC_CHANNELS.WATCHLIST_REFRESH)
      setItems(filterValid(fresh))
    } catch (e) {
      console.error('[useWatchlist] refresh 실패:', e)
      showIpcErrorToast(e)
    }
  }, [setItems])

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      try {
        const cached = await ipc.invoke<unknown>(IPC_CHANNELS.WATCHLIST_GET)
        if (cancelled) return
        setItems(filterValid(cached))
      } catch (e) {
        console.error('[useWatchlist] 초기 캐시 조회 실패:', e)
        showIpcErrorToast(e)
      }
    })()

    const unsubscribe = ipc.on(IPC_CHANNELS.WATCHLIST_UPDATE, (payload: unknown) => {
      setItems(filterValid(payload))
    })

    return () => {
      cancelled = true
      unsubscribe()
    }
    // setItems 는 zustand 가 동일 reference 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { items, isLoaded, refresh }
}
