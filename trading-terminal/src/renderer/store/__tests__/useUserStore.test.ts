import { describe, it, expect, beforeEach } from 'vitest'
import { useUserStore } from '../useUserStore'
import { useTradingStore } from '../useTradingStore'
import { usePortfolioStore } from '../usePortfolioStore'
import { useWatchlistStore } from '../useWatchlistStore'
import { usePricesStore } from '../usePricesStore'
import { useTranscriptStore } from '../useTranscriptStore'
import { useDrawerStore } from '../useDrawerStore'
import { useMarketIndicesStore } from '../useMarketIndicesStore'

/**
 * 로그아웃(useUserStore.clear()) 시 사용자 데이터가 남아있는 store 가 없어야 한다.
 * 재로그인 시 이전 계정의 잔여 상태(보유종목/신호/시세/트랜스크립트 등)가 노출되는 것을 막는다.
 */
describe('useUserStore.clear() — 로그아웃 전체 store 리셋', () => {
  beforeEach(() => {
    useUserStore.getState().clear()
  })

  it('user 상태를 초기화한다', () => {
    useUserStore.getState().setUser({ id: 1, email: 'a@b.c', nickname: 'nick', role: 'PRO' })
    useUserStore.getState().setSettings({ tradingMode: 'AUTO_PILOT', aiScoreThreshold: 0.9 })
    useUserStore.getState().setAccountType('KIS_REAL')

    useUserStore.getState().clear()

    const s = useUserStore.getState()
    expect(s.userId).toBeNull()
    expect(s.email).toBeNull()
    expect(s.nickname).toBeNull()
    expect(s.plan).toBe('FREE')
    expect(s.accountType).toBeNull()
    expect(s.settings.tradingMode).toBe('MANUAL')
    expect(s.settings.aiScoreThreshold).toBe(0.6)
  })

  it('useTradingStore 를 초기화한다', () => {
    useTradingStore.getState().setMode('AUTO_PILOT')
    useTradingStore.getState().forceManual('연결 끊김')
    useTradingStore.getState().receiveSignal({
      trade_id: 't-1',
      action: 'BUY',
      order_ratio: 0.1,
      ticker: 'NVDA',
      ai_score: 0.9,
    })
    useTradingStore.getState().setPendingConfirm({
      trade_id: 't-1',
      action: 'BUY',
      order_ratio: 0.1,
      ticker: 'NVDA',
      ai_score: 0.9,
    })
    useTradingStore.getState().setLastExecutedTrade({
      tradeId: 't-1',
      status: 'EXECUTED',
      orderId: 'o-1',
      executedPrice: 100,
      executedQty: 1,
      errorMessage: null,
    })
    useTradingStore.getState().setSession(true, 'NVDA')

    useUserStore.getState().clear()

    const s = useTradingStore.getState()
    expect(s.mode).toBe('MANUAL')
    expect(s.isForcedManual).toBe(false)
    expect(s.forcedManualReason).toBeNull()
    expect(s.activeSignal).toBeNull()
    expect(s.pendingConfirm).toBeNull()
    expect(s.lastExecutedTrade).toBeNull()
    expect(s.signalHistory).toEqual([])
    expect(s.isSessionActive).toBe(false)
    expect(s.sessionTicker).toBeNull()
  })

  it('usePortfolioStore 를 초기화한다', () => {
    usePortfolioStore.getState().setBalance(1000, 2000, [
      { ticker: 'AAPL', qty: 3, avgPrice: 100, currentPrice: 110 },
    ])
    usePortfolioStore.getState().setError('에러')
    usePortfolioStore.getState().setSyncing(true)
    usePortfolioStore.getState().setBalanceFetchError(new Error('실패'))

    useUserStore.getState().clear()

    const s = usePortfolioStore.getState()
    expect(s.orderableCash).toBe(0)
    expect(s.totalCash).toBe(0)
    expect(s.holdings).toEqual([])
    expect(s.lastSyncedAt).toBeNull()
    expect(s.isSyncing).toBe(false)
    expect(s.error).toBeNull()
    expect(s.balanceFetchError).toBeNull()
  })

  it('useWatchlistStore 를 초기화한다', () => {
    useWatchlistStore.getState().setItems([
      { ticker: 'AAPL', companyName: 'Apple', sector: 'Tech' },
    ])

    useUserStore.getState().clear()

    const s = useWatchlistStore.getState()
    expect(s.items).toEqual([])
    expect(s.isLoaded).toBe(false)
  })

  it('usePricesStore 를 초기화한다', () => {
    usePricesStore.getState().setSnapshot({
      AAPL: { currentPrice: 110, previousClose: 100, lastUpdated: 1 },
    })

    useUserStore.getState().clear()

    const s = usePricesStore.getState()
    expect(s.prices).toEqual({})
    expect(s.isLoaded).toBe(false)
  })

  it('useTranscriptStore 를 초기화한다', () => {
    useTranscriptStore.getState().setCurrentTicker('NVDA')
    useTranscriptStore.getState().upsertSegment({
      ticker: 'NVDA',
      call_id: 'NVDA-2025-Q3',
      sequence: 1,
      start_ms: 0,
      end_ms: 1000,
      text: 'hello',
      timestamp: 1,
    })

    useUserStore.getState().clear()

    const s = useTranscriptStore.getState()
    expect(s.byTicker.size).toBe(0)
    expect(s.currentTicker).toBeNull()
  })

  it('useDrawerStore 를 초기화한다', () => {
    useDrawerStore.getState().open('AAPL')
    expect(useDrawerStore.getState().openTicker).toBe('AAPL')

    useUserStore.getState().clear()

    expect(useDrawerStore.getState().openTicker).toBeNull()
  })

  it('useMarketIndicesStore 를 초기화한다', () => {
    useMarketIndicesStore.getState().setIndices([
      {
        symbol: 'SPX',
        price: 5000,
        changePercent: 1.2,
        trend: 'up',
        format: 'index',
        timestamp: 100,
      },
    ])

    useUserStore.getState().clear()

    const s = useMarketIndicesStore.getState()
    expect(s.indices).toEqual([])
    expect(s.lastUpdatedAt).toBeNull()
    expect(s.isLoaded).toBe(false)
  })
})
