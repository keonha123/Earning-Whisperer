import type { Holding } from '../../store/usePortfolioStore'

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

const STATUS_META: Record<SessionOrder['status'], { label: string; color: string; bg: string }> = {
  PENDING:  { label: '접수',     color: 'var(--caution)', bg: 'rgba(var(--caution-rgb),0.12)'  },
  EXECUTED: { label: '체결',     color: 'var(--ok)', bg: 'rgba(var(--ok-rgb),0.12)'  },
  FAILED:   { label: '실패',     color: 'var(--danger)', bg: 'rgba(var(--danger-rgb),0.12)'   },
}

interface PositionOrderPanelProps {
  ticker: string | null
  /**
   * 이 종목의 보유 정보. 잔고를 아직 불러오지 않았으면 `undefined` 다.
   * 0주 보유와 구분해야 한다 — 둘을 같이 보여주면 "안 갖고 있다" 로 오해한다.
   */
  holding: Holding | undefined
  /** 잔고를 한 번이라도 불러왔는지. `holding` 의 undefined 를 해석하는 데 쓴다. */
  balanceLoaded: boolean
  /** 현재가. 없으면 평가손익을 계산하지 않는다. */
  currentPrice: number | undefined
  /** 이 화면에서 낸 주문. 최근 것이 앞에 온다. */
  orders: readonly SessionOrder[]
  /** 접수 주문의 체결 여부를 다시 확인한다. 없으면 새로고침 버튼을 그리지 않는다. */
  onRefreshOrders?: () => void
  /** 다시 확인하는 중인지. 버튼을 막고 문구를 바꾼다. */
  refreshingOrders?: boolean
}

