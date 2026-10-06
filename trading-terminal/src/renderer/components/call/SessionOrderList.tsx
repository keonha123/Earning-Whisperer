import type { SessionOrder } from '../../lib/sessionOrders'

const STATUS_META: Record<SessionOrder['status'], { label: string; color: string }> = {
  PENDING: { label: '접수', color: 'var(--caution)' },
  EXECUTED: { label: '체결', color: 'var(--ok)' },
  FAILED: { label: '실패', color: 'var(--danger)' },
}

interface SessionOrderListProps {
  orders: readonly SessionOrder[]
  /** 접수 주문의 체결 여부를 다시 확인한다. */
  onRefresh: () => void
  refreshing: boolean
}

const TIME = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Seoul',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function usd(v: number): string {
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/**
 * 이번 세션에 이 화면에서 낸 주문 — 접수에서 체결로 바뀌는 것을 주문한 자리에서 본다.
 * 전체 이력은 포트폴리오의 거래 내역이 담당한다.
 */
export default function SessionOrderList({ orders, onRefresh, refreshing }: SessionOrderListProps) {
  const hasPending = orders.some((o) => o.status === 'PENDING')
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] font-semibold text-ink-2">
          이번 세션 주문 <span className="tabular-nums text-ink-3 font-normal">{orders.length}</span>
        </span>
        {/*
          체결통보를 받으면 자동으로 바뀌지만, 통보를 못 받는 경우(HTS ID 미등록, 연결 끊김)가 있어
          직접 확인하는 길을 둔다. 주기 폴링은 KIS 호출 제한 때문에 두지 않는다.
        */}
        {hasPending && (
          <button type="button" onClick={onRefresh} disabled={refreshing} className="gbtn gbtn-sm">
            {refreshing ? '확인 중' : '체결 확인'}
          </button>
        )}
      </div>
      {orders.length === 0 ? (
        <p className="text-[12.5px] text-ink-3">아직 주문이 없습니다.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {orders.map((order) => {
            // 일부만 체결되면 체결로 확정되지만 증권사에는 잔량이 남아 있을 수 있다.
            const isPartial = order.status === 'EXECUTED' && order.executedQty > 0 && order.executedQty < order.qty
            const meta = isPartial ? { ...STATUS_META.EXECUTED, label: '부분 체결' } : STATUS_META[order.status]
            const isBuy = order.side === 'BUY'
            return (
              <li key={order.localId} className="rounded-[14px] bg-white/[0.04] px-3 py-2 flex flex-col gap-0.5 text-[12.5px]">
                <div className="flex items-center justify-between gap-2">
                  <span>
                    <span className="font-semibold" style={{ color: isBuy ? 'var(--up)' : 'var(--down)' }}>
                      {isBuy ? '매수' : '매도'}
                    </span>{' '}
                    <span className="tabular-nums text-ink-1">{order.qty.toLocaleString()}주</span>
                  </span>
                  <span className="font-semibold" style={{ color: meta.color }}>
                    {meta.label}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2 text-[11.5px] text-ink-3 tabular-nums">
                  <span>
                    {order.status === 'EXECUTED' && order.executedPrice != null
                      ? `$${usd(order.executedPrice)} × ${order.executedQty.toLocaleString()}`
                      : order.requestedPrice != null
                        ? `지정가 $${usd(order.requestedPrice)}`
                        : '즉시 체결'}
                  </span>
                  <span className="num">{TIME.format(new Date(order.placedAt))}</span>
                </div>
                {order.errorMessage && <span className="text-[11.5px] text-danger leading-snug">{order.errorMessage}</span>}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
