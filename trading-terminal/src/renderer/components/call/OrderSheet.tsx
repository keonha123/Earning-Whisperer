import { useEffect, useMemo, useRef, useState } from 'react'
import SegmentedControl from '../common/SegmentedControl'
import Stepper from '../common/Stepper'
import SessionOrderList from './SessionOrderList'
import { useRefraction } from '../../lib/refraction'
import { maxOrderQty } from '../../lib/callScreen'
import type { SessionOrder } from '../../lib/sessionOrders'
import type { OrderAccount } from '../../hooks/useOrderAccount'
import { IMMEDIATE_FILL_BUFFER, immediateFillPrice } from '../../../lib/orderPricing'

export type OrderSide = 'BUY' | 'SELL'

export interface OrderSubmitPayload {
  side: OrderSide
  qty: number
  /** 즉시 체결 = null (main 이 현재가 기준 버퍼 지정가로 환산), 지정가 = 가격값. */
  price: number | null
}


interface OrderSheetProps {
  open: boolean
  onClose: () => void
  ticker: string
  currentPrice: number | null
  orderableCash: number
  /** 이 종목 보유 수량. 잔고를 못 불러왔으면 null. */
  heldQty: number | null
  /** 계좌를 아직 모르면 null — 모르는 채로 주문을 보내지 않는다. */
  account: OrderAccount | null
  /** KIS 계좌인데 키가 없으면 false. 이때는 입력 대신 키 등록 안내를 보인다. */
  hasKey: boolean
  onOpenSettings: () => void
  /** 전송. 성공 · 실패 기록은 호출 측이 남긴다. */
  onSubmit: (payload: OrderSubmitPayload) => Promise<void>
  submitting: boolean
  orders: readonly SessionOrder[]
  onRefreshOrders: () => void
  refreshingOrders: boolean
  /** 콜 바 아래에서 시작하도록 비워 두는 높이(px). */
  topInset: number
}

/** 지정가 입력 상한 (USD/주). 비현실적인 값이 들어와 예상 금액이 Infinity 가 되는 것을 막는다. */
const MAX_LIMIT_PRICE = 1_000_000

const ACCOUNT_META: Record<OrderAccount, { title: string; note: string }> = {
  KIS_PAPER: { title: 'KIS 모의투자 계좌', note: '모의투자 서버로 주문합니다. 실제 돈은 움직이지 않습니다.' },
  KIS_REAL: { title: 'KIS 실전투자 계좌', note: '실제 돈으로 주문합니다. 체결되면 되돌릴 수 없습니다.' },
  SELF_PAPER: { title: '페이퍼 계정', note: '증권사를 거치지 않고 현재가로 가상 체결합니다.' },
}

const SIDE_ITEMS: { id: OrderSide; label: string }[] = [
  { id: 'BUY', label: '매수' },
  { id: 'SELL', label: '매도' },
]

const TYPE_ITEMS: { id: 'IMMEDIATE' | 'LIMIT'; label: string }[] = [
  { id: 'IMMEDIATE', label: '즉시 체결' },
  { id: 'LIMIT', label: '지정가' },
]

function usd(v: number): string {
  return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/**
 * 주문 시트 — 콜 화면을 떠나지 않고 여는 보조 패널 (docs/design/ux.md 주문).
 *
 *  - 맨 위에 주문이 나가는 계좌(모의 · 실전 · 페이퍼)를 크게 쓴다.
 *  - `즉시 체결` 은 시장가가 아니라 현재가 ±1% 지정가라는 점을 화면에 둔다.
 *  - 전송 전에 확인 단계를 늘 거친다. 실전 계좌의 전송 버튼은 위험 행동(포르피라)이다.
 *  - 매도의 최대 수량은 보유 수량이다.
 *  - 콜 화면의 내용 위에 떠 있어 굴절을 건다. 읽고 입력하는 면이라 맑은 유리가 아니라 서리 유리이고,
 *    금테는 화면 중심 판의 2.2px 이다. 콜 바 아래에서 시작해 콜 바의 `주문` 버튼을 가리지 않는다.
 */
export default function OrderSheet(props: OrderSheetProps) {
  if (!props.open) return null
  return <OpenSheet {...props} />
}

/** 열렸을 때만 마운트한다 — 굴절 맵은 마운트된 요소의 크기로 만든다. */
/** 시트를 여닫는 버튼에 붙이는 표시. 바깥 클릭 판정에서 이 버튼은 뺀다(눌러서 닫는 것은 버튼이 한다). */
export const ORDER_TOGGLE_ATTR = 'data-order-toggle'

function OpenSheet(props: OrderSheetProps) {
  const { onClose, topInset } = props
  const ref = useRef<HTMLDivElement>(null)
  useRefraction(ref, 24)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    // 바깥을 누르면 닫는다. 덮개를 깔지 않아 시트가 열린 동안에도 자막 스크롤 · 콜 바를 그대로 쓴다.
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Element | null
      if (!target || ref.current?.contains(target)) return
      if (target.closest(`[${ORDER_TOGGLE_ATTR}]`)) return
      onClose()
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointerDown)
    // 닫히면 연 버튼으로 포커스를 돌려준다.
    const opener = document.activeElement as HTMLElement | null
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointerDown)
      if (opener && opener.isConnected) opener.focus()
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      role="dialog"
      aria-modal="false"
      aria-labelledby="order-sheet-title"
      className="frost rim rim-heavy absolute right-3 bottom-3 z-30 w-[400px] rounded-[30px] flex flex-col overflow-hidden animate-slide-in-top [-webkit-app-region:no-drag]"
      style={{ top: topInset }}
    >
      <SheetBody {...props} />
    </div>
  )
}

