import type { Sp500Stock } from '../../../lib/types/stockList'
import type { PriceEntry } from '../../store/usePricesStore'
import {
  formatCallDate,
  formatChange,
  formatMarketCap,
  formatPrice,
  resolveQuote,
  type StockFilterSets,
} from '../../lib/stocksScreen'

interface Props {
  stocks: Sp500Stock[]
  rankOffset: number
  prices: Record<string, PriceEntry>
  marks: StockFilterSets
  onPick: (ticker: string) => void
}

const CHANGE_COLOR = { up: 'text-up', down: 'text-down', flat: 'text-ink-3' } as const

/**
 * 종목 표. 행 어디를 눌러도 종목 브리핑이 열린다.
 * 키보드 · 스크린리더용으로 티커 칸에 실제 버튼을 두고, 버튼의 클릭이 행으로 올라와 같은 경로로 연다.
 * 관심 · 보유 · 이번 주 콜은 회사명 옆 무채색 표시로 둔다 — 색은 가격 등락에만 쓴다.
 */
export default function StockMarketTable({ stocks, rankOffset, prices, marks, onPick }: Props) {
  return (
    <table className="w-full text-[13.5px] border-separate border-spacing-0">
      <thead>
        <tr className="text-ink-3 text-[12px] font-medium">
          <th className="text-right pl-5 pr-3 py-3 font-medium w-12">#</th>
          <th className="text-left px-3 py-3 font-medium w-[96px]">티커</th>
          <th className="text-left px-3 py-3 font-medium">회사명</th>
          <th className="text-left px-3 py-3 font-medium hidden xl:table-cell w-[200px]">섹터</th>
          <th className="text-right px-3 py-3 font-medium w-[96px]">시가총액</th>
          <th className="text-right px-3 py-3 font-medium w-[104px]">현재가</th>
          <th className="text-right pl-3 pr-5 py-3 font-medium w-[112px]">일일</th>
        </tr>
      </thead>
      <tbody>
        {stocks.map((stock, idx) => {
          const { price, changePct } = resolveQuote(stock, prices[stock.ticker])
          const change = formatChange(changePct)
          const callAt = marks.week.get(stock.ticker)
          const watched = marks.watch.has(stock.ticker)
          const held = marks.held.has(stock.ticker)

          return (
            <tr
              key={stock.ticker}
              onClick={() => onPick(stock.ticker)}
              className="cursor-pointer transition-colors duration-100 hover:bg-white/[0.05] focus-within:bg-white/[0.05]"
            >
              <td className="num text-right text-[12px] text-ink-3 pl-5 pr-3 py-2.5 border-t border-white/[0.06]">
                {rankOffset + idx + 1}
              </td>
              <td className="px-3 py-2.5 border-t border-white/[0.06]">
                <button
                  type="button"
                  aria-label={`${stock.ticker} 종목 브리핑 열기`}
                  className="num font-semibold text-ink-1 rounded-md -mx-1 px-1
                             focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-hi"
                >
                  {stock.ticker}
                </button>
              </td>
              <td className="px-3 py-2.5 border-t border-white/[0.06] max-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-ink-2 truncate">{stock.companyName}</span>
                  {watched && <WatchStar />}
                  {held && <Mark strong>보유</Mark>}
                  {callAt !== undefined && <Mark>콜 {formatCallDate(callAt)}</Mark>}
                </div>
              </td>
              <td className="px-3 py-2.5 text-ink-3 hidden xl:table-cell truncate max-w-[200px] border-t border-white/[0.06]">
                {stock.sector ?? '—'}
              </td>
              <td className="tabular-nums text-right px-3 py-2.5 text-ink-2 border-t border-white/[0.06]">
                {formatMarketCap(stock.marketCapUsd)}
              </td>
              <td className="tabular-nums text-right px-3 py-2.5 text-ink-1 border-t border-white/[0.06]">
                {formatPrice(price)}
              </td>
              <td
                className={`tabular-nums text-right pl-3 pr-5 py-2.5 font-medium border-t border-white/[0.06] ${
                  change.dir ? CHANGE_COLOR[change.dir] : 'text-ink-3'
                }`}
              >
                {change.text}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function WatchStar() {
  return (
    <span className="shrink-0 text-ink-2" title="관심 종목">
      <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
        <path d="M8 1.6l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.4l-3.8 2 .7-4.3-3.1-3 4.3-.6z" />
      </svg>
      <span className="sr-only">관심</span>
    </span>
  )
}

function Mark({ children, strong = false }: { children: React.ReactNode; strong?: boolean }) {
  return (
    <span
      className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[11.5px] font-semibold border tabular-nums
                  ${strong ? 'text-ink-1 border-white/25' : 'text-ink-3 border-white/10'}`}
    >
      {children}
    </span>
  )
}
