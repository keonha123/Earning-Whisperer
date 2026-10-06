import { useEffect, useMemo, useRef, useState } from 'react'
import { useStockMarketStore } from '../store/useStockMarketStore'
import { usePortfolioStore } from '../store/usePortfolioStore'
import { useDrawerStore } from '../store/useDrawerStore'
import { usePrices } from '../hooks/usePrices'
import { useWatchlist } from '../hooks/useWatchlist'
import { useEarningsTimeline } from '../hooks/useEarningsTimeline'
import StockMarketTable from '../components/market/StockMarketTable'
import SegmentedControl, { type SegmentItem } from '../components/common/SegmentedControl'
import Pagination from '../components/common/Pagination'
import { EmptyState, LoadingBlock } from '../components/common/StateView'
import {
  emptyFilterMessage,
  filterStocks,
  weeklyCallTimes,
  type StockFilter,
  type StockFilterSets,
} from '../lib/stocksScreen'
import type { IpcErrorCode } from '../../lib/types/ipcError'

const PAGE_SIZE = 50

const FILTER_LABELS: Record<StockFilter, string> = {
  all: '전체',
  watch: '관심',
  held: '보유',
  week: '이번 주 콜',
}

const FILTERS: StockFilter[] = ['all', 'watch', 'held', 'week']

/**
 * 종목 — S&P 500 목록에서 종목을 찾는 화면 (docs/design/screens/stocks.md).
 *
 * 행을 누르면 종목 브리핑(오른쪽 패널)이 열리고, 콜 화면은 브리핑의 `콜 화면 열기` 로 들어간다.
 * 관심 · 보유 · 이번 주 콜 필터는 S&P 500 목록 안에서 거른다.
 */
