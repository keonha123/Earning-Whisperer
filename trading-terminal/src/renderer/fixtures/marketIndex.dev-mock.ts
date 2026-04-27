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
 * 추후 백엔드 PR:
 *   - 실시간 지수 fetch IPC 채널 (`KIS_GET_MARKET_INDICES` 등) 추가 예정.
 *     이때 본 fixture 는 제거.
 * ========================================================================== */

export type MarketTrend = 'up' | 'down' | 'neutral'

export interface MarketIndexItem {
  /** 표시 심볼 (예: "SPX", "NDX"). a11y label 에도 사용. */
  symbol: string
  /** 미포맷 가격값 (소수점 포함). */
  price: number
  /** 등락률(%) — 양수=상승, 음수=하락. */
  changePercent: number
  /** pip 색 결정용. changePercent 와 일치시키되 neutral 은 미세 변동 표시. */
  trend: MarketTrend
  /** 가격 표시 포맷터 (지수마다 자릿수 다름). */
  format?: 'index' | 'percent'
}

export const marketIndexDevMock: readonly MarketIndexItem[] = [
  { symbol: 'SPX', price: 5432.1, changePercent: 0.42, trend: 'up', format: 'index' },
  { symbol: 'NDX', price: 18211.5, changePercent: 0.81, trend: 'up', format: 'index' },
  { symbol: 'VIX', price: 14.2, changePercent: -2.1, trend: 'down', format: 'index' },
  { symbol: 'DXY', price: 104.5, changePercent: 0.1, trend: 'neutral', format: 'index' },
  { symbol: '10Y', price: 4.32, changePercent: 0.02, trend: 'up', format: 'percent' },
] as const
