import { describe, it, expect, beforeEach } from 'vitest'
import { useTradingStore } from '../useTradingStore'
import type { TradeSignal, TradingMode } from '../useTradingStore'
import { useUserStore } from '../useUserStore'

const signal: TradeSignal = {
  trade_id: 'T-1',
  action: 'BUY',
  order_ratio: 0.1,
  ticker: 'AAPL',
  ai_score: 0.9,
}

function setUserMode(tradingMode: TradingMode) {
  useUserStore.getState().setSettings({ tradingMode })
}

beforeEach(() => {
  useTradingStore.setState({
    mode: 'MANUAL',
    isForcedManual: false,
    forcedManualReason: null,
    activeSignal: null,
    pendingConfirm: null,
    lastExecutedTrade: null,
    signalHistory: [],
    isSessionActive: false,
    sessionTicker: null,
  })
  setUserMode('MANUAL')
})

describe('useTradingStore.receiveSignal — H7 모드 이중 보관', () => {
  it('useUserStore.settings.tradingMode 가 SEMI_AUTO 면 pendingConfirm 을 세팅한다', () => {
    setUserMode('SEMI_AUTO')

    useTradingStore.getState().receiveSignal(signal)

    const s = useTradingStore.getState()
    expect(s.pendingConfirm).toEqual(signal)
    expect(s.activeSignal).toEqual(signal)
    expect(s.signalHistory[0].status).toBe('PENDING')
  })

  it('MANUAL 이면 IGNORED 로 기록하고 pendingConfirm 을 세팅하지 않는다', () => {
    setUserMode('MANUAL')

    useTradingStore.getState().receiveSignal(signal)

    const s = useTradingStore.getState()
    expect(s.pendingConfirm).toBeNull()
    expect(s.signalHistory[0].status).toBe('IGNORED')
  })

  it('AUTO_PILOT 이면 PENDING 으로만 기록하고 pendingConfirm 은 없다', () => {
    setUserMode('AUTO_PILOT')

    useTradingStore.getState().receiveSignal(signal)

    const s = useTradingStore.getState()
    expect(s.pendingConfirm).toBeNull()
    expect(s.signalHistory[0].status).toBe('PENDING')
  })

  it('로그인 직후처럼 useTradingStore.mode 가 MANUAL 로 남아 있어도 사용자 설정(SEMI_AUTO)을 따른다', () => {
    // H7 회귀: AuthPage 가 setSettings 만 호출하고 setMode 를 부르지 않는 상황.
    useTradingStore.setState({ mode: 'MANUAL' })
    setUserMode('SEMI_AUTO')

    useTradingStore.getState().receiveSignal(signal)

    expect(useTradingStore.getState().pendingConfirm).toEqual(signal)
    expect(useTradingStore.getState().signalHistory[0].status).toBe('PENDING')
  })

  it('useTradingStore.mode 가 SEMI_AUTO 라도 사용자 설정이 MANUAL 이면 IGNORED', () => {
    useTradingStore.setState({ mode: 'SEMI_AUTO' })
    setUserMode('MANUAL')

    useTradingStore.getState().receiveSignal(signal)

    expect(useTradingStore.getState().pendingConfirm).toBeNull()
    expect(useTradingStore.getState().signalHistory[0].status).toBe('IGNORED')
  })
})
