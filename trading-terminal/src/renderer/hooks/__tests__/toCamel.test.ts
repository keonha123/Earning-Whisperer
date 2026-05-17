import { describe, it, expect } from 'vitest'
import { toCamel, isValidPayload } from '../useMarketIndices'

/**
 * toCamel — Backend snake_case payload → store camelCase item 변환.
 * isValidPayload — 6필드 typeof 가드.
 *
 * hook 자체는 useEffect/zustand 의존이라 jsdom 환경이 필요하지만,
 * 두 helper 는 순수 함수이므로 node 환경에서 단위 테스트 가능.
 */
describe('toCamel', () => {
  it('change_percent → changePercent 매핑', () => {
    const out = toCamel({
      symbol: 'SPX',
      price: 5123.4,
      change_percent: 0.21,
      trend: 'up',
      format: 'index',
      timestamp: 1714400000,
    })
    expect(out.changePercent).toBe(0.21)
    // snake_case 키는 결과에 남아있지 않아야 한다.
    expect((out as unknown as Record<string, unknown>).change_percent).toBeUndefined()
  })

  it('나머지 필드(symbol/price/trend/format/timestamp) 는 그대로 보존', () => {
    const out = toCamel({
      symbol: 'VIX',
      price: 13.6,
      change_percent: -1.1,
      trend: 'down',
      format: 'index',
      timestamp: 1714400000,
    })
    expect(out.symbol).toBe('VIX')
    expect(out.price).toBe(13.6)
    expect(out.trend).toBe('down')
    expect(out.format).toBe('index')
    expect(out.timestamp).toBe(1714400000)
  })

  it('change_percent: 0 같은 falsy 값도 보존 (|| 연산자 오용 회귀 가드)', () => {
    const out = toCamel({
      symbol: 'DXY',
      price: 105.0,
      change_percent: 0,
      trend: 'neutral',
      format: 'index',
      timestamp: 1714400000,
    })
    expect(out.changePercent).toBe(0)
  })
})

describe('isValidPayload', () => {
  const valid = {
    symbol: 'SPX',
    price: 5123.4,
    change_percent: 0.21,
    trend: 'up',
    format: 'index',
    timestamp: 1714400000,
  }

  it('정상 6필드 페이로드는 통과', () => {
    expect(isValidPayload(valid)).toBe(true)
  })

  it('null/undefined/원시 타입은 false', () => {
    expect(isValidPayload(null)).toBe(false)
    expect(isValidPayload(undefined)).toBe(false)
    expect(isValidPayload(123)).toBe(false)
    expect(isValidPayload('SPX')).toBe(false)
  })

  it('필드 누락 시 false (symbol 누락)', () => {
    const { symbol: _drop, ...partial } = valid
    void _drop
    expect(isValidPayload(partial)).toBe(false)
  })

  it('필드 타입 불일치 시 false (price 가 string)', () => {
    expect(isValidPayload({ ...valid, price: '5123.4' })).toBe(false)
  })

  it('change_percent 가 string 이면 false', () => {
    expect(isValidPayload({ ...valid, change_percent: '0.21' })).toBe(false)
  })

  it('timestamp 가 string 이면 false', () => {
    expect(isValidPayload({ ...valid, timestamp: '1714400000' })).toBe(false)
  })
})
