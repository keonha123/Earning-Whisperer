/**
 * 이 화면에서 낸 주문 1건. 재시작하면 사라지는 세션 한정 기록이다.
 *
 * 전체 이력은 거래내역 화면이 담당한다. 여기는 "방금 낸 주문이 어떻게 됐는지" 만 본다.
 */
export interface SessionOrder {
  /** 렌더러가 만드는 키. 브로커 주문번호는 실패 시 없을 수 있다. */
  localId: string
  side: 'BUY' | 'SELL'
  qty: number
  /** 주문 시 넘긴 지정가. 즉시 체결 의도였으면 null. */
  requestedPrice: number | null
  status: 'PENDING' | 'EXECUTED' | 'FAILED'
  executedQty: number
  executedPrice: number | null
  brokerOrderId: string | null
  errorMessage: string | null
  placedAt: number
}

/** 백엔드 `GET /api/v1/trades` 응답 항목 중 주문 패널 갱신에 쓰는 필드. */
export interface TradeRecord {
  brokerOrderId: string | null
  status: string
  executedQty: number
  executedPrice: number | null
}

/**
 * 백엔드 거래 기록으로 이 화면의 접수(PENDING) 주문 상태를 갱신한다.
 *
 * 짝짓는 키는 증권사 주문번호(ODNO)다. 패널 주문은 백엔드 tradeId 를 모르고, 체결 재확인은
 * 백엔드 기록만 고치기 때문에 둘을 잇는 값이 이것뿐이다.
 *
 * - 이미 체결·실패로 끝난 주문은 건드리지 않는다
 * - 백엔드의 EXPIRED(접수 후 24시간 미체결)는 그대로 둔다. 실제로 취소됐는지 알 수 없다
 * - 체결가가 0 이하면 null 로 둔다. 체결조회가 가격을 못 받으면 백엔드가 0 으로 저장한다
 * - 백엔드가 아직 PENDING 이거나 기록이 없으면 그대로 둔다 — "모른다" 를 결과로 단정하지 않는다
 * - 바뀐 것이 없으면 같은 배열을 돌려준다. React 가 불필요하게 다시 그리지 않게 하기 위해서다
 */
export function applyTradeRecords(
  orders: readonly SessionOrder[],
  trades: readonly TradeRecord[],
): readonly SessionOrder[] {
  const byOrderId = new Map<string, TradeRecord>()
  for (const trade of trades) {
    if (trade.brokerOrderId) byOrderId.set(trade.brokerOrderId, trade)
  }

  let changed = false
  const next = orders.map((order) => {
    if (order.status !== 'PENDING' || !order.brokerOrderId) return order
    const trade = byOrderId.get(order.brokerOrderId)
    if (!trade) return order
    if (trade.status === 'EXECUTED') {
      changed = true
      return {
        ...order,
        status: 'EXECUTED' as const,
        executedQty: trade.executedQty,
        executedPrice:
          trade.executedPrice != null && trade.executedPrice > 0 ? trade.executedPrice : null,
      }
    }
    if (trade.status === 'FAILED') {
      changed = true
      return { ...order, status: 'FAILED' as const }
    }
    return order
  })
  return changed ? next : orders
}
