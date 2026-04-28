import { describe, it, expect, beforeEach } from 'vitest'
import {
  useMarketIndicesStore,
  type MarketIndexItem,
} from '../useMarketIndicesStore'

function makeItem(symbol: string, ts: number, override: Partial<MarketIndexItem> = {}): MarketIndexItem {
  return {
    symbol,
    price: 100,
    changePercent: 0,
    trend: 'neutral',
    format: 'index',
    timestamp: ts,
    ...override,
  }
}

beforeEach(() => {
  // 각 테스트마다 store 초기화 (zustand persist 미사용이므로 reset() 으로 충분).
  useMarketIndicesStore.getState().reset()
})

describe('useMarketIndicesStore', () => {
  describe('setIndices', () => {
    it('빈 배열은 isLoaded=false 와 lastUpdatedAt=null 을 유지한다 (Contract 7.7 placeholder)', () => {
      useMarketIndicesStore.getState().setIndices([])
      const s = useMarketIndicesStore.getState()
      expect(s.indices).toEqual([])
      expect(s.isLoaded).toBe(false)
      expect(s.lastUpdatedAt).toBeNull()
    })

    it('5종 스냅샷을 symbol 알파벳 정렬로 저장하고 isLoaded=true 로 전환한다', () => {
      const items = [
        makeItem('SPX', 1000),
        makeItem('NDX', 1001),
        makeItem('VIX', 1002),
        makeItem('DXY', 1003),
        makeItem('10Y', 1004),
      ]
      useMarketIndicesStore.getState().setIndices(items)
      const s = useMarketIndicesStore.getState()
      expect(s.indices.map((i) => i.symbol)).toEqual(['10Y', 'DXY', 'NDX', 'SPX', 'VIX'])
      expect(s.isLoaded).toBe(true)
      // 가장 큰 timestamp 가 lastUpdatedAt 으로 설정.
      expect(s.lastUpdatedAt).toBe(1004)
    })

    it('부분 스냅샷 3종도 isLoaded=true + 정렬 + lastUpdatedAt 정상', () => {
      useMarketIndicesStore.getState().setIndices([
        makeItem('SPX', 200),
        makeItem('VIX', 300),
        makeItem('10Y', 100),
      ])
      const s = useMarketIndicesStore.getState()
      expect(s.indices.map((i) => i.symbol)).toEqual(['10Y', 'SPX', 'VIX'])
      expect(s.isLoaded).toBe(true)
      expect(s.lastUpdatedAt).toBe(300)
    })

    it('모든 timestamp=0 → lastUpdatedAt=null 유지 (양수만 반영)', () => {
      useMarketIndicesStore.getState().setIndices([
        makeItem('SPX', 0),
        makeItem('NDX', 0),
      ])
      const s = useMarketIndicesStore.getState()
      expect(s.isLoaded).toBe(true)
      expect(s.lastUpdatedAt).toBeNull()
    })

    it('모두 동일한 양수 timestamp → 그 값으로 고정', () => {
      useMarketIndicesStore.getState().setIndices([
        makeItem('SPX', 100),
        makeItem('NDX', 100),
        makeItem('DXY', 100),
      ])
      const s = useMarketIndicesStore.getState()
      expect(s.lastUpdatedAt).toBe(100)
    })

    it('lastUpdatedAt 은 단조 증가 — 더 작은 timestamp 스냅샷이 와도 역행 X', () => {
      const store = useMarketIndicesStore.getState()
      store.setIndices([makeItem('SPX', 500)])
      expect(useMarketIndicesStore.getState().lastUpdatedAt).toBe(500)
      // 더 과거 시점 스냅샷 — lastUpdatedAt 은 500 유지.
      store.setIndices([makeItem('SPX', 200)])
      expect(useMarketIndicesStore.getState().lastUpdatedAt).toBe(500)
    })
  })

  describe('upsertIndex', () => {
    it('신규 symbol 은 정렬을 유지하며 append 되고 isLoaded=true 로 전환한다', () => {
      const store = useMarketIndicesStore.getState()
      store.upsertIndex(makeItem('SPX', 100))
      store.upsertIndex(makeItem('NDX', 200))
      store.upsertIndex(makeItem('DXY', 150))
      const s = useMarketIndicesStore.getState()
      expect(s.indices.map((i) => i.symbol)).toEqual(['DXY', 'NDX', 'SPX'])
      expect(s.isLoaded).toBe(true)
    })

    it('기존 symbol 은 같은 위치에서 덮어쓰며 lastUpdatedAt 을 갱신한다', () => {
      const store = useMarketIndicesStore.getState()
      store.setIndices([
        makeItem('SPX', 100, { price: 5000 }),
        makeItem('NDX', 100, { price: 18000 }),
      ])
      store.upsertIndex(makeItem('SPX', 200, { price: 5432.1, changePercent: 0.42, trend: 'up' }))
      const s = useMarketIndicesStore.getState()
      const spx = s.indices.find((i) => i.symbol === 'SPX')!
      expect(spx.price).toBe(5432.1)
      expect(spx.changePercent).toBe(0.42)
      expect(spx.trend).toBe('up')
      // 정렬 유지: NDX < SPX (알파벳)
      expect(s.indices.map((i) => i.symbol)).toEqual(['NDX', 'SPX'])
      expect(s.lastUpdatedAt).toBe(200)
    })

    it('빈 store 에서 upsert 한 번에 isLoaded=true 와 lastUpdatedAt 이 설정된다', () => {
      expect(useMarketIndicesStore.getState().isLoaded).toBe(false)
      useMarketIndicesStore.getState().upsertIndex(makeItem('VIX', 999))
      const s = useMarketIndicesStore.getState()
      expect(s.isLoaded).toBe(true)
      expect(s.lastUpdatedAt).toBe(999)
      expect(s.indices).toHaveLength(1)
      expect(s.indices[0].symbol).toBe('VIX')
    })

    it('out-of-order push 는 stale-drop — 기존 timestamp 보다 과거면 state 변화 없음', () => {
      const store = useMarketIndicesStore.getState()
      store.setIndices([makeItem('SPX', 200, { price: 5000 })])
      const before = useMarketIndicesStore.getState()

      // 더 과거 timestamp 의 push — 무시되어야 함.
      store.upsertIndex(makeItem('SPX', 100, { price: 4000 }))

      const after = useMarketIndicesStore.getState()
      // 동일 reference 보존 (참조 동일성으로 reducer 가 state 그대로 반환했음을 검증).
      expect(after.indices).toBe(before.indices)
      expect(after.indices[0].price).toBe(5000)
      expect(after.lastUpdatedAt).toBe(200)
    })

    it('정방향 push (timestamp 100 → 200) 는 정상 갱신', () => {
      const store = useMarketIndicesStore.getState()
      store.upsertIndex(makeItem('SPX', 100, { price: 4000 }))
      store.upsertIndex(makeItem('SPX', 200, { price: 5000 }))
      const s = useMarketIndicesStore.getState()
      expect(s.indices[0].price).toBe(5000)
      expect(s.lastUpdatedAt).toBe(200)
    })

    it('upsertIndex 에 timestamp=0 호출 시 lastUpdatedAt 변경 없음 (기존 값 유지)', () => {
      const store = useMarketIndicesStore.getState()
      store.setIndices([makeItem('SPX', 500)])
      expect(useMarketIndicesStore.getState().lastUpdatedAt).toBe(500)

      store.upsertIndex(makeItem('NDX', 0, { price: 18000 }))
      const s = useMarketIndicesStore.getState()
      // NDX 는 추가되었지만 lastUpdatedAt 은 500 유지.
      expect(s.indices.map((i) => i.symbol)).toEqual(['NDX', 'SPX'])
      expect(s.lastUpdatedAt).toBe(500)
    })
  })

  describe('reset', () => {
    it('모든 상태를 초기화한다', () => {
      const store = useMarketIndicesStore.getState()
      store.setIndices([makeItem('SPX', 100), makeItem('NDX', 200)])
      expect(useMarketIndicesStore.getState().isLoaded).toBe(true)
      store.reset()
      const s = useMarketIndicesStore.getState()
      expect(s.indices).toEqual([])
      expect(s.isLoaded).toBe(false)
      expect(s.lastUpdatedAt).toBeNull()
    })
  })
})
