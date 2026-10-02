import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import {
  useTranscriptDiffStore,
  type PreviousCall,
  type TranscriptDiffItem,
} from '../store/useTranscriptDiffStore'

/**
 * useTranscriptDiff — 직전 콜 발언 대조 사이드이펙트 훅.
 *
 * Backend STOMP /topic/transcript-diff/{ticker} 와 연결.
 * useFactCheck 와 같은 구조이며, 같은 ticker 를 함께 따라간다.
 *
 * @returns items 도착 순서(= 발언 순서)로 누적된 대조 결과와, 비교 대상이 된 직전 콜.
 */
export function useTranscriptDiff(ticker: string | null): {
  items: readonly TranscriptDiffItem[]
  previousCall: PreviousCall | null
  clear: (ticker: string) => void
} {
  const upsertDiff = useTranscriptDiffStore((s) => s.upsertDiff)
  const clear = useTranscriptDiffStore((s) => s.clearTicker)
  const byTicker = useTranscriptDiffStore((s) => s.byTicker)

  useEffect(() => {
    const unsubscribe = ipc.on(IPC_CHANNELS.TRANSCRIPT_DIFF_RECEIVED, (payload: unknown) => {
      // 검증은 store 의 upsertDiff 가 수행한다.
      upsertDiff(payload)
    })
    return unsubscribe
    // upsertDiff 는 zustand 가 동일 reference 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!ticker) return
    void ipc.invoke(IPC_CHANNELS.TRANSCRIPT_DIFF_SUBSCRIBE, { ticker })
    return () => {
      void ipc.invoke(IPC_CHANNELS.TRANSCRIPT_DIFF_UNSUBSCRIBE, { ticker })
    }
  }, [ticker])

  const state = byTicker.get(ticker ?? '')
  return {
    items: state?.items ?? [],
    previousCall: state?.previousCall ?? null,
    clear,
  }
}
