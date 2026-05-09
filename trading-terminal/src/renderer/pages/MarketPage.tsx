import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStockMarketStore } from '../store/useStockMarketStore'
import { usePrices } from '../hooks/usePrices'
import StockMarketTable from '../components/market/StockMarketTable'

export default function MarketPage() {
  const [searchQuery, setSearchQuery] = useState('')
  const { list, isLoaded, loadList } = useStockMarketStore()
  const { prices } = usePrices()
  const navigate = useNavigate()

  useEffect(() => {
    loadList()
  }, [loadList])

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
          {isLoaded ? `${list.length}개 종목` : '로딩 중...'}
        </div>
      </div>

      {/* 테이블 */}
      <StockMarketTable
        stocks={list}
        searchQuery={searchQuery}
        prices={prices}
        onEnter={handleEnter}
      />
    </div>
  )
}
