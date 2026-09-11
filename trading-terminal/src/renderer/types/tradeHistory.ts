/**
 * 체결 내역 표시 모델.
 *
 * 백엔드의 `Trade` 는 mode / ai_score 를 주지 않는다. 화면은 그 두 컬럼을 가진
 * 디자인이라 별도 표시 타입을 둔다. 값이 없는 컬럼은 "—" 로 그린다 — 없는 값을
 * 그럴듯하게 채우지 않는다.
 *
 * 원래 `fixtures/historyRows.dev-mock.ts` 안에 가짜 체결 내역과 함께 있었다.
 * 그 목업은 거래가 없을 때 화면에 대신 떠서, 체결이 없는 것과 연동이 끊긴 것을
 * 구별할 수 없게 만들고 있었다. 타입만 분리하고 목업은 쓰지 않는다.
 */

export type HistoryMode = 'AUTO' | 'SEMI' | 'MANUAL'
export type HistoryStatus = 'EXECUTED' | 'FAILED' | 'PENDING'

export interface HistoryRow {
  id: number
  ticker: string
  side: 'BUY' | 'SELL'
  mode: HistoryMode
  /** 주문 유형. 백엔드가 주지 않던 값이라 nullable. */
  orderType: 'MARKET' | 'LIMIT' | null
  /** 사용자가 낸 주문 수량. 미체결 주문에도 존재한다. */
  orderQty: number | null
  /** 주문 지정가. 체결가와 달리 미체결 주문에도 존재한다. */
  price: number | null
  executedQty: number
  executedPrice: number | null
  amount: number | null
  /** 0~1 범위 EMA 점수. 백엔드가 아직 주지 않으므로 현재는 항상 null. */
  ai_score: number | null
  status: HistoryStatus
  /** ISO 8601. */
  createdAt: string
  /** 실패 사유 (status === FAILED 일 때만). */
  failureReason?: string
}
