import { describe, it, expect, beforeEach } from 'vitest'
import { usePricesStore } from '../usePricesStore'
import type { PriceUpdate } from '../../../lib/priceTypes'

beforeEach(() => {
  // 각 테스트마다 store 초기화 — zustand persist 미사용이므로 setState 로 reset.
  usePricesStore.setState({ prices: {}, isLoaded: false })
})

describe('usePricesStore.upsertBatch — reference equality 보존', () => {
  it('빈 batch + isLoaded=false → isLoaded=true 로 전환되지만 prices reference 동일', () => {
    const before = usePricesStore.getState()
    expect(before.isLoaded).toBe(false)
    const beforePrices = before.prices

    usePricesStore.getState().upsertBatch([])

    const after = usePricesStore.getState()
    expect(after.isLoaded).toBe(true)
    // prices 는 빈 객체 그대로 reference 보존.
    expect(after.prices).toBe(beforePrices)
  })

  it('빈 batch + isLoaded=true → state 자체 reference 동일 (no-op)', () => {
    usePricesStore.setState({
      prices: { AAPL: { currentPrice: 100, lastUpdated: 1 } },
      isLoaded: true,
    })
    const before = usePricesStore.getState()

    usePricesStore.getState().upsertBatch([])

    const after = usePricesStore.getState()
    // 전체 state 가 그대로 유지 (zustand 가 동일 객체를 반환했을 때 re-render skip).
    expect(after.prices).toBe(before.prices)
    expect(after.isLoaded).toBe(true)
  })

  it('동일 값 batch → prices reference 동일 (re-render 스킵 보장)', () => {
    usePricesStore.setState({
      prices: {
        AAPL: { currentPrice: 100, lastUpdated: 1000 },
        TSLA: { currentPrice: 250, lastUpdated: 1000 },
      },
      isLoaded: true,
    })
    const beforePrices = usePricesStore.getState().prices

    const batch: PriceUpdate[] = [
      { ticker: 'AAPL', currentPrice: 100, lastUpdated: 1000 },
      { ticker: 'TSLA', currentPrice: 250, lastUpdated: 1000 },
    ]
    usePricesStore.getState().upsertBatch(batch)

    const afterPrices = usePricesStore.getState().prices
    // Object.is 동일성 — 새 객체를 만들지 않았음을 보장.
    expect(Object.is(afterPrices, beforePrices)).toBe(true)
  })

  it('신규 ticker 단건 → prices reference 변경 + isLoaded=true', () => {
    const before = usePricesStore.getState()
    expect(before.isLoaded).toBe(false)
    const beforePrices = before.prices

    usePricesStore.getState().upsertBatch([
      { ticker: 'AAPL', currentPrice: 100, lastUpdated: 1000 },
    ])

    const after = usePricesStore.getState()
    expect(after.isLoaded).toBe(true)
    expect(after.prices).not.toBe(beforePrices)
    expect(after.prices.AAPL).toEqual({ currentPrice: 100, lastUpdated: 1000 })
  })

  it('일부만 변경된 batch → 변경된 ticker 만 새 entry, 나머지 entry reference 동일', () => {
    const aaplEntry = { currentPrice: 100, lastUpdated: 1000 }
    const tslaEntry = { currentPrice: 250, lastUpdated: 1000 }
    usePricesStore.setState({
      prices: { AAPL: aaplEntry, TSLA: tslaEntry },
      isLoaded: true,
    })

    const batch: PriceUpdate[] = [
      // AAPL 은 동일 값 — 변경 없음
      { ticker: 'AAPL', currentPrice: 100, lastUpdated: 1000 },
      // TSLA 는 가격 변경
      { ticker: 'TSLA', currentPrice: 260, lastUpdated: 2000 },
    ]
    usePricesStore.getState().upsertBatch(batch)

    const after = usePricesStore.getState()
    // prices 객체 자체는 변경됨 (TSLA 갱신 때문).
    expect(after.prices.TSLA).toEqual({ currentPrice: 260, lastUpdated: 2000 })
    expect(after.prices.TSLA).not.toBe(tslaEntry)
    // AAPL entry 는 변경되지 않았으므로 기존 reference 유지.
    expect(after.prices.AAPL).toBe(aaplEntry)
  })

  it('currentPrice 만 변경되어도 reference 갱신', () => {
    usePricesStore.setState({
      prices: { AAPL: { currentPrice: 100, lastUpdated: 1000 } },
      isLoaded: true,
    })
    const beforePrices = usePricesStore.getState().prices

    usePricesStore.getState().upsertBatch([
      { ticker: 'AAPL', currentPrice: 101, lastUpdated: 1000 },
    ])

    const afterPrices = usePricesStore.getState().prices
    expect(afterPrices).not.toBe(beforePrices)
    expect(afterPrices.AAPL.currentPrice).toBe(101)
  })

  it('lastUpdated 만 변경되어도 reference 갱신', () => {
    usePricesStore.setState({
      prices: { AAPL: { currentPrice: 100, lastUpdated: 1000 } },
      isLoaded: true,
    })
    const beforePrices = usePricesStore.getState().prices

    usePricesStore.getState().upsertBatch([
      { ticker: 'AAPL', currentPrice: 100, lastUpdated: 2000 },
    ])

    const afterPrices = usePricesStore.getState().prices
    expect(afterPrices).not.toBe(beforePrices)
    expect(afterPrices.AAPL.lastUpdated).toBe(2000)
  })
})

describe('usePricesStore.setSnapshot', () => {
  it('snapshot 통째 교체 + isLoaded=true', () => {
    usePricesStore.getState().setSnapshot({
      AAPL: { currentPrice: 100, lastUpdated: 1000 },
    })
    const s = usePricesStore.getState()
    expect(s.isLoaded).toBe(true)
    expect(s.prices.AAPL).toEqual({ currentPrice: 100, lastUpdated: 1000 })
  })

  it('빈 snapshot 도 isLoaded=true 로 마크', () => {
    usePricesStore.getState().setSnapshot({})
    const s = usePricesStore.getState()
    expect(s.isLoaded).toBe(true)
    expect(s.prices).toEqual({})
  })
})
