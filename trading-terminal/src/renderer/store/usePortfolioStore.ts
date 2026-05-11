import { create } from 'zustand'
import { IpcError, isIpcError } from '../../lib/types/ipcError'

export interface Holding {
  ticker: string
  qty: number
  avgPrice: number
  currentPrice: number
}

interface PortfolioState {
  orderableCash: number  // 즉시 주문가능 외화금액
  totalCash: number      // 외화 총 보유금액 (포트폴리오 표시용)
  holdings: Holding[]
  lastSyncedAt: number | null
  isSyncing: boolean
  /**
   * 사용자 가시 인라인 배너용 일반 메시지.
   * F-2 이전부터 존재. balanceFetchError 와 별개로 유지 (DashboardPage 상단 배너 호환).
   */
  error: string | null
  /**
   * F-2: 마지막 KIS_GET_BALANCE 가 실패했는가?
   * null = 실패 이력 없음 (성공 또는 미시도). 컴포넌트는 이 값으로 stale overlay 렌더 분기.
   * 성공 시 setBalance 가 자동 clear → overlay 자동 제거.
   *
   * IpcError 인스턴스를 보존하는 이유:
   *  - code 별 차등 메시지 (KIS_ERROR vs NETWORK vs AUTH_EXPIRED)
   *  - 사용자 재시도 가능 여부 판단 (AUTH_EXPIRED → 재로그인 유도)
   *  - 비-IPC Error 도 IpcError('UNKNOWN', ...) 으로 wrap 해서 일관 타입 유지.
   */
  balanceFetchError: IpcError | null

  setBalance: (orderableCash: number, totalCash: number, holdings: Holding[]) => void
  startSync: () => void
  setSyncing: (v: boolean) => void
  setError: (msg: string | null) => void
  /**
   * F-2: balance 조회 실패 마킹.
   * IpcError / Error / unknown 모두 받아서 IpcError 로 정규화.
   * null 전달 시 clear (clearBalanceFetchError 와 동일).
   */
  setBalanceFetchError: (err: unknown) => void
  /** F-2: balance fetch error 명시적 clear. 재시도 직전 또는 dismiss 시 호출. */
  clearBalanceFetchError: () => void
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  orderableCash: 0,
  totalCash: 0,
  holdings: [],
  lastSyncedAt: null,
  isSyncing: false,
  error: null,
  balanceFetchError: null,

  setBalance: (orderableCash, totalCash, holdings) =>
    set({
      orderableCash,
      totalCash,
      holdings,
      lastSyncedAt: Math.floor(Date.now() / 1000),
      error: null,
      // 성공 응답 도착 → stale 마커 자동 제거.
      balanceFetchError: null,
    }),

  startSync: () => set({ isSyncing: true, error: null }),

  setSyncing: (isSyncing) => set({ isSyncing }),

  setError: (error) => set({ error }),

  setBalanceFetchError: (err) => {
    if (err === null || err === undefined) {
      set({ balanceFetchError: null })
      return
    }
    const normalized = isIpcError(err)
      ? err
      : new IpcError('UNKNOWN', err instanceof Error ? err.message : String(err))
    set({ balanceFetchError: normalized })
  },

  clearBalanceFetchError: () => set({ balanceFetchError: null }),
}))
