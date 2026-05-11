import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStockMarketStore } from '../store/useStockMarketStore'
import { usePrices } from '../hooks/usePrices'
import StockMarketTable from '../components/market/StockMarketTable'

const PAGE_SIZE = 50

export default function MarketPage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(0)
  const { list, isLoaded, loadList } = useStockMarketStore()
  const { prices } = usePrices()
  const navigate = useNavigate()

  useEffect(() => {
    loadList()
  }, [loadList])

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return list
    return list.filter(
      (s) =>
        s.ticker.toLowerCase().includes(q) ||
        s.companyName.toLowerCase().includes(q),
    )
  }, [list, searchQuery])

  // 검색어 바뀌면 첫 페이지로
  useEffect(() => {
    setPage(0)
  }, [searchQuery])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages - 1)
  const pageStocks = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)
  const rankOffset = safePage * PAGE_SIZE

  function handleEnter(ticker: string) {
    navigate(`/trading-room?ticker=${encodeURIComponent(ticker)}`)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* 헤더 */}
      <div className="shrink-0 px-5 py-3.5 border-b border-border-subtle flex items-center gap-4">
        <div>
          <div className="text-[13px] font-semibold text-text-primary">S&P 500 Market</div>
          <div className="text-[11px] text-text-tertiary mt-0.5">시가총액 순 · IEX 실시간</div>
        </div>

        {/* 검색 */}
        <div className="ml-auto relative w-[220px]">
          <svg
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary pointer-events-none"
            width="13"
            height="13"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
          >
            <circle cx="6.5" cy="6.5" r="4.5" />
            <path d="M10.5 10.5L14 14" />
          </svg>
          <input
            type="text"
            placeholder="티커 또는 회사명 검색..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 rounded-md bg-surface-2 border border-border-subtle text-[12px] text-text-primary placeholder:text-text-disabled focus:outline-none focus:border-accent-500/50 focus:bg-surface-1 transition-colors"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
                <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>

        {/* 종목 수 */}
        <div className="num text-[11px] text-text-tertiary shrink-0">
          {isLoaded ? `${filtered.length}개 종목` : '로딩 중...'}
        </div>
      </div>

      {/* 테이블 */}
      <StockMarketTable
        stocks={pageStocks}
        rankOffset={rankOffset}
        prices={prices}
        onEnter={handleEnter}
        emptyMessage={
          searchQuery.trim()
            ? `"${searchQuery.trim()}" 검색 결과가 없습니다.`
            : '데이터를 불러오는 중...'
        }
      />

      {/* 페이지네이션 */}
      {totalPages > 1 && (
        <div className="shrink-0 border-t border-border-subtle px-5 py-2.5 flex items-center justify-center gap-1">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={safePage === 0}
            className="px-2 py-1 rounded text-[11px] text-text-tertiary hover:text-text-primary hover:bg-surface-2 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            ‹
          </button>

          {Array.from({ length: totalPages }, (_, i) => (
            <button
              key={i}
              onClick={() => setPage(i)}
              className={`num w-7 h-6 rounded text-[11px] font-medium transition-colors ${
                i === safePage
                  ? 'bg-accent-500/15 text-accent-400 border border-accent-500/30'
                  : 'text-text-tertiary hover:text-text-primary hover:bg-surface-2'
              }`}
            >
              {i + 1}
            </button>
          ))}

          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={safePage === totalPages - 1}
            className="px-2 py-1 rounded text-[11px] text-text-tertiary hover:text-text-primary hover:bg-surface-2 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            ›
          </button>
        </div>
      )}
    </div>
  )
}
