import { useMemo } from 'react'
import type { Holding } from '../../store/usePortfolioStore'
import type { PricePoint } from '../../types/priceSeries'
import { showComingSoon } from './comingSoon'

interface PriceCardProps {
  currentPrice: number | null
  changeAmount?: number
  changePercent?: number
  /** 30일 일봉 종가. */
  series: readonly PricePoint[]
  /** 이 종목 보유 정보. 잔고를 아직 못 불러왔으면 undefined. */
  holding: Holding | undefined
  balanceLoaded: boolean
}

const TIMEFRAMES = ['1분', '5분', '1시간', '1일', '30일'] as const

/**
 * 가격과 내 포지션 — 콜 화면의 보조 자리 (시작 전 옆, 진행 중 가격 탭).
 *
 * 차트는 30일 일봉 종가뿐이다. 분봉 기간 버튼은 데이터가 없어 자리만 둔다.
 * 등락은 색과 함께 ▲ ▼ 를 붙인다. 없는 값은 0 으로 채우지 않는다.
 */
export default function PriceCard({
  currentPrice,
  changeAmount,
  changePercent,
  series,
  holding,
  balanceLoaded,
}: PriceCardProps) {
  const up = (changePercent ?? 0) >= 0
  const hasChange = changePercent != null && Number.isFinite(changePercent)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="tabular-nums text-[24px] font-semibold text-ink-1">
          {currentPrice != null ? `$${currentPrice.toFixed(2)}` : '—'}
        </span>
        {hasChange && (
          <span className="tabular-nums text-[13px] font-semibold" style={{ color: up ? 'var(--up)' : 'var(--down)' }}>
            {up ? '▲' : '▼'}
            {changeAmount != null && Number.isFinite(changeAmount) && ` ${Math.abs(changeAmount).toFixed(2)}`} (
            {up ? '+' : '−'}
            {Math.abs(changePercent as number).toFixed(2)}%)
          </span>
        )}
      </div>

      <div className="flex gap-1 flex-wrap" role="group" aria-label="차트 기간">
        {TIMEFRAMES.map((tf) =>
          tf === '30일' ? (
            <span key={tf} className="glass rim rim-float rounded-full px-3 py-1 text-[12px] font-semibold text-ink-1">
              {tf}
            </span>
          ) : (
            <button
              key={tf}
              type="button"
              onClick={() => showComingSoon(`${tf} 차트`)}
              className="rounded-full px-3 py-1 text-[12px] text-ink-4"
              aria-disabled="true"
            >
              {tf}
            </button>
          ),
        )}
      </div>

      <Sparkline series={series} />

      <div className="border-t border-border-subtle pt-3 flex flex-col gap-1.5 text-[13px]">
        <span className="text-[12px] text-ink-3">내 포지션</span>
        {!balanceLoaded ? (
          <span className="text-ink-3">잔고를 아직 불러오지 않았습니다.</span>
        ) : !holding || holding.qty === 0 ? (
          <span className="text-ink-2">보유하지 않은 종목입니다.</span>
        ) : (
          <HoldingRows holding={holding} currentPrice={currentPrice} />
        )}
      </div>
    </div>
  )
}

function HoldingRows({ holding, currentPrice }: { holding: Holding; currentPrice: number | null }) {
  const pnl = currentPrice != null ? (currentPrice - holding.avgPrice) * holding.qty : null
  const pnlPct = pnl != null && holding.avgPrice > 0 ? (pnl / (holding.avgPrice * holding.qty)) * 100 : null
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
      <dt className="text-ink-3">보유</dt>
      <dd className="tabular-nums text-right text-ink-1">{holding.qty.toLocaleString()}주</dd>
      <dt className="text-ink-3">평단</dt>
      <dd className="tabular-nums text-right text-ink-2">${holding.avgPrice.toFixed(2)}</dd>
      <dt className="text-ink-3">평가손익</dt>
      <dd className="tabular-nums text-right" style={{ color: pnl == null ? undefined : pnl >= 0 ? 'var(--up)' : 'var(--down)' }}>
        {pnl == null
          ? '현재가 없음'
          : `${pnl >= 0 ? '+' : '−'}$${Math.abs(pnl).toFixed(2)}${pnlPct != null ? ` (${pnl >= 0 ? '+' : '−'}${Math.abs(pnlPct).toFixed(2)}%)` : ''}`}
      </dd>
    </dl>
  )
}

/** 30일 종가 선. 결측치가 섞이면 SVG 경로가 깨지므로 걸러 낸다. */
function Sparkline({ series }: { series: readonly PricePoint[] }) {
  const W = 400
  const H = 120
  const path = useMemo(() => {
    const valid = series.filter((p) => Number.isFinite(p.price))
    if (valid.length < 2) return null
    const prices = valid.map((p) => p.price)
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const range = max - min || 1
    const step = W / (valid.length - 1)
    const pts = valid.map((p, i) => [i * step, 8 + ((max - p.price) / range) * (H - 16)] as const)
    const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    return {
      line,
      area: `${line} L${W},${H} L0,${H} Z`,
      first: valid[0].time,
      last: valid[valid.length - 1].time,
      min,
      max,
    }
  }, [series])

  if (!path) {
    return <div className="h-[120px] grid place-items-center text-[12px] text-ink-3">가격 기록이 없습니다.</div>
  }
  return (
    <figure className="flex flex-col gap-1">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-[120px]" role="img" aria-label="30일 종가 추이">
        <path d={path.area} fill="rgba(251,250,246,0.06)" />
        <path d={path.line} fill="none" stroke="var(--ink-2)" strokeWidth="1.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="flex justify-between num text-[11px] text-ink-3">
        <span>{path.first}</span>
        <span>
          ${path.min.toFixed(2)} ~ ${path.max.toFixed(2)}
        </span>
        <span>{path.last}</span>
      </figcaption>
    </figure>
  )
}