function formatUsd(value: number): string {
  return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatTime(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString('ko-KR', { hour12: false })
}

/**
 * PositionOrderPanel — 우측 하단 보유 현황 · 주문 상태 패널.
 *
 * 주문 바 바로 위에 온다. 주문을 내기 직전에 필요한 것(지금 몇 주 갖고 있고 평단이 얼마인지)과
 * 낸 직후에 필요한 것(접수됐는지 체결됐는지)을 한자리에서 본다.
 *
 * 전체 종목의 거래 이력은 거래내역 화면이 담당한다. 여기는 <b>이 종목, 이번 세션</b>으로
 * 범위를 좁혀 역할이 겹치지 않게 한다.
 */
export default function PositionOrderPanel({
  ticker,
  holding,
  balanceLoaded,
  currentPrice,
  orders,
  onRefreshOrders,
  refreshingOrders = false,
}: PositionOrderPanelProps) {
  const hasPending = orders.some((o) => o.status === 'PENDING')
  const qty = holding?.qty ?? 0
  const avgPrice = holding?.avgPrice ?? 0
  // 평가손익은 현재가가 있어야 계산된다. 없는 값을 0 으로 보여주면 손익이 없는 것처럼 읽힌다.
  const marketValue = currentPrice != null ? currentPrice * qty : null
  const pnl = marketValue != null && qty > 0 ? marketValue - avgPrice * qty : null
  const pnlPercent = pnl != null && avgPrice > 0 ? (pnl / (avgPrice * qty)) * 100 : null

  return (
    <div className="flex flex-col min-h-0 h-full">
      {/* 헤더 */}
      <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
          보유 · 주문
        </span>
        <span className="num text-[10px] text-text-tertiary">{ticker ?? '—'}</span>
      </div>

      {/* 보유 현황 */}
      <div className="px-3.5 py-2 border-b border-border-subtle shrink-0">
        {!balanceLoaded ? (
          <div className="text-[10.5px] text-text-disabled">잔고를 불러오지 않았습니다.</div>
        ) : qty === 0 ? (
          <div className="text-[10.5px] text-text-disabled">보유하지 않은 종목입니다.</div>
        ) : (
          <div className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[10px] text-text-tertiary">보유</span>
              <span className="num text-[12px] text-text-primary tabular-nums">
                {qty.toLocaleString()}주
              </span>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[10px] text-text-tertiary">평단</span>
              <span className="num text-[11px] text-text-secondary tabular-nums">
                ${formatUsd(avgPrice)}
              </span>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[10px] text-text-tertiary">평가손익</span>
              {pnl == null ? (
                <span className="text-[10.5px] text-text-disabled">현재가 없음</span>
              ) : (
                <span
                  className="num text-[11px] tabular-nums"
                  style={{ color: pnl >= 0 ? 'var(--up)' : 'var(--down)' }}
                >
                  {pnl >= 0 ? '+' : '−'}${formatUsd(Math.abs(pnl))}
                  {pnlPercent != null && (
                    <span className="text-[10px] ml-1">
                      ({pnl >= 0 ? '+' : '−'}
                      {Math.abs(pnlPercent).toFixed(2)}%)
                    </span>
                  )}
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 이번 세션 주문 */}
      <div className="h-7 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <span className="text-[10px] text-text-tertiary uppercase tracking-[0.1em]">
          이번 세션 주문
        </span>
        <span className="inline-flex items-center gap-2">
          {/*
            접수 주문이 있을 때만 보인다. 체결통보를 받으면 자동으로 바뀌지만, 통보를 못 받는
            경우(HTS ID 미등록, 연결 끊김)가 있어 직접 확인하는 길을 둔다. 주기 폴링은 KIS
            호출 제한 때문에 두지 않는다.
          */}
          {hasPending && onRefreshOrders && (
            <button
              type="button"
              onClick={onRefreshOrders}
              disabled={refreshingOrders}
              className="text-[10px] text-text-tertiary hover:text-text-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {refreshingOrders ? '확인 중…' : '새로고침'}
            </button>
          )}
          <span className="num text-[10px] text-text-disabled tabular-nums">{orders.length}건</span>
        </span>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 px-2 py-1.5 flex flex-col gap-1">
        {orders.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-[10.5px] text-text-disabled">
            아직 주문이 없습니다.
          </div>
        ) : (
          orders.map((order) => {
            // 일부만 체결되면 체결로 확정되지만(백엔드 콜백 규칙) 증권사에는 잔량이 남아 있을 수
            // 있다. "체결" 만 보여주면 전량 체결로 읽힌다.
            const isPartial =
              order.status === 'EXECUTED' && order.executedQty > 0 && order.executedQty < order.qty
            const meta = isPartial
              ? { ...STATUS_META.EXECUTED, label: '부분 체결' }
              : STATUS_META[order.status]
            const isBuy = order.side === 'BUY'
            return (
              <div
                key={order.localId}
                className="rounded border border-border-subtle bg-surface-2 px-2 py-1.5 flex flex-col gap-0.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className="text-[9.5px] font-semibold"
                      style={{ color: isBuy ? 'var(--up)' : 'var(--down)' }}
                    >
                      {isBuy ? '매수' : '매도'}
                    </span>
                    <span className="num text-[10.5px] text-text-primary tabular-nums">
                      {order.qty.toLocaleString()}주
                    </span>
                  </span>
                  <span
                    className="text-[9px] font-semibold px-1.5 py-0.5 rounded"
                    style={{ color: meta.color, backgroundColor: meta.bg }}
                  >
                    {meta.label}
                  </span>
                </div>

                <div className="flex items-center justify-between gap-2">
                  <span className="num text-[9.5px] text-text-tertiary tabular-nums">
                    {order.status === 'EXECUTED' && order.executedPrice != null
                      ? `$${formatUsd(order.executedPrice)} × ${order.executedQty.toLocaleString()}`
                      : order.requestedPrice != null
                        ? `지정가 $${formatUsd(order.requestedPrice)}`
                        : '즉시 체결'}
                  </span>
                  <span className="num text-[9px] text-text-disabled tabular-nums">
                    {formatTime(order.placedAt)}
                  </span>
                </div>

                {/*
                  접수 상태는 지정가가 걸려 체결을 기다리는 것이다. 체결통보가 오면 자동으로
                  바뀌고, 오지 않으면(HTS ID 미등록, 연결 끊김) 위 새로고침으로 확인한다.
                */}
                {order.status === 'PENDING' && (
                  <span className="text-[9px] text-text-disabled">
                    체결통보를 받으면 바뀝니다. 그대로면 새로고침으로 확인합니다.
                  </span>
                )}

                {order.errorMessage && (
                  <span className="text-[9px] leading-snug" style={{ color: 'var(--danger)' }}>
                    {order.errorMessage}
                  </span>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
