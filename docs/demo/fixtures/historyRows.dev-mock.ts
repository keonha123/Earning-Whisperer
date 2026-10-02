/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * HistoryPage 테이블이 mode/AI 컬럼 등 디자인 매칭을 위해 사용하는 더미 행.
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 store 의 실제 Trade 만 표시하고 mode/AI 컬럼은
 *     숨기거나 빈 셀("—") 로 표시 (TRADES_GET 응답에 해당 필드 없음).
 *
 * 타입 정책:
 *   - 기존 `Trade` 인터페이스를 변경하지 않기 위해 별도 `HistoryRowMock`
 *     타입으로 분리. mode/ai_score 는 fixture 전용 필드.
 *   - Trade 호환 필드(id, ticker, side, executedQty, executedPrice, status, createdAt)는
 *     동일 형태로 유지하여 prod 와의 마이그레이션을 단순화.
 *
 * 추후:
 *   - TRADES_GET 응답에 mode / ai_score 추가 시 별도 PR 에서 본 fixture 제거.
 *   - 보안: 더미 거래도 가짜로 보이게 하기 위해 가격은 실제 시장가에서 살짝
 *     벗어난 값을 사용 (오인 방지).
 * ========================================================================== */

export type HistoryMode = 'AUTO' | 'SEMI' | 'MANUAL'
export type HistoryStatus = 'EXECUTED' | 'FAILED' | 'PENDING'

export interface HistoryRowMock {
  id: number
  ticker: string
  side: 'BUY' | 'SELL'
  mode: HistoryMode
  executedQty: number
  executedPrice: number | null
  /** mode / 가격에서 자동 계산하지 않고 미리 산출된 표시값. */
  amount: number | null
  /** 0~1 범위 EMA 점수 (없을 수도 있음 — MANUAL 모드 등). */
  ai_score: number | null
  status: HistoryStatus
  /** ISO 8601. */
  createdAt: string
  /** 실패 사유 (status === FAILED 일 때만). */
  failureReason?: string
}

export const historyRowsDevMock: readonly HistoryRowMock[] = [
  {
    id: 1001,
    ticker: 'NVDA',
    side: 'BUY',
    mode: 'AUTO',
    executedQty: 10,
    executedPrice: 125.5,
    amount: 1255.0,
    ai_score: 0.84,
    status: 'EXECUTED',
    createdAt: '2026-04-20T09:42:15+09:00',
  },
  {
    id: 1002,
    ticker: 'NVDA',
    side: 'BUY',
    mode: 'AUTO',
    executedQty: 5,
    executedPrice: 125.1,
    amount: 625.5,
    ai_score: 0.78,
    status: 'EXECUTED',
    createdAt: '2026-04-20T09:41:58+09:00',
  },
  {
    id: 1003,
    ticker: 'TSLA',
    side: 'SELL',
    mode: 'SEMI',
    executedQty: 5,
    executedPrice: 245.2,
    amount: 1226.0,
    ai_score: 0.71,
    status: 'EXECUTED',
    createdAt: '2026-04-19T16:02:33+09:00',
  },
  {
    id: 1004,
    ticker: 'MSFT',
    side: 'BUY',
    mode: 'AUTO',
    executedQty: 3,
    executedPrice: 418.75,
    amount: 1256.25,
    ai_score: 0.82,
    status: 'EXECUTED',
    createdAt: '2026-04-19T09:31:22+09:00',
  },
  {
    id: 1005,
    ticker: 'AAPL',
    side: 'SELL',
    mode: 'SEMI',
    executedQty: 8,
    executedPrice: 189.4,
    amount: 1515.2,
    ai_score: 0.66,
    status: 'EXECUTED',
    createdAt: '2026-04-18T15:58:07+09:00',
  },
  {
    id: 1006,
    ticker: 'AAPL',
    side: 'BUY',
    mode: 'MANUAL',
    executedQty: 8,
    executedPrice: 186.1,
    amount: 1488.8,
    ai_score: null,
    status: 'EXECUTED',
    createdAt: '2026-04-18T09:34:11+09:00',
  },
  {
    id: 1007,
    ticker: 'META',
    side: 'SELL',
    mode: 'AUTO',
    executedQty: 2,
    executedPrice: 512.3,
    amount: 1024.6,
    ai_score: 0.69,
    status: 'EXECUTED',
    createdAt: '2026-04-17T16:05:44+09:00',
  },
  {
    id: 1008,
    ticker: 'META',
    side: 'BUY',
    mode: 'AUTO',
    executedQty: 2,
    executedPrice: 508.9,
    amount: 1017.8,
    ai_score: 0.76,
    status: 'EXECUTED',
    createdAt: '2026-04-17T09:30:02+09:00',
  },
  {
    id: 1009,
    ticker: 'AMZN',
    side: 'BUY',
    mode: 'SEMI',
    executedQty: 4,
    executedPrice: 178.25,
    amount: 713.0,
    ai_score: 0.62,
    status: 'FAILED',
    createdAt: '2026-04-16T10:15:33+09:00',
    failureReason: '쿨다운 위반',
  },
  {
    id: 1010,
    ticker: 'GOOGL',
    side: 'BUY',
    mode: 'AUTO',
    executedQty: 6,
    executedPrice: 165.8,
    amount: 994.8,
    ai_score: 0.74,
    status: 'EXECUTED',
    createdAt: '2026-04-16T09:30:15+09:00',
  },
  {
    id: 1011,
    ticker: 'NFLX',
    side: 'SELL',
    mode: 'SEMI',
    executedQty: 1,
    executedPrice: 622.15,
    amount: 622.15,
    ai_score: 0.58,
    status: 'EXECUTED',
    createdAt: '2026-04-15T15:45:21+09:00',
  },
  {
    id: 1012,
    ticker: 'NFLX',
    side: 'BUY',
    mode: 'AUTO',
    executedQty: 1,
    executedPrice: 615.4,
    amount: 615.4,
    ai_score: 0.81,
    status: 'EXECUTED',
    createdAt: '2026-04-15T09:30:05+09:00',
  },
] as const

/** 디자인의 요약 칩 (오늘 N건 / BUY / SELL) 더미 합계. */
export const historySummaryDevMock = {
  todayCount: 24,
  buyCount: 14,
  sellCount: 10,
  totalCount: 124,
} as const
