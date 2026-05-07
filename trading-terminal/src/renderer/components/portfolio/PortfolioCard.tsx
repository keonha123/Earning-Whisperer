import { useState } from 'react'
import type { Holding } from '../../store/usePortfolioStore'
import { usePricesStore } from '../../store/usePricesStore'
import type { IpcError } from '../../../lib/types/ipcError'
import StaleDataOverlay from '../common/StaleDataOverlay'

interface Props {
  orderableCash: number
  totalCash: number
  holdings: Holding[]
  totalAsset: number
  balanceFetchError?: IpcError | null
  onRetryBalance?: () => void
  isSyncing?: boolean
  lastSyncedAt?: number | null
}

// ── 페이지 1: 자산 현황 ────────────────────────────────────────────

function StackedBar({ cashRatio, stockRatio }: { cashRatio: number; stockRatio: number }) {
  return (
    <div className="w-full h-1.5 bg-[#1e2738] rounded-full overflow-hidden flex">
      <div
        className="h-full transition-all duration-500 bg-[#3b82f6]"
        style={{ width: `${Math.min(cashRatio * 100, 100)}%` }}
      />
      <div
        className="h-full transition-all duration-500 bg-[#22c55e]"
        style={{ width: `${Math.min(stockRatio * 100, 100)}%` }}
      />
    </div>
  )
}

