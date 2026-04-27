import { useMemo, useState } from 'react'
import Stepper from '../common/Stepper'
import type { TradingMode } from '../../store/useTradingStore'

export type OrderSide = 'BUY' | 'SELL'

export interface OrderBarSubmitPayload {
  side: OrderSide
  qty: number
  /** 시장가 = null, 지정가 = 가격값. */
  price: number | null
}

interface OrderBarProps {
  ticker: string | null
  /** 현재가 (USD). null 이면 표시만 비활성. */
  currentPrice: number | null
  /** 등락률 (%) — UI 색상용. */
  changePercent?: number
  /** 외화 예수금 (USD). */
  orderableCash: number
  /** 트레이딩 모드. AUTO_PILOT 일 때는 입력 비활성. */
  mode: TradingMode
  /** 주문 제출 콜백. 페이지가 IPC 호출. */
  onSubmit: (payload: OrderBarSubmitPayload) => void
  /** 처리 중 표시. */
  isLoading?: boolean
  /**
   * 명시적 비활성. AUTO_PILOT 외 사유 (e.g. prod 빌드에서 manual order IPC 미구현)
   * 로 인해 입력 자체를 막고 안내 라벨을 표시해야 할 때 true.
   */
  disabled?: boolean
  /**
   * disabled=true 시 주문 버튼 자리에 표시할 안내 라벨.
   * 예: "수동 주문은 다음 업데이트에서 지원됩니다".
   */
  disabledLabel?: string
}

/**
 * 지정가 입력 상한 (USD/주). 실제 미국 주식 종가 최고치 (BRK.A 약 $700K) 의
 * 안전 여유분. 사용자가 1e308 같은 비현실적인 값을 paste 시 estimatedTotal 이
 * Infinity 가 되는 것을 방지. main 측 검증 (KIS_PLACE_MANUAL_ORDER 신규 채널)
 * 도입 시 동일 상한을 서버측에서도 강제할 것.
 */
const MAX_LIMIT_PRICE = 1_000_000

/**
 * OrderBar — 하단 80px 고정 매매 입력 바.
 *
 * 디자인 매칭: TradingRoomPage.html `.order` + `.bs-toggle` + `.ord-*`.
 *
 * 레이아웃 (좌→우):
 *  1. ord-ticker     ticker + 현재가 + 등락률
 *  2. bs-toggle      BUY/SELL 탭
 *  3. ord-qty        Stepper 수량 + MAX 버튼
 *  4. ord-calc       예상 체결액 + 예수금
 *  5. ord-actions    시장가 토글 + 주문 버튼
 *
 * AUTO_PILOT 가드:
 *  - 모든 입력 비활성, 주문 버튼 자리에 안내 라벨.
 *  - 신호 도착 → main 측 TradeExecutor 가 자동 실행하므로 수동 입력 불필요.
 *
 * 데이터 출처:
 *  - currentPrice / changePercent: 활성 신호 또는 fixture (TradingRoomPage 가 결정).
 *  - orderableCash: usePortfolioStore.
 *  - 주문 IPC 호출은 페이지 책임 — 본 컴포넌트는 onSubmit 콜백만.
 */
