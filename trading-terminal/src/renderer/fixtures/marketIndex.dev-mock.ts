/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * MarketStrip 컴포넌트가 표시하는 글로벌 지수 더미값 (S&P 500 등).
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 컴포넌트 자체가 placeholder/숨김 처리하므로
 *     이 fixture 가 화면에 도달하지 않아야 한다.
 *
 * PR-B 시점 변경:
 *   - 타입은 useMarketIndicesStore 의 `MarketIndexItem` 으로 통합 (source of truth).
 *   - 본 fixture 는 backend 미연동 (isLoaded === false) DEV 환경 fallback 으로만 사용.
 *   - 실제 데이터(REST + STOMP) 도착 시 store 가 채워지며 자동으로 교체된다.
 * ========================================================================== */

import type { MarketIndexItem } from '../store/useMarketIndicesStore'

export type MarketTrend = 'up' | 'down' | 'neutral'
export type { MarketIndexItem }

export const marketIndexDevMock: readonly MarketIndexItem[] = [
  { symbol: 'SPX', price: 5432.1, changePercent: 0.42, trend: 'up', format: 'index', timestamp: 0 },
  { symbol: 'NDX', price: 18211.5, changePercent: 0.81, trend: 'up', format: 'index', timestamp: 0 },
  { symbol: 'VIX', price: 14.2, changePercent: -2.1, trend: 'down', format: 'index', timestamp: 0 },
  { symbol: 'DXY', price: 104.5, changePercent: 0.1, trend: 'neutral', format: 'index', timestamp: 0 },
  { symbol: '10Y', price: 4.32, changePercent: 0.02, trend: 'up', format: 'percent', timestamp: 0 },
] as const