function AssetPage({
  orderableCash, totalCash, cashRatio, stockValue, stockRatio,
}: {
  orderableCash: number; totalCash: number; cashRatio: number; stockValue: number; stockRatio: number
}) {
  return (
    <>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#3b82f6] shrink-0" />
          <span className="text-[10px] text-text-disabled uppercase tracking-wide">현금</span>
          <span className="num text-sm text-text-primary">
            ${totalCash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </span>
          <span className="num text-[10px] text-text-disabled">({(cashRatio * 100).toFixed(0)}%)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="num text-[10px] text-text-disabled">({(stockRatio * 100).toFixed(0)}%)</span>
          <span className="num text-sm text-text-primary">
            ${stockValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </span>
          <span className="text-[10px] text-text-disabled uppercase tracking-wide">평가</span>
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#22c55e] shrink-0" />
        </div>
      </div>
      <StackedBar cashRatio={cashRatio} stockRatio={stockRatio} />
      <p className="num text-[10px] text-text-disabled mt-1.5">
        주문가능 ${orderableCash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
      </p>
    </>
  )
}

// ── 페이지 2: 종목 비중 도넛 ──────────────────────────────────────

const DONUT_COLORS = ['#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4', '#f97316', '#ec4899', '#10b981', '#e879f9']

function DonutPage({ holdings, totalCash }: { holdings: Holding[]; totalCash: number }) {
  const slices: { label: string; value: number; color: string }[] = []
  if (totalCash > 0) slices.push({ label: '현금', value: totalCash, color: '#3b82f6' })
  holdings.forEach((h, i) => {
    const v = h.qty * (h.currentPrice ?? 0)
    if (v > 0) slices.push({ label: h.ticker, value: v, color: DONUT_COLORS[i % DONUT_COLORS.length] })
  })

  const total = slices.reduce((s, sl) => s + sl.value, 0)
  if (total === 0) {
    return <p className="text-text-disabled text-xs py-4 text-center">데이터 없음</p>
  }

  const cx = 40, cy = 40, outer = 28, inner = 16
  let angle = -Math.PI / 2
  const paths = slices.map((sl) => {
    const sweep = (sl.value / total) * 2 * Math.PI
    const end = angle + sweep
    const ox1 = cx + outer * Math.cos(angle), oy1 = cy + outer * Math.sin(angle)
    const ox2 = cx + outer * Math.cos(end), oy2 = cy + outer * Math.sin(end)
    const ix1 = cx + inner * Math.cos(end), iy1 = cy + inner * Math.sin(end)
    const ix2 = cx + inner * Math.cos(angle), iy2 = cy + inner * Math.sin(angle)
    const large = sweep > Math.PI ? 1 : 0
    const d = `M ${ox1} ${oy1} A ${outer} ${outer} 0 ${large} 1 ${ox2} ${oy2} L ${ix1} ${iy1} A ${inner} ${inner} 0 ${large} 0 ${ix2} ${iy2} Z`
    const result = { d, color: sl.color, label: sl.label, pct: (sl.value / total) * 100 }
    angle = end
    return result
  })

  return (
    <div className="flex items-center gap-3">
      <svg viewBox="0 0 80 80" className="w-14 h-14 shrink-0">
        {paths.map((p, i) => <path key={i} d={p.d} fill={p.color} />)}
      </svg>
      <div className="flex flex-col gap-1 flex-1 overflow-hidden">
        {paths.map((p, i) => (
          <div key={i} className="flex items-center gap-1.5 min-w-0">
            <span className="inline-block w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: p.color }} />
            <span className="text-[10px] text-text-disabled truncate flex-1">{p.label}</span>
            <span className="num text-[10px] text-text-secondary shrink-0">{p.pct.toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── 페이지 3: 일일 손익 ────────────────────────────────────────

function DailyPnlPage({ holdings }: { holdings: Holding[] }) {
  const prices = usePricesStore((s) => s.prices)

  if (holdings.length === 0) {
    return <p className="text-text-disabled text-xs py-4 text-center">보유 종목 없음</p>
  }

  const rows = holdings.map((h) => {
    const entry = prices[h.ticker]
    const cur = entry?.currentPrice ?? h.currentPrice
    const prev = entry?.previousClose ?? 0
    const pnl = prev > 0 ? (cur - prev) * h.qty : 0
    const pct = prev > 0 ? ((cur - prev) / prev) * 100 : null
    return { ticker: h.ticker, pnl, pct, hasData: prev > 0 }
  })
  const totalPnl = rows.reduce((s, r) => s + r.pnl, 0)
  const isPos = totalPnl >= 0

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-disabled uppercase tracking-wide">일간 손익</span>
        <span className={`num text-sm font-semibold ${isPos ? 'text-buy' : 'text-sell'}`}>
          {isPos ? '+' : ''}${totalPnl.toFixed(2)}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        {rows.map((r) => (
          <div key={r.ticker} className="flex items-center justify-between">
            <span className="num text-[10px] text-text-secondary">{r.ticker}</span>
            {r.hasData ? (
              <span className={`num text-[10px] ${r.pnl >= 0 ? 'text-buy' : 'text-sell'}`}>
                {r.pnl >= 0 ? '+' : ''}${r.pnl.toFixed(2)}{r.pct !== null ? ` (${r.pct >= 0 ? '+' : ''}${r.pct.toFixed(1)}%)` : ''}
              </span>
            ) : (
              <span className="num text-[10px] text-text-disabled">—</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── 페이지 4: 누적 손익 ───────────────────────────────────────────

function CumulativePnlPage({ holdings }: { holdings: Holding[] }) {
  if (holdings.length === 0) {
    return <p className="text-text-disabled text-xs py-4 text-center">보유 종목 없음</p>
  }

  const rows = holdings.map((h) => {
    const cur = h.currentPrice ?? 0
    const pnl = (cur - h.avgPrice) * h.qty
    const pct = h.avgPrice > 0 ? ((cur - h.avgPrice) / h.avgPrice) * 100 : 0
    return { ticker: h.ticker, pnl, pct }
  })
  const totalPnl = rows.reduce((s, r) => s + r.pnl, 0)
  const isPos = totalPnl >= 0

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-disabled uppercase tracking-wide">미실현 손익</span>
        <span className={`num text-sm font-semibold ${isPos ? 'text-buy' : 'text-sell'}`}>
          {isPos ? '+' : ''}${totalPnl.toFixed(2)}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        {rows.map((r) => (
          <div key={r.ticker} className="flex items-center justify-between">
            <span className="num text-[10px] text-text-secondary">{r.ticker}</span>
            <span className={`num text-[10px] ${r.pnl >= 0 ? 'text-buy' : 'text-sell'}`}>
              {r.pnl >= 0 ? '+' : ''}${r.pnl.toFixed(2)} ({r.pnl >= 0 ? '+' : ''}{r.pct.toFixed(1)}%)
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── 메인 ─────────────────────────────────────────────────────────

const PAGE_COUNT = 4

export default function PortfolioCard({
  orderableCash,
  totalCash,
  holdings,
  totalAsset,
  balanceFetchError = null,
  onRetryBalance,
  isSyncing = false,
  lastSyncedAt = null,
}: Props) {
  const [page, setPage] = useState(0)
  const stockValue = holdings.reduce((s, h) => s + h.qty * (h.currentPrice ?? 0), 0)
  const cashRatio = totalAsset > 0 ? totalCash / totalAsset : 1
  const stockRatio = totalAsset > 0 ? stockValue / totalAsset : 0

  return (
    // 바깥: overlay 기준점 (absolute 포지셔닝용)
    <div className="h-full relative">
      {/* 안쪽: 스크롤 컨테이너 — 총자산 + 페이지 컨텐츠가 함께 스크롤 */}
      <div className="h-full overflow-y-auto">
        {/* 총자산 섹션 — 압축 (pt-3 pb-2, text-xl) */}
        <div className="px-5 pt-3 pb-2 border-b border-[#1e2738]">
          <div className="flex items-center justify-between mb-0.5">
            <p className="text-[10px] text-text-disabled uppercase tracking-widest">총 자산 (USD)</p>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPage((p) => (p - 1 + PAGE_COUNT) % PAGE_COUNT)}
                className="text-text-disabled hover:text-text-primary transition-colors px-0.5 text-base leading-none"
              >
                ‹
              </button>
              {Array.from({ length: PAGE_COUNT }).map((_, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setPage(i)}
                  className={`w-1.5 h-1.5 rounded-full transition-colors ${
                    i === page ? 'bg-text-secondary' : 'bg-[#2a3447]'
                  }`}
                />
              ))}
              <button
                type="button"
                onClick={() => setPage((p) => (p + 1) % PAGE_COUNT)}
                className="text-text-disabled hover:text-text-primary transition-colors px-0.5 text-base leading-none"
              >
                ›
              </button>
            </div>
          </div>
          <p className="num text-xl font-bold text-text-primary">
            ${totalAsset.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
        </div>

        {/* 페이지 컨텐츠 — 자연 높이, 스크롤 시 총자산과 함께 올라감 */}
        <div className="px-5 py-3">
          {page === 0 && (
            <AssetPage
              orderableCash={orderableCash}
              totalCash={totalCash}
              cashRatio={cashRatio}
              stockValue={stockValue}
              stockRatio={stockRatio}
            />
          )}
          {page === 1 && <DonutPage holdings={holdings} totalCash={totalCash} />}
          {page === 2 && <DailyPnlPage holdings={holdings} />}
          {page === 3 && <CumulativePnlPage holdings={holdings} />}
        </div>
      </div>

      <StaleDataOverlay
        error={balanceFetchError}
        onRetry={onRetryBalance}
        isRetrying={isSyncing}
        lastSyncedAt={lastSyncedAt}
      />
    </div>
  )
}
