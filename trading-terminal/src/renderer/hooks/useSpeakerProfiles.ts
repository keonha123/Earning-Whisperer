import { useEffect, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import type { SpeakerProfile } from '../types/speakerProfile'

/**
 * useSpeakerProfiles — 콜 참가자 명부 조회.
 *
 * 명부는 회차 내내 바뀌지 않으므로 트레이딩 룸 진입 시 한 번만 가져온다.
 * 실패하거나 명부가 비면 빈 배열 — 호출 측은 그때 프로필 진입점을 감춘다.
 *
 * `ticker` 는 재조회 트리거로만 쓴다. 시연 백엔드는 준비된 스크립트 한 벌만 들고 있어서
 * 종목을 인자로 받지 않는다 (Contract 7.8). 여러 콜을 동시에 재생하게 되면 그때
 * 엔드포인트에 ticker 파라미터를 추가하고 여기서 함께 보내야 한다.
 */
export function useSpeakerProfiles(ticker: string | null): readonly SpeakerProfile[] {
  const [profiles, setProfiles] = useState<readonly SpeakerProfile[]>([])

  useEffect(() => {
    if (!ticker) {
      setProfiles([])
      return
    }
    let cancelled = false
    ipc
      .invoke<SpeakerProfile[]>(IPC_CHANNELS.DEMO_EARNINGS_SPEAKERS)
      .then((list) => {
        if (!cancelled) setProfiles(Array.isArray(list) ? list : [])
      })
      .catch(() => {
        if (!cancelled) setProfiles([])
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  return profiles
}
