import { describe, it, expect } from 'vitest'
import { applyTradeRecords, type TradeRecord } from '../sessionOrders'
import type { SessionOrder } from '../../components/trading/PositionOrderPanel'

function order(overrides: Partial<SessionOrder> = {}): SessionOrder {
  return {
    localId: 'WMT-BUY-1',
    side: 'BUY',
    qty: 2,
    requestedPrice: 100,
    status: 'PENDING',
    executedQty: 0,
    executedPrice: null,
    brokerOrderId: '0000044600',
    errorMessage: null,
    placedAt: 1,
    ...overrides,
  }
}

function trade(overrides: Partial<TradeRecord> = {}): TradeRecord {
  return {
    brokerOrderId: '0000044600',
    status: 'EXECUTED',
    executedQty: 2,
    executedPrice: 99.5,
    ...overrides,
  }
}

describe('applyTradeRecords — 주문 패널의 접수 주문 갱신', () => {
  it('백엔드가 체결로 확정한 주문은 체결로 바꾸고 체결 수량·가격을 채운다', () => {
    const [result] = applyTradeRecords([order()], [trade()])

    expect(result.status).toBe('EXECUTED')
    expect(result.executedQty).toBe(2)
    expect(result.executedPrice).toBe(99.5)
  })

  it('백엔드가 실패로 기록한 주문은 실패로 바꾼다', () => {
    const [result] = applyTradeRecords([order()], [trade({ status: 'FAILED', executedQty: 0, executedPrice: null })])

    expect(result.status).toBe('FAILED')
  })

  it('백엔드가 아직 PENDING 이면 그대로 둔다', () => {
    const orders = [order()]

    expect(applyTradeRecords(orders, [trade({ status: 'PENDING', executedQty: 0, executedPrice: null })])).toBe(orders)
  })

  it('주문번호가 같은 기록이 없으면 그대로 둔다', () => {
    const orders = [order()]

    expect(applyTradeRecords(orders, [trade({ brokerOrderId: '0000099999' })])).toBe(orders)
  })

  it('주문번호가 없는 주문(주문 실패)은 짝짓지 않는다', () => {
    const orders = [order({ status: 'FAILED', brokerOrderId: null })]

    expect(applyTradeRecords(orders, [trade({ brokerOrderId: null })])).toBe(orders)
  })

  it('이미 체결로 끝난 주문은 다시 덮어쓰지 않는다', () => {
    const done = order({ status: 'EXECUTED', executedQty: 2, executedPrice: 101 })
    const orders = [done]

    expect(applyTradeRecords(orders, [trade({ executedPrice: 99.5 })])).toBe(orders)
  })

  it('체결 수량은 주문 수량이 아니라 백엔드 기록의 체결 수량을 쓴다 (부분 체결)', () => {
    const [result] = applyTradeRecords([order({ qty: 2 })], [trade({ executedQty: 1 })])

    expect(result.status).toBe('EXECUTED')
    expect(result.qty).toBe(2)
    expect(result.executedQty).toBe(1)
  })

  it('백엔드가 EXPIRED 로 만료시킨 주문은 그대로 둔다 — 실제로 취소됐는지 알 수 없다', () => {
    const orders = [order()]

    expect(applyTradeRecords(orders, [trade({ status: 'EXPIRED', executedQty: 0, executedPrice: null })])).toBe(orders)
  })

  it('체결가가 0 이하면 null 로 둔다 — 체결조회가 가격을 못 받으면 백엔드가 0 으로 저장한다', () => {
    const [zero] = applyTradeRecords([order()], [trade({ executedPrice: 0 })])
    const [missing] = applyTradeRecords([order()], [trade({ executedPrice: null })])

    expect(zero.status).toBe('EXECUTED')
    expect(zero.executedPrice).toBeNull()
    expect(missing.executedPrice).toBeNull()
  })

  it('여러 주문 중 해당 주문만 바꾸고 나머지는 같은 객체로 둔다', () => {
    const other = order({ localId: 'WMT-SELL-2', side: 'SELL', brokerOrderId: '0000044601' })
    const result = applyTradeRecords([order(), other], [trade()])

    expect(result[0].status).toBe('EXECUTED')
    expect(result[1]).toBe(other)
  })
})
