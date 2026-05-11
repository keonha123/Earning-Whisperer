/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * HoldingsTable 컴포넌트의 보유/관심 종목 메타데이터 (회사 로고 색 포함).
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 실제 usePortfolioStore.holdings 만 사용 (로고 색 fallback).
 *
 * 회사별 색은 디자인 캔버스 `.lg-nvda` / `.lg-aapl` 등에서 가져온 인라인 헥스.
 * 새 토큰을 만들지 않고 데이터로 보존 (Tailwind 토큰은 의미론적 색만 정의).
 *
 * 추후:
 *   - 백엔드에 종목별 메타데이터(로고/색) 컬럼 도입 시 본 fixture 제거.
 *   - watchlist 는 별도 IPC (`WATCHLIST_LIST` 등) 도입 후 store 로 이전.
 * ========================================================================== */

export interface HoldingMockRow {
  ticker: string
  name: string
  /** 표시용 현재가. */
  currentPrice: number
  /** 일간 등락률 (%). */
  dailyChangePercent: number
  /** 평가 손익률 (%). */
  pnlPercent: number
  /** 어닝 배지: "LIVE" / epoch seconds / null */
  earningsBadge: 'LIVE' | number | null
  /** 회사 로고 색 — 디자인 캔버스 `.lg-*` 에서 가져옴. */
  logoBg: string
  logoFg: string
  /** 표시용 이니셜 (선택). 미지정 시 ticker[0..2]. */
  logoLabel?: string
}

export interface WatchlistMockRow extends Omit<HoldingMockRow, 'pnlPercent'> {
  /** 관심종목은 평가 손익이 없음 (보유하지 않음). */
}

export const holdingsDevMock: readonly HoldingMockRow[] = [
  {
    ticker: 'NVDA',
    name: 'NVIDIA Corp.',
    currentPrice: 125.5,
    dailyChangePercent: 1.32,
    pnlPercent: 4.21,
    earningsBadge: 'LIVE' as const,
    logoBg: '#103a2b',
    logoFg: '#6ee7b7',
    logoLabel: 'NV',
  },
  {
    ticker: 'AAPL',
    name: 'Apple Inc.',
    currentPrice: 195.2,
    dailyChangePercent: -0.52,
    pnlPercent: 2.14,
    earningsBadge: null,
    logoBg: '#1f2937',
    logoFg: '#e5e7eb',
    logoLabel: 'AA',
  },
  {
    ticker: 'TSLA',
    name: 'Tesla Inc.',
    currentPrice: 245.8,
    dailyChangePercent: 3.21,
    pnlPercent: -1.48,
    earningsBadge: Math.floor(Date.now() / 1000) + 86400,
    logoBg: '#3b1d1d',
    logoFg: '#fca5a5',
    logoLabel: 'TS',
  },
  {
    ticker: 'MSFT',
    name: 'Microsoft Corp.',
    currentPrice: 420.1,
    dailyChangePercent: 0.82,
    pnlPercent: 8.32,
    earningsBadge: Math.floor(Date.now() / 1000) + 86400 * 5,
    logoBg: '#1e293b',
    logoFg: '#93c5fd',
    logoLabel: 'MS',
  },
] as const

export const watchlistDevMock: readonly WatchlistMockRow[] = [
  {
    ticker: 'AMZN',
    name: 'Amazon.com Inc.',
    currentPrice: 178.25,
    dailyChangePercent: 0.41,
    earningsBadge: Math.floor(Date.now() / 1000) + 86400 * 30,
    logoBg: '#332617',
    logoFg: '#fcd34d',
    logoLabel: 'AM',
  },
  {
    ticker: 'META',
    name: 'Meta Platforms',
    currentPrice: 512.3,
    dailyChangePercent: -1.04,
    earningsBadge: null,
    logoBg: '#1e2b4a',
    logoFg: '#93c5fd',
    logoLabel: 'ME',
  },
  {
    ticker: 'GOOGL',
    name: 'Alphabet Inc.',
    currentPrice: 165.8,
    dailyChangePercent: 0.18,
    earningsBadge: null,
    logoBg: '#2a2320',
    logoFg: '#fdba74',
    logoLabel: 'GO',
  },
] as const