export default function OrderBar({
  ticker,
  currentPrice,
  changePercent,
  orderableCash,
  mode,
  onSubmit,
  isLoading,
  disabled,
  disabledLabel,
}: OrderBarProps) {
  const [side, setSide] = useState<OrderSide>('BUY')
  const [qty, setQty] = useState<number>(1)
  const [isMarket, setIsMarket] = useState<boolean>(true)
  const [limitPrice, setLimitPrice] = useState<string>('')

  const isAuto = mode === 'AUTO_PILOT'
  // 입력 비활성 통합 플래그 — AUTO_PILOT (자동 실행) 또는 외부에서 명시 disabled.
  const inputsLocked = isAuto || disabled === true
  const hasPrice = currentPrice != null && Number.isFinite(currentPrice) && currentPrice > 0

  // 예상 체결액 (시장가는 현재가 기준, 지정가는 입력가 기준).
  // 가드: 음수 / NaN / Infinity / 비현실적 상한 초과 → null 처리.
  //   사용자가 `1e308` 등을 paste 했을 때 estimatedTotal 이 Infinity 로 표시되는 것을 방지.
  //   prod 연결 시 main 측에서 동일 검증을 KIS_PLACE_MANUAL_ORDER 핸들러에 적용해야 한다.
  const effectivePrice = useMemo(() => {
    if (isMarket) return hasPrice ? (currentPrice as number) : null
    const parsed = parseFloat(limitPrice)
    if (!Number.isFinite(parsed)) return null
    if (parsed <= 0 || parsed >= MAX_LIMIT_PRICE) return null
    return parsed
  }, [isMarket, limitPrice, currentPrice, hasPrice])

  const estimatedTotal = effectivePrice != null ? effectivePrice * qty : null

  // MAX = 예수금으로 살 수 있는 최대 수량 (BUY 한정). 0 으로 나누기 방지.
  const maxBuyQty = useMemo(() => {
    if (!hasPrice || (currentPrice as number) <= 0 || orderableCash <= 0) return 0
    return Math.floor(orderableCash / (currentPrice as number))
  }, [orderableCash, currentPrice, hasPrice])

  function handleSubmit() {
    // TODO(impl): main 측 KIS_PLACE_MANUAL_ORDER 채널 추가 시
    //   validateManualOrder(side, ticker, qty, price) 함께 도입 — 클라이언트 가드 외에
    //   금액 상한 / 보유수량(SELL) / 시간외 주문 가부 등을 서버에서 재검증할 것.
    if (inputsLocked || isLoading || !ticker) return
    if (qty <= 0) return
    if (!isMarket && effectivePrice == null) return
    onSubmit({
      side,
      qty,
      price: isMarket ? null : effectivePrice,
    })
  }

  // 디자인: grid-template-columns:180px 150px 1fr 1fr auto
  return (
    <div
      className="h-20 shrink-0 bg-surface-0 border-t border-border-strong px-4
                 grid items-center gap-3.5"
      style={{ gridTemplateColumns: '180px 150px 1fr 1fr auto' }}
      aria-label="주문 입력 바"
    >
      {/* 1. ord-ticker */}
      <div className="flex flex-col">
        <span className="num text-base font-bold text-text-primary">
          {ticker ?? '—'}
        </span>
        <span className="num text-[13px] text-text-primary">
          {hasPrice ? formatUsd(currentPrice as number) : '—'}
          {changePercent != null && Number.isFinite(changePercent) && (
            <span
              className={`num text-[11px] ml-1.5 ${
                changePercent >= 0 ? 'text-buy' : 'text-sell'
              }`}
            >
              {changePercent >= 0 ? '+' : ''}{changePercent.toFixed(2)}%
            </span>
          )}
        </span>
      </div>

      {/* 2. bs-toggle */}
      <div
        role="tablist"
        aria-label="매수 / 매도 선택"
        className="inline-flex bg-surface-1 border border-border-subtle rounded-md p-0.5 gap-0.5 w-fit"
      >
        <SideButton
          active={side === 'BUY'}
          onClick={() => setSide('BUY')}
          disabled={inputsLocked}
          tone="buy"
          label="▲ BUY"
        />
        <SideButton
          active={side === 'SELL'}
          onClick={() => setSide('SELL')}
          disabled={inputsLocked}
          tone="sell"
          label="▼ SELL"
        />
      </div>

      {/* 3. ord-qty */}
      <div className="flex flex-col gap-1 min-w-0">
        <span className="text-[10px] text-text-tertiary uppercase tracking-[0.1em]">
          수량
        </span>
        <div className="flex items-center gap-1.5">
          <div className="w-28">
            <Stepper
              value={qty}
              min={1}
              max={Math.max(1, maxBuyQty || 9999)}
              onChange={setQty}
              ariaLabel="주문 수량"
              disabled={inputsLocked}
            />
          </div>
          <button
            type="button"
            onClick={() => maxBuyQty > 0 && setQty(maxBuyQty)}
            disabled={inputsLocked || maxBuyQty <= 0}
            className="px-2 py-1 rounded border border-border-strong text-[10px] font-semibold
                       tracking-[0.08em] text-text-tertiary
                       hover:bg-surface-2 hover:text-text-primary
                       disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label={`최대 수량 ${maxBuyQty}주`}
          >
            MAX {maxBuyQty || 0}
          </button>
          <span className="num text-[10px] text-text-disabled">주</span>
        </div>
      </div>

      {/* 4. ord-calc */}
      <div className="flex flex-col gap-1 min-w-0">
        <div className="flex justify-between items-baseline gap-3 text-[11px]">
          <span className="text-text-tertiary uppercase tracking-[0.06em]">
            예상 체결액
          </span>
          <span className="num text-[13px] font-semibold text-text-primary tabular-nums">
            {estimatedTotal != null ? formatUsd(estimatedTotal) : '—'}
          </span>
        </div>
        <div className="flex justify-between items-baseline gap-3 text-[11px]">
          <span className="text-text-tertiary uppercase tracking-[0.06em]">
            예수금
          </span>
          <span className="num text-[11px] text-text-tertiary tabular-nums">
            {formatUsd(orderableCash)}
          </span>
        </div>
      </div>

      {/* 5. ord-actions */}
      <div className="flex items-center gap-2">
        {/* 시장가/지정가 토글 — 디자인의 [시장가 ▾] 자리. 클릭 시 입력 노출. */}
        <button
          type="button"
          onClick={() => setIsMarket((v) => !v)}
          disabled={inputsLocked}
          className="h-9 px-3.5 rounded-md bg-surface-2 border border-border-strong
                     text-text-primary text-xs font-semibold inline-flex items-center gap-1.5
                     hover:bg-surface-3 disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label={isMarket ? '시장가 (클릭하여 지정가로 변경)' : '지정가 (클릭하여 시장가로 변경)'}
        >
          {isMarket ? '시장가' : '지정가'}
          <span className="text-[9px] text-text-tertiary">▾</span>
        </button>

        {!isMarket && (
          <input
            type="number"
            value={limitPrice}
            onChange={(e) => setLimitPrice(e.target.value)}
            placeholder={hasPrice ? (currentPrice as number).toFixed(2) : '0.00'}
            disabled={inputsLocked}
            min={0}
            max={MAX_LIMIT_PRICE}
            step="0.01"
            className="num w-24 h-9 px-2.5 rounded-md bg-surface-3 border border-border-strong
                       text-text-primary text-[13px] text-right tabular-nums
                       focus:outline-none focus:border-accent-500 focus:ring-1 focus:ring-accent-500/30
                       disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="지정가 입력"
          />
        )}

        {isAuto ? (
          <span className="h-9 px-4 rounded-md bg-surface-2 border border-border-subtle
                           text-text-tertiary text-xs font-semibold inline-flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" />
            AUTO 모드 — 자동 실행
          </span>
        ) : disabled ? (
          // 외부 disabled (e.g. prod 빌드에서 manual order IPC 미구현) — silent noop 대신
          // 명시적 비활성 안내. AUTO_PILOT 분기와 동일 패턴 (시각적 disabled + 라벨).
          <span
            className="h-9 px-4 rounded-md bg-surface-2 border border-border-subtle
                       text-text-tertiary text-xs font-semibold inline-flex items-center gap-2"
            role="status"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-neutral" />
            {disabledLabel ?? '준비 중'}
          </span>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isLoading || !ticker || qty <= 0 || (!isMarket && effectivePrice == null)}
            className={
              'h-9 px-4 rounded-md text-xs font-bold tracking-[0.04em] inline-flex items-center gap-1.5 ' +
              'disabled:opacity-40 disabled:cursor-not-allowed transition-colors duration-100 ' +
              (side === 'BUY'
                ? 'bg-accent-500 hover:bg-accent-600 text-accent-foreground'
                : 'bg-sell hover:bg-sell-hover text-white')
            }
            aria-label={`${side} ${qty}주 주문`}
          >
            {isLoading ? (
              <>
                <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                처리 중
              </>
            ) : (
              <>
                {side === 'BUY' ? '▲ BUY' : '▼ SELL'} 주문
              </>
            )}
          </button>
        )}
      </div>
    </div>
  )
}

interface SideButtonProps {
  active: boolean
  onClick: () => void
  disabled?: boolean
  tone: 'buy' | 'sell'
  label: string
}

function SideButton({ active, onClick, disabled, tone, label }: SideButtonProps) {
  const activeClass =
    tone === 'buy'
      ? 'bg-buy/[0.14] text-buy shadow-[inset_0_0_0_1px_rgba(16,185,129,0.35)]'
      : 'bg-sell/[0.14] text-sell shadow-[inset_0_0_0_1px_rgba(239,68,68,0.35)]'
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      disabled={disabled}
      className={
        'px-3.5 py-1.5 rounded num text-xs font-bold tracking-[0.04em] inline-flex items-center gap-1.5 ' +
        'disabled:opacity-40 disabled:cursor-not-allowed ' +
        (active ? activeClass : 'text-text-tertiary hover:text-text-primary')
      }
    >
      {label}
    </button>
  )
}

/** USD 사람-친화 포맷 ($1,255.00). 소수점 2자리 고정. */
function formatUsd(v: number): string {
  if (!Number.isFinite(v)) return '—'
  return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
