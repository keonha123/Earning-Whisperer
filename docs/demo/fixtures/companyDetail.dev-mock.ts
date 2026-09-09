/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * CompanyDrawer 가 표시하는 ticker 별 상세 정보:
 *   - 기본 정보 (섹터, 시총, 52주 고저, 배당)
 *   - 30일 가격 시계열 (SVG 미니 차트용)
 *   - 어닝 히스토리 (최근 4분기)
 *   - AI 분석 요약 텍스트
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 fixture 가 없는 ticker 는 "데이터를 불러올 수 없습니다"
 *     placeholder 로 표시 (현재 백엔드에 IPC 미존재).
 *
 * 보안:
 *   - ticker 파라미터는 정규식 [A-Z0-9.-]{1,10} 로 화이트리스트 검증
 *     (CompanyDrawer 컴포넌트에서 처리).
 *   - AI 요약 텍스트는 plain string 으로만 렌더 (dangerouslySetInnerHTML 금지).
 *
 * 추후:
 *   - 백엔드 PR 에서 IPC (`COMPANY_GET_DETAIL`, `KIS_GET_DAILY_CHART`) 추가.
 *   - 어닝 히스토리는 별도 finance 데이터 소스 연동.
 * ========================================================================== */

export interface CompanyBasicInfo {
  /** "Technology · Semiconductors" 같은 결합 라벨. */
  sector: string
  /** "$3.12T" 같은 사람-친화 포맷. 숫자 계산 안 함. */
  marketCap: string
  high52w: string
  low52w: string
  dividendYield: string
}

export interface EarningsHistoryRow {
  /** 분기 라벨 (예: "Q2 FY25"). */
  quarter: string
  epsEstimate: string
  epsActual: string
  /** 부호 포함 문자열 (예: "+17.2%", "−1.7%"). 색은 호출자가 부호로 결정. */
  surprisePercent: string
  priceReactionPercent: string
}

export interface ChartPoint {
  /** "MM-DD" 라벨. SVG 그리기용. */
  date: string
  /** 종가. */
  price: number
}

export interface CompanyDetailFixture {
  ticker: string
  name: string
  /** 회사 로고 색 (CompanyLogo 컴포넌트에 prop 전달용). */
  logoBg: string
  logoFg: string
  logoLabel?: string
  isLive?: boolean

  basic: CompanyBasicInfo

  /** 30일치 종가 시계열 (SVG 폴리라인용). */
  chart30d: ChartPoint[]
  chartCurrent: {
    /** "$125.50" — 표시용 포맷. */
    priceLabel: string
    /** "+1.32% · +$1.63" — 일간 등락. */
    dayChangeLabel: string
    /** "+2.34%" — 30일 누적. */
    periodChangeLabel: string
    /** 전체 차트가 상승/하락 — 라인/영역 색 결정용. */
    direction: 'up' | 'down' | 'neutral'
  }

  earningsHistory: EarningsHistoryRow[]

  ai: {
    /** plain text. 줄바꿈은 컴포넌트가 처리. */
    summary: string
    /** "+0.71" 같은 평균 점수 라벨. */
    avgScoreLabel: string
    /** "BUY 우세" / "SELL 우세" / "중립". */
    bias: 'BUY' | 'SELL' | 'NEUTRAL'
  }
}

const NVDA_CHART: ChartPoint[] = [
  { date: '03-21', price: 110 }, { date: '03-22', price: 111 }, { date: '03-23', price: 109 },
  { date: '03-24', price: 112 }, { date: '03-25', price: 110 }, { date: '03-26', price: 113 },
  { date: '03-27', price: 115 }, { date: '03-28', price: 116 }, { date: '03-29', price: 114 },
  { date: '03-30', price: 117 }, { date: '03-31', price: 118 }, { date: '04-01', price: 117 },
  { date: '04-02', price: 119 }, { date: '04-03', price: 120 }, { date: '04-04', price: 118 },
  { date: '04-05', price: 121 }, { date: '04-06', price: 122 }, { date: '04-07', price: 121 },
  { date: '04-08', price: 122 }, { date: '04-09', price: 123 }, { date: '04-10', price: 122 },
  { date: '04-11', price: 124 }, { date: '04-12', price: 123 }, { date: '04-13', price: 124 },
  { date: '04-14', price: 125 }, { date: '04-15', price: 124 }, { date: '04-16', price: 125 },
  { date: '04-17', price: 124 }, { date: '04-18', price: 125 }, { date: '04-19', price: 124 },
  { date: '04-20', price: 125.5 },
]

