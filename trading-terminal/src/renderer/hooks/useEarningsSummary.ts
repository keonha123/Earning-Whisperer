import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useEarningsSummaryStore } from '../store/useEarningsSummaryStore'
import type { EarningsSummary } from '../types/earningsSummary'

/**
 * useEarningsSummary — 어닝콜 종료 후 종합 판단 사이드이펙트 훅.
 *
 * Backend Contract 4.7 STOMP /topic/evaluation/{ticker} 와 연결.
 * useFactCheck 와 같은 구조이며 같은 ticker 를 함께 따라간다.
 *
 * 이 토픽은 <b>어닝콜 회차당 1건</b>만 흐른다. 늦게 구독하면 그 1건을 놓치고
 * 다시 받을 방법이 없으므로, 재생 시작 전에 구독이 서 있어야 한다.
 * 화면이 ticker 를 정하는 즉시 구독하는 이 훅의 구조가 그것을 보장한다.
 */
export function useEarningsSummary(ticker: string | null): {
  summary: EarningsSummary | null
  clear: (ticker: string) => void
} {
  const setSummary = useEarningsSummaryStore((s) => s.setSummary)
  const clear = useEarningsSummaryStore((s) => s.clearTicker)
  const byTicker = useEarningsSummaryStore((s) => s.byTicker)

  useEffect(() => {
    const unsubscribe = ipc.on(IPC_CHANNELS.EVALUATION_RECEIVED, (payload: unknown) => {
      // 검증은 store 의 setSummary 가 수행한다.
      setSummary(payload)
    })
    return unsubscribe
    // setSummary 는 zustand 가 동일 reference 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!ticker) return
    void ipc.invoke(IPC_CHANNELS.EVALUATION_SUBSCRIBE, { ticker })
    return () => {
      void ipc.invoke(IPC_CHANNELS.EVALUATION_UNSUBSCRIBE, { ticker })
    }
  }, [ticker])

  return { summary: byTicker.get(ticker ?? '') ?? null, clear }
}
