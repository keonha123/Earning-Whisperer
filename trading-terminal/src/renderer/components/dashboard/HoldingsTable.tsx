import { useMemo, useState } from 'react'
import Tabs from '../common/Tabs'
import CompanyLogo from '../common/CompanyLogo'
import StaleDataOverlay from '../common/StaleDataOverlay'
import type { HoldingMockRow, WatchlistMockRow } from '../../fixtures/holdings.dev-mock'
import type { IpcError } from '../../../lib/types/ipcError'

export interface HoldingsTableRow {
  ticker: string
  name: string
  currentPrice: number
  dailyChangePercent: number
  /** 보유 탭에서만 의미. 관심종목은 undefined. */
  pnlPercent?: number
  /** 어닝 배지: 'LIVE' / epoch seconds / null */
  earningsBadge?: 'LIVE' | number | null
  logoBg?: string
  logoFg?: string
  logoLabel?: string
}

interface HoldingsTableProps {
  holdings: HoldingsTableRow[]
  watchlist: HoldingsTableRow[]
  /** 행 클릭 시 ticker 전달 (CompanyDrawer 트리거). */
  onRowClick?: (ticker: string) => void
  /** 우측 상단 메타 라벨 (예: "평가 $4,345.67"). */
  rightMeta?: string
  className?: string
  /**
   * F-2: 마지막 잔고 조회 실패 시 IpcError. null 이면 overlay 숨김.
   * 보유 탭의 stale 데이터 오인 차단용. 관심종목은 watchlist API 별도이므로
   * 본 prop 영향 받지 않지만, overlay 가 카드 전체를 덮으므로 사용자 시점에서는
   * 두 탭 모두 차단됨 (의도된 동작 — 카드 단위 신뢰성 표시).
   */
  balanceFetchError?: IpcError | null
  /** F-2: overlay 의 "다시 조회" 버튼 클릭 핸들러. */
  onRetryBalance?: () => void
  /** F-2: 재시도 진행 중. */
  isSyncing?: boolean
  /** F-2: 마지막 성공 동기화 시각 (epoch sec). */
  lastSyncedAt?: number | null
}

type TabId = 'holdings' | 'watchlist'

/**
 * HoldingsTable — 보유/관심 탭 테이블 (5컬럼: 종목/현재가/일간%/평가%/어닝).
 *
 * 디자인 매칭: DashboardPage.html `.row3 > .card` 좌측 영역.
 *  - 헤더: Tabs (underline 변형) + 우측 메타 라벨.
 *  - 행 hover: 좌측 2px emerald 바 + surface-2 배경.
 *  - 회사 로고 색은 prop 으로 (logoBg/logoFg).
 *
 * 클릭: 행 전체가 onRowClick(ticker) 트리거.
 */
