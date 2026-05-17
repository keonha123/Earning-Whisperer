import { describe, it, expect, beforeEach } from 'vitest'
import { usePortfolioStore } from '../usePortfolioStore'
import { IpcError, isIpcError } from '../../../lib/types/ipcError'

beforeEach(() => {
  // 각 테스트마다 store 초기화 — zustand persist 미사용이므로 setState 로 reset.
  usePortfolioStore.setState({
    orderableCash: 0,
    totalCash: 0,
    holdings: [],
    lastSyncedAt: null,
    isSyncing: false,
    error: null,
    balanceFetchError: null,
  })
})

describe('usePortfolioStore.setBalanceFetchError — F-2 stale 마커', () => {
  it('IpcError 인스턴스 그대로 보존 (정규화 우회)', () => {
    const err = new IpcError('KIS_ERROR', 'KIS API 5xx')

    usePortfolioStore.getState().setBalanceFetchError(err)

    const stored = usePortfolioStore.getState().balanceFetchError
    expect(stored).toBe(err)
    expect(stored?.code).toBe('KIS_ERROR')
    expect(stored?.message).toBe('KIS API 5xx')
  })

  it('일반 Error → IpcError("UNKNOWN") 으로 정규화', () => {
    const err = new Error('네트워크 끊김')

    usePortfolioStore.getState().setBalanceFetchError(err)

    const stored = usePortfolioStore.getState().balanceFetchError
    expect(stored).not.toBeNull()
    expect(isIpcError(stored)).toBe(true)
    expect(stored?.code).toBe('UNKNOWN')
    expect(stored?.message).toBe('네트워크 끊김')
  })

  it('string 등 unknown 타입도 IpcError 로 정규화', () => {
    usePortfolioStore.getState().setBalanceFetchError('raw string error')

    const stored = usePortfolioStore.getState().balanceFetchError
    expect(stored).not.toBeNull()
    expect(stored?.code).toBe('UNKNOWN')
    expect(stored?.message).toBe('raw string error')
  })

  it('null 전달 → balanceFetchError null 로 clear', () => {
    usePortfolioStore.setState({
      balanceFetchError: new IpcError('NETWORK', '연결 끊김'),
    })

    usePortfolioStore.getState().setBalanceFetchError(null)

    expect(usePortfolioStore.getState().balanceFetchError).toBeNull()
  })

  it('undefined 전달 → null 로 clear (방어적 처리)', () => {
    usePortfolioStore.setState({
      balanceFetchError: new IpcError('NETWORK', '연결 끊김'),
    })

    usePortfolioStore.getState().setBalanceFetchError(undefined)

    expect(usePortfolioStore.getState().balanceFetchError).toBeNull()
  })

  it('Error 가 아닌 객체 (number 등) 도 String 변환 후 정규화', () => {
    usePortfolioStore.getState().setBalanceFetchError(404)

    const stored = usePortfolioStore.getState().balanceFetchError
    expect(stored?.code).toBe('UNKNOWN')
    expect(stored?.message).toBe('404')
  })
})

describe('usePortfolioStore.clearBalanceFetchError', () => {
  it('balanceFetchError 를 null 로 reset', () => {
    usePortfolioStore.setState({
      balanceFetchError: new IpcError('AUTH_EXPIRED', '토큰 만료'),
    })

    usePortfolioStore.getState().clearBalanceFetchError()

    expect(usePortfolioStore.getState().balanceFetchError).toBeNull()
  })

  it('이미 null 이어도 안전 (no-op)', () => {
    usePortfolioStore.getState().clearBalanceFetchError()

    expect(usePortfolioStore.getState().balanceFetchError).toBeNull()
  })
})

describe('usePortfolioStore.setBalance — 성공 시 stale 마커 자동 제거', () => {
  it('이전 balanceFetchError 상태에서 setBalance → balanceFetchError 자동 null', () => {
    // 실패 → 사용자에게 overlay 표시
    usePortfolioStore.setState({
      balanceFetchError: new IpcError('NETWORK', '연결 끊김'),
    })
    expect(usePortfolioStore.getState().balanceFetchError).not.toBeNull()

    // 재시도 성공
    usePortfolioStore.getState().setBalance(1000, 1500, [])

    // overlay 자동 제거
    expect(usePortfolioStore.getState().balanceFetchError).toBeNull()
    expect(usePortfolioStore.getState().error).toBeNull()
    // 잔고도 정상 반영
    expect(usePortfolioStore.getState().orderableCash).toBe(1000)
    expect(usePortfolioStore.getState().totalCash).toBe(1500)
    // lastSyncedAt epoch sec 갱신됨 (현재 시점 ± 2초 이내).
    const now = Math.floor(Date.now() / 1000)
    const synced = usePortfolioStore.getState().lastSyncedAt
    expect(synced).not.toBeNull()
    expect(Math.abs(synced! - now)).toBeLessThanOrEqual(2)
  })

  it('balanceFetchError 가 없는 상태에서도 setBalance 정상 동작 (회귀)', () => {
    usePortfolioStore.getState().setBalance(500, 700, [
      { ticker: 'AAPL', qty: 1, avgPrice: 150, currentPrice: 160 },
    ])

    const s = usePortfolioStore.getState()
    expect(s.orderableCash).toBe(500)
    expect(s.totalCash).toBe(700)
    expect(s.holdings).toHaveLength(1)
    expect(s.balanceFetchError).toBeNull()
    expect(s.error).toBeNull()
  })
})

describe('usePortfolioStore — 초기 상태 vs 에러 상태 구분 (F-2 핵심)', () => {
  it('초기 상태: balanceFetchError === null 이고 lastSyncedAt === null (loading)', () => {
    const s = usePortfolioStore.getState()
    expect(s.balanceFetchError).toBeNull()
    expect(s.lastSyncedAt).toBeNull()
  })

  it('첫 조회 실패: balanceFetchError 세팅 + lastSyncedAt null (한번도 성공 못함)', () => {
    usePortfolioStore.getState().setBalanceFetchError(new IpcError('NETWORK', '연결 끊김'))

    const s = usePortfolioStore.getState()
    expect(s.balanceFetchError).not.toBeNull()
    expect(s.lastSyncedAt).toBeNull()
  })

  it('성공 후 재조회 실패: balanceFetchError 세팅 + lastSyncedAt 이전 값 보존', () => {
    // 1차 성공
    usePortfolioStore.getState().setBalance(100, 200, [])
    const firstSync = usePortfolioStore.getState().lastSyncedAt

    // 2차 실패
    usePortfolioStore.getState().setBalanceFetchError(new IpcError('KIS_ERROR', 'KIS 5xx'))

    const s = usePortfolioStore.getState()
    expect(s.balanceFetchError).not.toBeNull()
    // 마지막 성공 동기화 시각은 보존 → overlay 가 "마지막 정상 조회 N분 전" 표시 가능.
    expect(s.lastSyncedAt).toBe(firstSync)
    // 이전 잔고도 보존됨 (사용자에게 overlay 가 가려서 보여주지 않음).
    expect(s.totalCash).toBe(200)
  })
})
