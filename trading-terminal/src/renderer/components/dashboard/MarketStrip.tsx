import type { MarketIndexItem } from '../../fixtures/marketIndex.dev-mock'

interface MarketStripProps {
  items: readonly MarketIndexItem[]
  className?: string
}

/**
 * MarketStrip — 상단 시장 지수 행 (SPX/NDX/VIX 등).
 *
 * 디자인 매칭: DashboardPage.html `.strip` (height 42px).
 *
 * 레이아웃:
 *  - 가로 flex, 균등 분할.
 *  - 각 셀: pip(3px 컬러바) + symbol + price + change badge.
 *  - 셀 사이 좌측 보더 (border-subtle).
 *
 * NOTE: 데이터는 MarketStripContainer (DashboardPage 내부) 에서
 *  import.meta.env.DEV 가드로 dev-mock 만 주입한다.
 *  prod 에서는 호출자가 빈 배열 → placeholder 분기 처리.
 */
export default function MarketStrip({ items, className = '' }: MarketStripProps) {
  if (items.length === 0) {
    return (
      <div
        className={`h-[42px] flex items-center justify-center px-4
                    bg-surface-1 border border-border-subtle rounded-lg
                    text-[11px] text-text-disabled tracking-wide ${className}`}
      >
        시장 지표 동기화 중…
      </div>
    )
  }

  return (
    <div
      className={`h-[42px] flex items-stretch overflow-hidden
                  bg-surface-1 border border-border-subtle rounded-lg ${className}`}
      role="region"
      aria-label="글로벌 지수"
    >
      {items.map((it, idx) => {
        const pipColor =
          it.trend === 'up'
            ? 'bg-buy shadow-[0_0_8px_rgba(16,185,129,0.5)]'
            : it.trend === 'down'
              ? 'bg-sell shadow-[0_0_8px_rgba(239,68,68,0.4)]'
              : 'bg-neutral'
        const chgColor =
          it.changePercent > 0
            ? 'text-buy bg-buy/10'
            : it.changePercent < 0
              ? 'text-sell bg-sell/10'
              : 'text-text-tertiary bg-surface-2'
        const sign = it.changePercent > 0 ? '+' : ''
        const chgLabel =
          it.format === 'percent'
            ? `${sign}${it.changePercent.toFixed(2)}`
            : `${sign}${it.changePercent.toFixed(2)}%`
        const priceLabel =
          it.format === 'percent'
            ? `${it.price.toFixed(2)}%`
            : it.price.toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })

        return (
          <div
            key={it.symbol}
            className={`flex-1 flex items-center gap-2 px-3.5 ${
              idx > 0 ? 'border-l border-border-subtle' : ''
            }`}
          >
            <span className={`w-[3px] h-[18px] rounded-sm flex-none ${pipColor}`} />
            <span className="num text-[10px] font-semibold text-text-tertiary tracking-[0.16em]">
              {it.symbol}
            </span>
            <span className="num text-[13px] font-semibold text-text-primary tabular-nums">
              {priceLabel}
            </span>
            <span
              className={`num text-[11px] font-semibold tabular-nums ml-auto px-1.5 py-px rounded-[3px] ${chgColor}`}
            >
              {chgLabel}
            </span>
          </div>
        )
      })}
    </div>
  )
}
