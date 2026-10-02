import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useFactCheckStore, type FactCheckClaim } from '../store/useFactCheckStore'

/**
 * useFactCheck — 실시간 어닝콜 팩트체크 사이드이펙트 훅.
 *
 * Backend Contract 4.6 STOMP /topic/factcheck/{ticker} 와 연결.
 * useLiveTranscript 와 같은 구조이며, 같은 ticker 를 함께 따라간다.
 *
 * @returns claims 도착 순서(= 발언 순서)로 누적된 판정 배열.
 */
export function useFactCheck(ticker: string | null): {
  claims: readonly FactCheckClaim[]
  clear: (ticker: string) => void
} {
  const upsertBatch = useFactCheckStore((s) => s.upsertBatch)
  const clear = useFactCheckStore((s) => s.clearTicker)
  const byTicker = useFactCheckStore((s) => s.byTicker)

  useEffect(() => {
    const unsubscribe = ipc.on(IPC_CHANNELS.FACTCHECK_BATCH_RECEIVED, (payload: unknown) => {
      // 검증은 store 의 upsertBatch 가 수행한다.
      upsertBatch(payload)
    })
    return unsubscribe
    // upsertBatch 는 zustand 가 동일 reference 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!ticker) return
    void ipc.invoke(IPC_CHANNELS.FACTCHECK_SUBSCRIBE, { ticker })
    return () => {
      void ipc.invoke(IPC_CHANNELS.FACTCHECK_UNSUBSCRIBE, { ticker })
    }
  }, [ticker])

  return { claims: byTicker.get(ticker ?? '')?.claims ?? [], clear }
}
