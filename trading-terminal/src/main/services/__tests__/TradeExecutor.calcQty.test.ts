import { describe, it, expect } from 'vitest'
import { calcQty, failureReason, type TradeSignal } from '../TradeExecutor'

type Balance = { orderableCash: number; holdings: { ticker: string; qty: number }[] }

function buy(ratio: number, ticker = 'TSLA'): TradeSignal {
  return { trade_id: 't1', action: 'BUY', order_ratio: ratio, ticker, ai_score: 0.9 }
}

function sell(ratio: number, ticker = 'TSLA'): TradeSignal {
  return { trade_id: 't1', action: 'SELL', order_ratio: ratio, ticker, ai_score: 0.1 }
}

function balance(orderableCash: number, holdings: Balance['holdings'] = []): Balance {
  return { orderableCash, holdings }
}

describe('calcQty — BUY', () => {
  it('정상 케이스: 1000 × 0.1 / 10 = 10주', () => {
    expect(calcQty(buy(0.1), balance(1000), 10)).toBe(10)
  })

  it('floor 절삭: 1000 × 0.1 / 33 = 3.03 → 3주', () => {
    expect(calcQty(buy(0.1), balance(1000), 33)).toBe(3)
  })

  it('1주 미만: 100 × 0.05 / 200 = 0.025 → 0주', () => {
    expect(calcQty(buy(0.05), balance(100), 200)).toBe(0)
  })

  it('예수금 0 → 0주', () => {
    expect(calcQty(buy(0.5), balance(0), 50)).toBe(0)
  })

  it('현재가 0 → 0주 (0 나눗셈 가드)', () => {
    expect(calcQty(buy(0.5), balance(1000), 0)).toBe(0)
  })

  it('NaN 예수금 가드 → 0주', () => {
    expect(calcQty(buy(0.5), balance(Number.NaN), 50)).toBe(0)
  })

  it('Infinity 가격 가드 → 0주', () => {
    expect(calcQty(buy(0.5), balance(1000), Number.POSITIVE_INFINITY)).toBe(0)
  })

  it('음수 예수금 → 0주', () => {
    expect(calcQty(buy(0.5), balance(-100), 50)).toBe(0)
  })

  it('음수 현재가 → 0주', () => {
    expect(calcQty(buy(0.5), balance(1000), -10)).toBe(0)
  })
})

describe('calcQty — SELL', () => {
  // SELL은 currentPrice를 쓰지 않지만 시그니처상 인자가 필요 — 0을 넣는다.
  const ANY_PRICE = 0

  it('정상 케이스: 보유 10주 × 0.5 = 5주', () => {
    expect(calcQty(sell(0.5), balance(0, [{ ticker: 'TSLA', qty: 10 }]), ANY_PRICE)).toBe(5)
  })

  it('미보유 종목 → 0주', () => {
    expect(calcQty(sell(0.5, 'TSLA'), balance(0, []), ANY_PRICE)).toBe(0)
  })

  it('다른 ticker만 보유 → 0주', () => {
    expect(
      calcQty(sell(0.5, 'TSLA'), balance(0, [{ ticker: 'AAPL', qty: 100 }]), ANY_PRICE),
    ).toBe(0)
  })

  it('floor → 0: 1주 × 0.4 = 0.4 → 0주', () => {
    expect(calcQty(sell(0.4), balance(0, [{ ticker: 'TSLA', qty: 1 }]), ANY_PRICE)).toBe(0)
  })

  it('보유 0주 → 0주', () => {
    expect(calcQty(sell(0.5), balance(0, [{ ticker: 'TSLA', qty: 0 }]), ANY_PRICE)).toBe(0)
  })
})

describe('calcQty — ratio 경계값', () => {
  it('ratio 0 → 0주 (BUY)', () => {
    expect(calcQty(buy(0), balance(1000), 10)).toBe(0)
  })

  it('ratio 1 (경계 포함): 100 × 1 / 10 = 10주', () => {
    expect(calcQty(buy(1), balance(100), 10)).toBe(10)
  })

  it('ratio 1.01 (1 초과) → 0주', () => {
    expect(calcQty(buy(1.01), balance(1000), 10)).toBe(0)
  })

  it('ratio 음수 → 0주', () => {
    expect(calcQty(buy(-0.5), balance(1000), 10)).toBe(0)
  })

  it('ratio NaN → 0주', () => {
    expect(calcQty(buy(Number.NaN), balance(1000), 10)).toBe(0)
  })
})

describe('failureReason — 분기별 사유 메시지', () => {
  it('비정상 ratio → "비정상 order_ratio" 메시지', () => {
    const reason = failureReason(buy(1.5), balance(1000), 10)
    expect(reason).toContain('비정상 order_ratio')
    expect(reason).toContain('1.5')
  })

  it('BUY + 현재가 0 → "현재가 조회 실패"', () => {
    expect(failureReason(buy(0.5), balance(1000), 0)).toBe('현재가 조회 실패')
  })

  it('BUY + 예수금 0 → "예수금 부족"', () => {
    expect(failureReason(buy(0.5), balance(0), 10)).toBe('예수금 부족')
  })

  it('BUY + 1주 가격 미만 → "예수금 대비 주문 비율..."', () => {
    expect(failureReason(buy(0.05), balance(100), 200)).toBe(
      '예수금 대비 주문 비율이 1주 가격에 못 미침',
    )
  })

  it('SELL + 미보유 → "보유 수량 없음"', () => {
    expect(failureReason(sell(0.5), balance(0, []), 0)).toBe('보유 수량 없음')
  })

  it('SELL + floor 미달 → "보유수량 대비 비율..."', () => {
    const reason = failureReason(sell(0.4), balance(0, [{ ticker: 'TSLA', qty: 1 }]), 0)
    expect(reason).toBe('보유수량 대비 비율이 1주에 못 미침')
  })
})
