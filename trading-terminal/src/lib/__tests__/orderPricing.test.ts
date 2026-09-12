import { describe, it, expect } from 'vitest'
import { IMMEDIATE_FILL_BUFFER, immediateFillPrice } from '../orderPricing'

describe('immediateFillPrice', () => {
  it('매수는 현재가에 버퍼를 얹고 호가 단위로 올림한다', () => {
    // 100 * 1.01 = 101 (정확히 떨어지는 경우)
    expect(immediateFillPrice('BUY', 100)).toBe(101)
    // 97.35 * 1.01 = 98.3235 → 올림 98.33
    expect(immediateFillPrice('BUY', 97.35)).toBe(98.33)
  })

  it('매도는 버퍼만큼 내리고 호가 단위로 내림한다', () => {
    expect(immediateFillPrice('SELL', 100)).toBe(99)
    // 97.35 * 0.99 = 96.3765 → 내림 96.37
    expect(immediateFillPrice('SELL', 97.35)).toBe(96.37)
  })

  it('결과는 항상 소수 2자리 이하다 (KIS 가 거부하는 호가를 만들지 않는다)', () => {
    for (const p of [1.234, 12.005, 333.333, 1999.999]) {
      for (const side of ['BUY', 'SELL'] as const) {
        const price = immediateFillPrice(side, p)
        expect(price).not.toBeNull()
        expect(Math.round((price as number) * 100)).toBeCloseTo((price as number) * 100, 9)
      }
    }
  })

  it('버퍼 방향이 체결에 유리한 쪽이다', () => {
    const cur = 250.5
    expect(immediateFillPrice('BUY', cur)).toBeGreaterThan(cur)
    expect(immediateFillPrice('SELL', cur) as number).toBeLessThan(cur)
  })

  it('현재가가 0/음수/NaN/Infinity 면 null — 0달러 지정가가 나가지 않는다', () => {
    for (const bad of [0, -1, NaN, Infinity, -Infinity]) {
      expect(immediateFillPrice('BUY', bad)).toBeNull()
      expect(immediateFillPrice('SELL', bad)).toBeNull()
    }
  })

  it('매도 버퍼가 가격 전체를 깎아 0 이 되는 초저가는 null', () => {
    // 0.005 * 0.99 = 0.00495 → 내림 0 → 주문 불가로 처리
    expect(immediateFillPrice('SELL', 0.005)).toBeNull()
  })

  it('버퍼는 1%', () => {
    expect(IMMEDIATE_FILL_BUFFER).toBe(0.01)
  })
})