export const companyDetailDevMock: Readonly<Record<string, CompanyDetailFixture>> = {
  NVDA: {
    ticker: 'NVDA',
    name: 'NVIDIA Corp.',
    logoBg: '#103a2b',
    logoFg: '#6ee7b7',
    logoLabel: 'NV',
    isLive: true,
    basic: {
      sector: 'Technology · Semiconductors',
      marketCap: '$3.12T',
      high52w: '$138.07',
      low52w: '$75.60',
      dividendYield: '0.03%',
    },
    chart30d: NVDA_CHART,
    chartCurrent: {
      priceLabel: '$125.50',
      dayChangeLabel: '+1.32% · +$1.63',
      periodChangeLabel: '+2.34%',
      direction: 'up',
    },
    earningsHistory: [
      { quarter: 'Q2 FY25', epsEstimate: '$0.58', epsActual: '$0.68', surprisePercent: '+17.2%', priceReactionPercent: '+9.3%' },
      { quarter: 'Q1 FY25', epsEstimate: '$0.54', epsActual: '$0.61', surprisePercent: '+13.0%', priceReactionPercent: '+2.4%' },
      { quarter: 'Q4 FY24', epsEstimate: '$0.51', epsActual: '$0.52', surprisePercent: '+2.0%',  priceReactionPercent: '−1.7%' },
      { quarter: 'Q3 FY24', epsEstimate: '$0.47', epsActual: '$0.50', surprisePercent: '+6.4%',  priceReactionPercent: '+0.5%' },
    ],
    ai: {
      summary:
        '데이터센터 매출 YoY +112%, 가이던스 상향. Blackwell 출하 가속화 + Hopper 수요 지속으로 긍정 시그널 우세. 마진 압박 우려는 제한적.',
      avgScoreLabel: '+0.71',
      bias: 'BUY',
    },
  },
  AAPL: {
    ticker: 'AAPL',
    name: 'Apple Inc.',
    logoBg: '#1f2937',
    logoFg: '#e5e7eb',
    logoLabel: 'AA',
    basic: {
      sector: 'Technology · Consumer Electronics',
      marketCap: '$2.98T',
      high52w: '$199.62',
      low52w: '$164.08',
      dividendYield: '0.49%',
    },
    chart30d: NVDA_CHART.map((p, i) => ({ date: p.date, price: 188 + Math.sin(i / 3) * 4 + i * 0.2 })),
    chartCurrent: {
      priceLabel: '$195.20',
      dayChangeLabel: '−0.52% · −$1.02',
      periodChangeLabel: '+1.85%',
      direction: 'up',
    },
    earningsHistory: [
      { quarter: 'Q2 FY25', epsEstimate: '$1.50', epsActual: '$1.53', surprisePercent: '+2.0%',  priceReactionPercent: '+1.1%' },
      { quarter: 'Q1 FY25', epsEstimate: '$2.10', epsActual: '$2.18', surprisePercent: '+3.8%',  priceReactionPercent: '+0.4%' },
      { quarter: 'Q4 FY24', epsEstimate: '$1.39', epsActual: '$1.40', surprisePercent: '+0.7%',  priceReactionPercent: '−0.6%' },
      { quarter: 'Q3 FY24', epsEstimate: '$1.34', epsActual: '$1.46', surprisePercent: '+9.0%',  priceReactionPercent: '+1.8%' },
    ],
    ai: {
      summary:
        '서비스 매출 견조하나 iPhone 출하 정체. 인도/베트남 다변화는 진행 중. 가이던스 보수적, 단기 모멘텀 약함.',
      avgScoreLabel: '+0.42',
      bias: 'NEUTRAL',
    },
  },
  TSLA: {
    ticker: 'TSLA',
    name: 'Tesla Inc.',
    logoBg: '#3b1d1d',
    logoFg: '#fca5a5',
    logoLabel: 'TS',
    basic: {
      sector: 'Consumer Cyclical · Auto Manufacturers',
      marketCap: '$782B',
      high52w: '$299.29',
      low52w: '$138.80',
      dividendYield: '—',
    },
    chart30d: NVDA_CHART.map((p, i) => ({ date: p.date, price: 235 + Math.sin(i / 4) * 8 + i * 0.4 })),
    chartCurrent: {
      priceLabel: '$245.80',
      dayChangeLabel: '+3.21% · +$7.65',
      periodChangeLabel: '+4.02%',
      direction: 'up',
    },
    earningsHistory: [
      { quarter: 'Q1 25', epsEstimate: '$0.51', epsActual: '$0.45', surprisePercent: '−11.8%', priceReactionPercent: '−3.4%' },
      { quarter: 'Q4 24', epsEstimate: '$0.74', epsActual: '$0.71', surprisePercent: '−4.1%',  priceReactionPercent: '−2.1%' },
      { quarter: 'Q3 24', epsEstimate: '$0.60', epsActual: '$0.72', surprisePercent: '+20.0%', priceReactionPercent: '+5.8%' },
      { quarter: 'Q2 24', epsEstimate: '$0.62', epsActual: '$0.52', surprisePercent: '−16.1%', priceReactionPercent: '−6.4%' },
    ],
    ai: {
      summary:
        '딜리버리 가이던스 하향. FSD 매출은 점진 증가하나 자동차 마진 압박. 에너지 부문은 강세.',
      avgScoreLabel: '−0.18',
      bias: 'SELL',
    },
  },
  MSFT: {
    ticker: 'MSFT',
    name: 'Microsoft Corp.',
    logoBg: '#1e293b',
    logoFg: '#93c5fd',
    logoLabel: 'MS',
    basic: {
      sector: 'Technology · Software—Infrastructure',
      marketCap: '$3.12T',
      high52w: '$430.82',
      low52w: '$309.45',
      dividendYield: '0.72%',
    },
    chart30d: NVDA_CHART.map((p, i) => ({ date: p.date, price: 405 + Math.cos(i / 3) * 6 + i * 0.5 })),
    chartCurrent: {
      priceLabel: '$420.10',
      dayChangeLabel: '+0.82% · +$3.42',
      periodChangeLabel: '+3.71%',
      direction: 'up',
    },
    earningsHistory: [
      { quarter: 'Q3 FY24', epsEstimate: '$2.82', epsActual: '$2.94', surprisePercent: '+4.3%', priceReactionPercent: '+1.8%' },
      { quarter: 'Q2 FY24', epsEstimate: '$2.78', epsActual: '$2.93', surprisePercent: '+5.4%', priceReactionPercent: '+0.7%' },
      { quarter: 'Q1 FY24', epsEstimate: '$2.65', epsActual: '$2.99', surprisePercent: '+12.8%', priceReactionPercent: '+2.4%' },
      { quarter: 'Q4 FY23', epsEstimate: '$2.55', epsActual: '$2.69', surprisePercent: '+5.5%', priceReactionPercent: '−0.3%' },
    ],
    ai: {
      summary:
        'Azure 성장 가속, AI 워크로드 견인. Copilot 채택률 상승 중. 클라우드 인프라 capex 부담은 단기 마진 누름.',
      avgScoreLabel: '+0.58',
      bias: 'BUY',
    },
  },
  AMZN: {
    ticker: 'AMZN',
    name: 'Amazon.com Inc.',
    logoBg: '#332617',
    logoFg: '#fcd34d',
    logoLabel: 'AM',
    basic: {
      sector: 'Consumer Cyclical · Internet Retail',
      marketCap: '$1.85T',
      high52w: '$201.20',
      low52w: '$118.35',
      dividendYield: '—',
    },
    chart30d: NVDA_CHART.map((p, i) => ({ date: p.date, price: 170 + Math.sin(i / 5) * 5 + i * 0.3 })),
    chartCurrent: {
      priceLabel: '$178.25',
      dayChangeLabel: '+0.41% · +$0.73',
      periodChangeLabel: '+2.10%',
      direction: 'up',
    },
    earningsHistory: [
      { quarter: 'Q4 24', epsEstimate: '$0.78', epsActual: '$1.00', surprisePercent: '+28.2%', priceReactionPercent: '+8.0%' },
      { quarter: 'Q3 24', epsEstimate: '$0.58', epsActual: '$0.94', surprisePercent: '+62.1%', priceReactionPercent: '+6.2%' },
      { quarter: 'Q2 24', epsEstimate: '$0.34', epsActual: '$0.65', surprisePercent: '+91.2%', priceReactionPercent: '+8.3%' },
      { quarter: 'Q1 24', epsEstimate: '$0.21', epsActual: '$0.31', surprisePercent: '+47.6%', priceReactionPercent: '+1.4%' },
    ],
    ai: {
      summary:
        'AWS 성장 회복, 광고 부문 두 자리 수 성장. 물류 효율 개선 + Prime 구독 확대. 단기 가이던스 양호.',
      avgScoreLabel: '+0.64',
      bias: 'BUY',
    },
  },
} as const
