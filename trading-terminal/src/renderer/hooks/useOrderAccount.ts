import { useEffect, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useUserStore } from '../store/useUserStore'

/** 주문이 나가는 계좌. */
export type OrderAccount = 'KIS_PAPER' | 'KIS_REAL' | 'SELF_PAPER'

export const ACCOUNT_LABELS: Record<OrderAccount, string> = {
  KIS_PAPER: 'KIS 모의투자',
  KIS_REAL: 'KIS 실전투자',
  SELF_PAPER: '페이퍼 계정',
}

/**
 * 지금 주문이 나가는 계좌를 판단한다.
 *
 * 페이퍼 계정은 KIS 를 거치지 않는다. KIS 계좌면 모의 · 실전 설정을 main 에 묻는다.
 * 로그인 정보(계좌 종류)나 설정을 아직 모르면 null — 모르는 채로 주문을 보내지 않게 호출 측이 막는다.
 */
export function useOrderAccount(): OrderAccount | null {
  const accountType = useUserStore((s) => s.accountType)
  const [isPaperTrading, setIsPaperTrading] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    ipc
      .invoke<boolean>(IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING)
      .then((v) => {
        if (!cancelled) setIsPaperTrading(v !== false)
      })
      .catch(() => {
        // 모르는 채로 둔다 — 계좌 표시가 "확인 중" 으로 남는다.
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (accountType === 'SELF_PAPER') return 'SELF_PAPER'
  if (accountType == null || isPaperTrading === null) return null
  return isPaperTrading ? 'KIS_PAPER' : 'KIS_REAL'
}