function SheetBody({
  onClose,
  ticker,
  currentPrice,
  orderableCash,
  heldQty,
  account,
  hasKey,
  onOpenSettings,
  onSubmit,
  submitting,
  orders,
  onRefreshOrders,
  refreshingOrders,
}: OrderSheetProps) {
  const [side, setSide] = useState<OrderSide>('BUY')
  const [type, setType] = useState<'IMMEDIATE' | 'LIMIT'>('IMMEDIATE')
  const [qty, setQty] = useState(1)
  const [limitPrice, setLimitPrice] = useState('')
  const [confirming, setConfirming] = useState(false)

  const hasPrice = currentPrice != null && Number.isFinite(currentPrice) && currentPrice > 0

  // 실제로 나갈 단가. 즉시 체결은 main 이 주문 시점 현재가로 다시 계산하지만, 예상 금액 · 최대 수량은
  // 버퍼가 얹힌 가격을 기준으로 보여 줘야 예수금 부족 거부를 피할 수 있다.
  const unitPrice = useMemo(() => {
    if (type === 'IMMEDIATE') return hasPrice ? immediateFillPrice(side, currentPrice as number) : null
    const parsed = parseFloat(limitPrice)
    if (!Number.isFinite(parsed) || parsed <= 0 || parsed >= MAX_LIMIT_PRICE) return null
    return parsed
  }, [type, hasPrice, side, currentPrice, limitPrice])

  const maxQty = maxOrderQty({ side, unitPrice, orderableCash, heldQty })
  const total = unitPrice != null ? unitPrice * qty : null
  const overMax = maxQty != null && qty > maxQty
  // 보유 수량을 모르면 매도를 막는다 — 모르는 채로 보내면 가진 것보다 많이 팔 수 있다.
  const sellUnknown = side === 'SELL' && heldQty == null
  const canReview =
    account !== null &&
    Number.isInteger(qty) &&
    qty > 0 &&
    unitPrice != null &&
    !overMax &&
    !sellUnknown &&
    !submitting
  const needsKey = account !== null && account !== 'SELF_PAPER' && !hasKey

  async function send() {
    // 확인 화면에 있는 동안 예수금 · 보유 · 가격이 바뀌었을 수 있다. 보내기 직전에 다시 본다.
    if (!canReview) return
    await onSubmit({ side, qty, price: type === 'IMMEDIATE' ? null : unitPrice })
    setConfirming(false)
  }

  // 단계가 바뀌면 누른 버튼이 사라진다. 포커스를 새 단계의 제목으로 옮긴다.
  const titleRef = useRef<HTMLSpanElement>(null)
  const confirmTitleRef = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    ;(confirming ? confirmTitleRef.current : titleRef.current)?.focus()
  }, [confirming])

  const meta = account ? ACCOUNT_META[account] : null
  const sideWord = side === 'BUY' ? '매수' : '매도'
  const bufferPct = (IMMEDIATE_FILL_BUFFER * 100).toFixed(0)

  return (
    <>
      <header className="px-6 pt-5 pb-4 flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[12px] text-ink-3">
            <span className="num text-ink-1 font-semibold">{ticker}</span> 주문
          </span>
          <span id="order-sheet-title" ref={titleRef} tabIndex={-1} className="text-[19px] font-bold text-ink-1 outline-none">
            {meta ? meta.title : '계좌 확인 중'}
          </span>
          {meta && (
            <span className={`text-[12.5px] leading-snug ${account === 'KIS_REAL' ? 'text-warning' : 'text-ink-3'}`}>
              {meta.note}
            </span>
          )}
        </div>
        <button type="button" onClick={onClose} className="gbtn gbtn-icon gbtn-sm shrink-0" aria-label="주문 닫기">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" strokeLinecap="round" />
          </svg>
        </button>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 flex flex-col gap-5">
        {needsKey ? (
          <div className="flex flex-col gap-3 py-4">
            <p className="text-[14px] text-ink-1 leading-relaxed">KIS 키를 등록하면 이 자리에서 주문할 수 있습니다.</p>
            <button type="button" className="gbtn gbtn-lapis self-start" onClick={onOpenSettings}>
              설정에서 키 등록
            </button>
          </div>
        ) : confirming ? (
          <div className="flex flex-col gap-4">
            <span ref={confirmTitleRef} tabIndex={-1} className="text-[17px] font-bold text-ink-1 outline-none">
              주문을 보낼까요?
            </span>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[14px]">
              <dt className="text-ink-3">계좌</dt>
              <dd className="text-right text-ink-1">{meta?.title}</dd>
              <dt className="text-ink-3">종목</dt>
              <dd className="num text-right text-ink-1">{ticker}</dd>
              <dt className="text-ink-3">방향</dt>
              <dd className="text-right font-semibold" style={{ color: side === 'BUY' ? 'var(--up)' : 'var(--down)' }}>
                {sideWord}
              </dd>
              <dt className="text-ink-3">수량</dt>
              <dd className="tabular-nums text-right text-ink-1">{qty.toLocaleString()}주</dd>
              <dt className="text-ink-3">가격</dt>
              <dd className="tabular-nums text-right text-ink-1">
                {unitPrice != null ? usd(unitPrice) : '—'}
                <span className="text-ink-3 text-[12px]"> {type === 'IMMEDIATE' ? '지정가 (즉시 체결)' : '지정가'}</span>
              </dd>
              <dt className="text-ink-3">예상 금액</dt>
              <dd className="tabular-nums text-right text-ink-1 font-semibold">{total != null ? usd(total) : '—'}</dd>
            </dl>
            <div className="flex gap-2 pt-2">
              <button type="button" className="gbtn flex-1" onClick={() => setConfirming(false)} disabled={submitting}>
                취소
              </button>
              <button
                type="button"
                className={`gbtn flex-1 ${account === 'KIS_REAL' ? 'gbtn-porphyra' : 'gbtn-lapis'}`}
                onClick={() => void send()}
                disabled={!canReview}
              >
                {submitting ? '보내는 중' : '주문 보내기'}
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <SegmentedControl items={SIDE_ITEMS} activeId={side} onChange={setSide} className="self-start" />

            <div className="flex flex-col gap-2">
              <span className="text-[12.5px] text-ink-3">수량</span>
              <div className="flex items-center gap-2">
                <div className="w-36">
                  <Stepper value={qty} min={1} max={Math.max(1, maxQty ?? 99999)} onChange={(v) => setQty(Math.max(1, Math.floor(v)))} ariaLabel="주문 수량" suffix="주" />
                </div>
                <button
                  type="button"
                  className="gbtn gbtn-sm"
                  onClick={() => maxQty && maxQty > 0 && setQty(maxQty)}
                  disabled={!maxQty}
                >
                  최대
                </button>
              </div>
              <span className="text-[12px] text-ink-3">
                {side === 'BUY'
                  ? maxQty == null
                    ? '가격을 알 수 없어 최대 수량을 계산하지 못했습니다'
                    : `최대 매수 ${maxQty.toLocaleString()}주`
                  : heldQty == null
                    ? '잔고를 불러오지 않아 보유 수량을 모릅니다'
                    : `보유 ${heldQty.toLocaleString()}주까지 팔 수 있습니다`}
              </span>
              {overMax && <span className="text-[12px] text-danger">최대 수량을 넘었습니다.</span>}
              {sellUnknown && <span className="text-[12px] text-danger">보유 수량을 확인한 뒤 매도할 수 있습니다.</span>}
            </div>

            <div className="flex flex-col gap-2">
              <SegmentedControl items={TYPE_ITEMS} activeId={type} onChange={setType} className="self-start" />
              {type === 'IMMEDIATE' ? (
                <p className="text-[12.5px] text-ink-2 leading-relaxed">
                  미국 주식은 시장가 주문이 없어 현재가보다 {bufferPct}% {side === 'BUY' ? '높은' : '낮은'} 지정가
                  {unitPrice != null && <span className="tabular-nums text-ink-1"> {usd(unitPrice)}</span>}로 냅니다.
                </p>
              ) : (
                <input
                  type="number"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  placeholder={hasPrice ? (currentPrice as number).toFixed(2) : '0.00'}
                  min={0}
                  max={MAX_LIMIT_PRICE}
                  step="0.01"
                  className="input-base tabular-nums w-40 text-right"
                  aria-label="지정가"
                />
              )}
            </div>

            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-[13.5px] border-t border-border-subtle pt-4">
              <dt className="text-ink-3">예상 금액</dt>
              <dd className="tabular-nums text-right text-ink-1 font-semibold">{total != null ? usd(total) : '—'}</dd>
              <dt className="text-ink-3">예수금</dt>
              <dd className="tabular-nums text-right text-ink-2">{usd(orderableCash)}</dd>
            </dl>

            <button
              type="button"
              className="gbtn gbtn-lapis w-full"
              disabled={!canReview}
              onClick={() => setConfirming(true)}
            >
              {sideWord} 확인
            </button>
          </div>
        )}

        <div className="border-t border-border-subtle pt-4">
          <SessionOrderList orders={orders} onRefresh={onRefreshOrders} refreshing={refreshingOrders} />
        </div>
      </div>
    </>
  )
}
