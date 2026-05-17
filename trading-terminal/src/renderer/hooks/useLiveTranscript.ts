import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import {
  useTranscriptStore,
  type TranscriptSegment,
} from '../store/useTranscriptStore'

/**
 * useLiveTranscript — 실시간 어닝콜 트랜스크립트 사이드이펙트 훅.
 *
 * Backend Contract 4.5 STOMP /topic/transcript/{ticker} 와 연결.
 *
 * 동작:
 *  1) ticker 가 truthy 하면 Main 에 SUBSCRIBE IPC 발송 + currentTicker 갱신.
 *  2) ticker 변경 / 언마운트 시 이전 ticker UNSUBSCRIBE.
 *  3) TRANSCRIPT_SEGMENT_RECEIVED IPC 수신 시 store.upsertSegment 호출.
 *
 * 반환값:
 *  - segments: 현재 ticker 의 정렬된 segment 배열 (오래된→최신).
 *  - endedCallIds: 종료된 call 식별자 집합 (LIVE 판정용).
 *
 * useMarketIndices 와 동일한 hook + store 분리 패턴.
 */
export function useLiveTranscript(ticker: string | null): {
  segments: readonly TranscriptSegment[]
  endedCallIds: ReadonlySet<string>
} {
  const upsertSegment = useTranscriptStore((s) => s.upsertSegment)
  const setCurrentTicker = useTranscriptStore((s) => s.setCurrentTicker)
  const byTicker = useTranscriptStore((s) => s.byTicker)

  // 1) IPC 구독 — 마운트 시 1회 등록, 언마운트 시 해제. ticker 변경과 무관하게 유지.
  useEffect(() => {
    const unsubscribe = ipc.on(
      IPC_CHANNELS.TRANSCRIPT_SEGMENT_RECEIVED,
      (payload: unknown) => {
        // store 의 upsertSegment 가 자체적으로 isValidTranscriptPayload 검증을 수행.
        upsertSegment(payload)
      },
    )
    return () => {
      unsubscribe()
    }
    // upsertSegment 는 zustand 가 동일 reference 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 2) ticker 별 SUBSCRIBE/UNSUBSCRIBE — ticker 변경 시 cleanup 으로 이전 ticker 해제.
  useEffect(() => {
    if (!ticker) {
      setCurrentTicker(null)
      return
    }
    setCurrentTicker(ticker)
    void ipc.invoke(IPC_CHANNELS.TRANSCRIPT_SUBSCRIBE, { ticker })

    return () => {
      void ipc.invoke(IPC_CHANNELS.TRANSCRIPT_UNSUBSCRIBE, { ticker })
    }
    // setCurrentTicker 은 zustand reference 안정.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  const tickerState = ticker ? byTicker.get(ticker) : undefined
  return {
    segments: tickerState?.segments ?? [],
    endedCallIds: tickerState?.endedCallIds ?? new Set<string>(),
  }
}