export default function HoldingsTable({
  holdings,
  watchlist,
  onRowClick,
  rightMeta,
  className = '',
  balanceFetchError = null,
  onRetryBalance,
  isSyncing = false,
  lastSyncedAt = null,
}: HoldingsTableProps) {
  const [tab, setTab] = useState<TabId>('holdings')

  const rows = tab === 'holdings' ? holdings : watchlist

  const tabItems = useMemo(
    () => [
      { id: 'holdings', label: '보유종목', count: holdings.length },
      { id: 'watchlist', label: '관심종목', count: watchlist.length },
    ],
    [holdings.length, watchlist.length],
  )

  return (
    // F-2: overlay 가 absolute 로 깔리려면 컨테이너 relative.
    <section
      className={`relative rounded-lg bg-surface-1 border border-border-subtle flex flex-col min-h-0 overflow-hidden ${className}`}
    >
      <div className="h-[38px] pl-2 pr-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <Tabs
          items={tabItems}
          activeId={tab}
          onChange={(id) => setTab(id as TabId)}
        />
        {rightMeta && (
          <span className="num text-[11px] text-text-tertiary">{rightMeta}</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <table className="w-full table-fixed">
          <caption className="sr-only">
            {tab === 'holdings' ? '보유 종목 목록' : '관심 종목 목록'}
          </caption>
          <colgroup>
            <col style={{ width: '36%' }} />
            <col style={{ width: '18%' }} />
            <col style={{ width: '14%' }} />
            <col style={{ width: '14%' }} />
            <col style={{ width: '18%' }} />
          </colgroup>
          <thead>
            <tr>
              <Th>종목</Th>
              <Th align="right">현재가</Th>
              <Th align="right">일간%</Th>
              <Th align="right">{tab === 'holdings' ? '평가%' : '관심'}</Th>
              <Th align="right">어닝</Th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-text-disabled text-xs">
                  {tab === 'holdings' ? '보유 종목이 없습니다' : '관심 종목이 없습니다'}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <Row key={r.ticker} row={r} tab={tab} onClick={onRowClick} />
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* F-2: stale 데이터 overlay — error 가 null 일 때 컴포넌트 자체가 null 반환. */}
      <StaleDataOverlay
        error={balanceFetchError}
        onRetry={onRetryBalance}
        isRetrying={isSyncing}
        lastSyncedAt={lastSyncedAt}
      />
    </section>
  )
}

function Th({
  children,
  align,
}: {
  children: React.ReactNode
  align?: 'right'
}) {
  return (
    <th
      className={`text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.12em]
                  bg-surface-1 border-b border-border-subtle sticky top-0
                  px-3.5 py-2 ${align === 'right' ? 'text-right' : 'text-left'}`}
    >
      {children}
    </th>
  )
}

function Row({
  row,
  tab,
  onClick,
}: {
  row: HoldingsTableRow
  tab: TabId
  onClick?: (t: string) => void
}) {
  const dailyCls =
    row.dailyChangePercent > 0
      ? 'text-buy'
      : row.dailyChangePercent < 0
        ? 'text-sell'
        : 'text-text-tertiary'
  const pnl = row.pnlPercent
  const pnlCls =
    pnl == null
      ? 'text-text-tertiary'
      : pnl > 0
        ? 'text-buy'
        : pnl < 0
          ? 'text-sell'
          : 'text-text-tertiary'

  return (
    <tr
      onClick={() => onClick?.(row.ticker)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.(row.ticker)
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={`${row.ticker} ${row.name} 상세 보기`}
      className="group h-[38px] border-b border-border-subtle relative cursor-pointer
                 hover:bg-surface-2 focus:outline-none focus:bg-surface-2"
    >
      <td className="px-3.5 align-middle relative">
        <span
          aria-hidden="true"
          className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent-500
                     opacity-0 group-hover:opacity-100 group-focus:opacity-100"
        />
        <div className="flex items-center gap-2">
          <CompanyLogo
            ticker={row.ticker}
            label={row.logoLabel}
            bg={row.logoBg}
            fg={row.logoFg}
          />
          <div className="min-w-0">
            <div className="num text-[12px] font-semibold text-text-primary">{row.ticker}</div>
            <div className="text-[10px] text-text-tertiary truncate">{row.name}</div>
          </div>
        </div>
      </td>
      <td className="px-3.5 num text-right text-text-primary tabular-nums text-[12px]">
        ${row.currentPrice.toFixed(2)}
      </td>
      <td className={`px-3.5 num text-right tabular-nums text-[12px] ${dailyCls}`}>
        {row.dailyChangePercent > 0 ? '+' : ''}
        {row.dailyChangePercent.toFixed(2)}%
      </td>
      <td className={`px-3.5 num text-right tabular-nums text-[12px] ${pnlCls}`}>
        {pnl != null
          ? `${pnl > 0 ? '+' : ''}${pnl.toFixed(2)}%`
          : tab === 'watchlist'
            ? '관심'
            : '—'}
      </td>
      <td className="px-3.5 num text-right">
        <EarningsBadge value={row.earningsBadge ?? null} />
      </td>
    </tr>
  )
}

function EarningsBadge({ value }: { value: 'LIVE' | number | null | undefined }) {
  if (!value && value !== 0) return <span className="text-text-disabled text-[10px]">—</span>

  if (value === 'LIVE') {
    return (
      <span className="num text-[10px] px-1.5 py-0.5 rounded-[3px] font-semibold tracking-[0.06em] inline-flex items-center gap-1 bg-sell/10 text-sell border border-sell/30">
        <span className="w-1 h-1 rounded-full bg-sell" />
        LIVE
      </span>
    )
  }

  // epoch seconds → KST 날짜 라벨 (M/D)
  const kstMs = value * 1000 + 9 * 3600 * 1000
  const d = new Date(kstMs)
  const label = `${d.getUTCMonth() + 1}/${d.getUTCDate()}`

  // 긴급도: 오늘 기준 남은 일수
  const daysLeft = Math.ceil((value - Date.now() / 1000) / 86400)
  const cls =
    daysLeft <= 3
      ? 'bg-sell/10 text-[#fca5a5] border border-sell/30'
      : daysLeft <= 14
        ? 'bg-warning/10 text-[#fdba74] border border-warning/30'
        : 'bg-surface-3 text-text-tertiary border border-border-subtle'

  return (
    <span className={`num text-[10px] px-1.5 py-0.5 rounded-[3px] font-semibold tracking-[0.06em] inline-flex items-center gap-1 ${cls}`}>
      {label}
    </span>
  )
}
