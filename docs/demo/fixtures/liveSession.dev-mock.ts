/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * TradingRoomPage 가 표시하는 LIVE 어닝콜 세션 메타데이터 + 가격 시계열.
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 placeholder ("실시간 데이터 동기화 중") 또는 빈 상태로
 *     표시되며 본 fixture 가 화면에 도달하지 않아야 한다.
 *
 * 추후 백엔드 PR:
 *   - LIVE 세션 시작/종료는 STOMP 이벤트 (`EARNINGS_SESSION_STARTED` 등) 로 주입.
 *   - 가격 시계열은 KIS WS 또는 별도 시세 IPC 채널로 대체.
 * ========================================================================== */

export interface LiveSessionMetadata {
  /** 표시 ticker. CompanyDrawer 트리거 키로도 사용. */
  ticker: string
  companyName: string
  /** "Q3 FY25 Earnings Call" 같은 세션명. */
  sessionLabel: string
  /** 세션 시작 epoch 초. */
  startedAtEpoch: number
  /**
   * 경과 시간 라벨 ("MM:SS").
   *
   * 디자인 캔버스가 "25:14 경과" 표시를 요구하지만, 실시간 계산을 위한 helper
   * (startedAtEpoch → "25:14") 는 본 PR 범위 외이므로 fixture 정적값으로 표시한다.
   * 백엔드 IPC 도입 시 헬퍼로 대체 또는 main 측 선계산 후 주입.
   */
  elapsedLabel: string
  /** 화자 분당 단어 수 (UI 메타). */
  wpm: number
  /** "$125.50" 같은 사람-친화 가격 라벨 (현재가). */
  currentPriceLabel: string
  currentPrice: number
  /** 등락률 (%). 양수=상승. */
  changePercent: number
  /** 등락액 ($). */
  changeAmount: number
  /** 거래량 라벨 (e.g. "38.4M"). */
  volumeLabel: string
  /** 시간외 / 장중 같은 세션 상태. */
  marketSession: 'REGULAR' | 'AFTER_HOURS' | 'PRE_MARKET'
  /** AI 점수 현재값 (-1 ~ +1). */
  currentAiScore: number
  /** AI 점수 방향 라벨. */
  aiDirection: 'BUY' | 'SELL' | 'NEUTRAL'
  aiStrength: 'STRONG' | 'MODERATE' | 'WEAK'
}

export interface PricePoint {
  /** "HH:mm" 라벨. */
  time: string
  /** 종가. */
  price: number
}

export interface AiScorePoint {
  time: string
  /** −1 ~ +1. */
  score: number
}

export const liveSessionDevMock: LiveSessionMetadata = {
  ticker: 'NVDA',
  companyName: 'NVIDIA Corp.',
  sessionLabel: 'Q3 FY25 Earnings Call',
  // 디자인 캔버스의 "25:14 경과" 표시를 위해 고정값 (NaN 방지 — toFixed 등은 호출처에서 가드).
  startedAtEpoch: 1719055586,
  elapsedLabel: '25:14',
  wpm: 178,
  currentPriceLabel: '$125.50',
  currentPrice: 125.5,
  changePercent: 4.21,
  changeAmount: 5.07,
  volumeLabel: '38.4M',
  marketSession: 'AFTER_HOURS',
  currentAiScore: 0.78,
  aiDirection: 'BUY',
  aiStrength: 'STRONG',
}

/** 디자인 캔버스의 가격 차트 path 와 동일한 곡선 (30포인트, 1분 간격). */
export const livePriceSeriesDevMock: readonly PricePoint[] = [
  { time: '15:01', price: 120.43 },
  { time: '15:02', price: 120.51 },
  { time: '15:03', price: 120.32 },
  { time: '15:04', price: 120.78 },
  { time: '15:05', price: 120.65 },
  { time: '15:06', price: 121.02 },
  { time: '15:07', price: 121.35 },
  { time: '15:08', price: 121.58 },
  { time: '15:09', price: 121.21 },
  { time: '15:10', price: 121.89 },
  { time: '15:11', price: 122.45 },
  { time: '15:12', price: 122.10 },
  { time: '15:13', price: 122.78 },
  { time: '15:14', price: 123.15 },
  { time: '15:15', price: 122.92 },
  { time: '15:16', price: 123.61 },
  { time: '15:17', price: 124.05 },
  { time: '15:18', price: 124.48 },
  { time: '15:19', price: 124.21 },
  { time: '15:20', price: 124.87 },
  { time: '15:21', price: 124.63 },
  { time: '15:22', price: 125.02 },
  { time: '15:23', price: 124.81 },
  { time: '15:24', price: 125.18 },
  { time: '15:25', price: 124.95 },
  { time: '15:26', price: 125.27 },
  { time: '15:27', price: 125.06 },
  { time: '15:28', price: 125.41 },
  { time: '15:29', price: 125.32 },
  { time: '15:30', price: 125.50 },
] as const

/** AI 점수 시계열 (디자인 캔버스의 보라색 라인). */
export const liveAiScoreSeriesDevMock: readonly AiScorePoint[] = [
  { time: '15:01', score: -0.05 },
  { time: '15:02', score: -0.08 },
  { time: '15:03', score: 0.03 },
  { time: '15:04', score: -0.12 },
  { time: '15:05', score: 0.08 },
  { time: '15:06', score: 0.18 },
  { time: '15:07', score: 0.12 },
  { time: '15:08', score: 0.27 },
  { time: '15:09', score: 0.21 },
  { time: '15:10', score: 0.34 },
  { time: '15:11', score: 0.42 },
  { time: '15:12', score: 0.31 },
  { time: '15:13', score: 0.48 },
  { time: '15:14', score: 0.55 },
  { time: '15:15', score: 0.46 },
  { time: '15:16', score: 0.62 },
  { time: '15:17', score: 0.51 },
  { time: '15:18', score: 0.65 },
  { time: '15:19', score: 0.58 },
  { time: '15:20', score: 0.69 },
  { time: '15:21', score: 0.63 },
  { time: '15:22', score: 0.71 },
  { time: '15:23', score: 0.66 },
  { time: '15:24', score: 0.74 },
  { time: '15:25', score: 0.69 },
  { time: '15:26', score: 0.76 },
  { time: '15:27', score: 0.72 },
  { time: '15:28', score: 0.79 },
  { time: '15:29', score: 0.75 },
  { time: '15:30', score: 0.78 },
] as const