export default function MarketPage() {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StockFilter>('all')
  const [page, setPage] = useState(0)
  const topRef = useRef<HTMLDivElement>(null)

  const list = useStockMarketStore((s) => s.list)
  const isLoaded = useStockMarketStore((s) => s.isLoaded)
  const error = useStockMarketStore((s) => s.error)
  const loadList = useStockMarketStore((s) => s.loadList)
  const invalidate = useStockMarketStore((s) => s.invalidate)
  const holdings = usePortfolioStore((s) => s.holdings)
  const openDrawer = useDrawerStore((s) => s.open)
  const { prices } = usePrices()
  const { items: watchlist } = useWatchlist()
  const { data: timeline, status: timelineStatus, retry: retryTimeline } = useEarningsTimeline()

  useEffect(() => {
    void loadList()
  }, [loadList])

  const retryList = () => {
    invalidate()
    void loadList()
  }

  const marks = useMemo<StockFilterSets>(
    () => ({
      watch: new Set(watchlist.map((w) => w.ticker)),
      held: new Set(holdings.filter((h) => h.qty > 0).map((h) => h.ticker)),
      week: weeklyCallTimes(timeline),
    }),
    [watchlist, holdings, timeline],
  )

  const filtered = useMemo(() => filterStocks(list, filter, query, marks), [list, filter, query, marks])

  // 칸마다 S&P 500 안에서 해당하는 종목 수를 단다. 일정을 아직 모르면 이번 주 콜 칸은 비워 둔다.
  const segments = useMemo<SegmentItem<StockFilter>[]>(
    () =>
      FILTERS.map((f) => ({
        id: f,
        label: FILTER_LABELS[f],
        count:
          !isLoaded || error || (f === 'week' && timelineStatus !== 'ready')
            ? undefined
            : filterStocks(list, f, '', marks).length,
      })),
    [list, marks, isLoaded, error, timelineStatus],
  )

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages - 1)
  const pageStocks = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)

  // 필터 · 검색어가 바뀌면 첫 페이지로. 이벤트에서 바로 바꿔 이전 페이지가 한 번 그려지지 않게 한다.
  const changeFilter = (f: StockFilter) => {
    setFilter(f)
    setPage(0)
  }
  const changeQuery = (q: string) => {
    setQuery(q)
    setPage(0)
  }

  const changePage = (p: number) => {
    setPage(p)
    topRef.current?.scrollIntoView({ block: 'start' })
  }

  const listFailed = isLoaded && error !== null && list.length === 0
  const ready = isLoaded && !listFailed

  return (
    <div ref={topRef} className="flex flex-col gap-6 max-w-[1320px]">
      <header className="flex items-end justify-between gap-4 pt-2">
        <div>
          <h1 className="text-[24px] font-bold tracking-[-0.02em] text-ink-1">종목</h1>
          <p className="mt-1 text-[12.5px] text-ink-3">S&amp;P 500 · 시가총액 순</p>
        </div>
        {ready && <span className="text-[12.5px] text-ink-3 tabular-nums">{filtered.length}개 종목</span>}
      </header>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <SegmentedControl items={segments} activeId={filter} onChange={changeFilter} />
        <SearchField value={query} onChange={changeQuery} />
      </div>

      <section className="glass glass-flat rim rounded-[28px] flex flex-col" aria-label="종목 목록">
        {!isLoaded || (filter === 'week' && timelineStatus === 'loading') ? (
          <LoadingBlock lines={10} lineHeight={20} className="p-5" />
        ) : listFailed ? (
          <FailureState
            message="종목 목록을 불러오지 못했습니다."
            reason={error && failureReason(error)}
            // 로그인 만료는 다시 시도해도 같은 실패라 버튼을 두지 않는다
            onRetry={error === 'AUTH_REQUIRED' || error === 'AUTH_EXPIRED' ? undefined : retryList}
          />
        ) : filter === 'week' && timelineStatus === 'error' ? (
          <FailureState message="실적 콜 일정을 불러오지 못했습니다." onRetry={retryTimeline} />
        ) : filtered.length === 0 ? (
          query.trim() ? (
            <EmptyState
              message={`${filter === 'all' ? '' : `${FILTER_LABELS[filter]} 종목 중 `}"${query.trim()}" 검색 결과가 없습니다.`}
              action={
                <button type="button" className="gbtn rim gbtn-sm" onClick={() => changeQuery('')}>
                  검색어 지우기
                </button>
              }
            />
          ) : (
            <EmptyState message={emptyFilterMessage(filter)} />
          )
        ) : (
          <>
            <StockMarketTable
              stocks={pageStocks}
              rankOffset={safePage * PAGE_SIZE}
              prices={prices}
              marks={marks}
              onPick={openDrawer}
            />
            <Pagination page={safePage} totalPages={totalPages} onPageChange={changePage} />
          </>
        )}
      </section>
    </div>
  )
}

function SearchField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative w-[280px]">
      <svg
        className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none"
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        aria-hidden
      >
        <circle cx="6.5" cy="6.5" r="4.5" />
        <path d="M10.5 10.5L14 14" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && value) {
            e.stopPropagation()
            onChange('')
          }
        }}
        placeholder="티커 또는 회사명"
        aria-label="종목 검색"
        className="input-base !text-[13.5px] !py-2 pl-10 pr-9"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 rounded-full text-ink-3 hover:text-ink-1"
          aria-label="검색어 지우기"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden>
            <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      )}
    </div>
  )
}

/** 오류 코드 → 실패 사유 한 줄. */
function failureReason(code: IpcErrorCode): string {
  switch (code) {
    case 'NETWORK':
      return '서버에 연결하지 못했습니다. 네트워크 연결을 확인해 주세요.'
    case 'BACKEND_5XX':
      return '서버가 응답하지 않습니다.'
    case 'AUTH_REQUIRED':
    case 'AUTH_EXPIRED':
      return '로그인이 만료되었습니다. 다시 로그인해 주세요.'
    default:
      return '잠시 뒤 다시 시도해 주세요.'
  }
}

function FailureState({
  message,
  reason,
  onRetry,
}: {
  message: string
  reason?: string | null
  onRetry?: () => void
}) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <p className="text-danger text-[13px] font-semibold">{message}</p>
      {reason && <p className="text-ink-3 text-[12px] max-w-[48ch] break-words">{reason}</p>}
      {onRetry && (
        <button type="button" className="gbtn rim gbtn-sm" onClick={onRetry}>
          다시 시도
        </button>
      )}
    </div>
  )
}
