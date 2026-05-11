import type { Sp500Stock } from '../../../lib/types/stockList'
import type { PriceEntry } from '../../store/usePricesStore'

interface Props {
  stocks: Sp500Stock[]
  rankOffset: number
  prices: Record<string, PriceEntry>
  onEnter: (ticker: string) => void
  emptyMessage?: string
}

function formatMarketCap(usd: number | null): string {
  if (usd == null) return '—'
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(1)}T`
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(0)}B`
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`
  return `$${usd.toFixed(0)}`
}

function formatPrice(price: number | null): string {
  if (price == null) return '—'
  return `$${price.toFixed(2)}`
}

function formatChange(pct: number | null): { text: string; positive: boolean | null } {
  if (pct == null) return { text: '—', positive: null }
  const sign = pct >= 0 ? '+' : ''
  return { text: `${sign}${pct.toFixed(2)}%`, positive: pct >= 0 }
}

export default function StockMarketTable({ stocks, rankOffset, prices, onEnter, emptyMessage }: Props) {
  return (
    <div className="flex-1 min-h-0 overflow-auto">
      <table className="w-full text-[12px] border-separate border-spacing-0">
        <thead className="sticky top-0 z-10 bg-surface-1">
          <tr className="text-text-tertiary text-[10px] uppercase tracking-[0.1em]">
            <th className="text-right px-3.5 py-2 font-medium w-10">#</th>
            <th className="text-left px-3 py-2 font-medium w-[110px]">티커</th>
            <th className="text-left px-3 py-2 font-medium">회사명</th>
            <th className="text-left px-3 py-2 font-medium hidden xl:table-cell">섹터</th>
            <th className="text-right px-3 py-2 font-medium w-[90px]">시가총액</th>
            <th className="text-right px-3 py-2 font-medium w-[88px]">현재가</th>
            <th className="text-right px-3 py-2 font-medium w-[80px]">일일%</th>
            <th className="text-center px-3 py-2 font-medium w-[68px]"></th>
          </tr>
          <tr>
            <td colSpan={8} className="border-b border-border-subtle p-0" />
          </tr>
        </thead>
        <tbody>
          {stocks.map((stock, idx) => {
            const livePrice = prices[stock.ticker]
            const currentPrice = livePrice?.currentPrice ?? stock.currentPrice
            const changePercent =
              livePrice
                ? livePrice.previousClose > 0
                  ? ((livePrice.currentPrice - livePrice.previousClose) /
                      livePrice.previousClose) *
                    100
                  : null
                : stock.changePercent
            const change = formatChange(changePercent)

            return (
              <tr
                key={stock.ticker}
                className="group border-b border-border-subtle/50 hover:bg-surface-2 transition-colors duration-75"
              >
                <td className="num text-right text-text-disabled px-3.5 py-2.5">{rankOffset + idx + 1}</td>
                <td className="px-3 py-2.5">
                  <span className="num font-semibold text-text-primary tracking-wide">
                    {stock.ticker}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-text-secondary truncate max-w-[180px]">
                  {stock.companyName}
                </td>
                <td className="px-3 py-2.5 text-text-tertiary hidden xl:table-cell truncate max-w-[120px]">
                  {stock.sector ?? '—'}
                </td>
                <td className="num text-right px-3 py-2.5 text-text-secondary">
                  {formatMarketCap(stock.marketCapUsd)}
                </td>
                <td className="num text-right px-3 py-2.5 text-text-primary">
                  {formatPrice(currentPrice)}
                </td>
                <td
                  className={`num text-right px-3 py-2.5 font-medium ${
                    change.positive === true
                      ? 'text-buy'
                      : change.positive === false
                        ? 'text-sell'
                        : 'text-text-tertiary'
                  }`}
                >
                  {change.text}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <button
                    onClick={() => onEnter(stock.ticker)}
                    className="px-2.5 py-1 rounded text-[11px] font-semibold text-accent-400 border border-accent-500/30 hover:bg-accent-500/10 hover:border-accent-500/60 transition-colors duration-100"
                  >
                    진입
                  </button>
                </td>
              </tr>
            )
          })}
          {stocks.length === 0 && (
            <tr>
              <td colSpan={8} className="text-center text-text-disabled py-16 text-[13px]">
                {emptyMessage ?? '데이터를 불러오는 중...'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
