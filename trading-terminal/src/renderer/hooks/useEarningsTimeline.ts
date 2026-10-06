import { useEffect, useRef, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import type { EarningsTimelineData } from '../../lib/types/earningsTimeline'

export type EarningsTimelineStatus = 'loading' | 'ready' | 'error'

const EMPTY: EarningsTimelineData = { live: null, groups: [] }

/**
 * 어닝콜 일정 — 처음 한 번 가져오고 이후 갱신을 구독한다.
 *
 * 실패를 "불러오는 중" 으로 남기지 않도록 상태를 따로 든다. 갱신이 오면 실패 상태도 풀린다.
 * `live` 는 서버가 예정 시각 창으로 추정한 진행 중 콜이라, 실제 시작 여부는 콜 화면의 자막으로 확인한다.
 */
export function useEarningsTimeline() {
  const [data, setData] = useState<EarningsTimelineData>(EMPTY)
  const [status, setStatus] = useState<EarningsTimelineStatus>('loading')
  const [attempt, setAttempt] = useState(0)
  // 갱신을 받을 때마다 올린다. 다시 시도한 GET 이 그보다 늦게 오면 오래된 일정이라 버린다.
  const pushVersion = useRef(0)

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    const versionAtRequest = pushVersion.current
    ipc
      .invoke<EarningsTimelineData>(IPC_CHANNELS.EARNINGS_TIMELINE_GET)
      .then((d) => {
        if (cancelled) return
        if (pushVersion.current !== versionAtRequest) {
          setStatus('ready')
          return
        }
        setData(d ?? EMPTY)
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [attempt])

  useEffect(() => {
    return ipc.on(IPC_CHANNELS.EARNINGS_TIMELINE_UPDATE, (d) => {
      pushVersion.current += 1
      setData((d as EarningsTimelineData | null) ?? EMPTY)
      setStatus('ready')
    })
  }, [])

  return { data, status, retry: () => setAttempt((n) => n + 1) }
}
