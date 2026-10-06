import { useEffect, useMemo, useRef, useState } from 'react'
import type { HistoryRow, HistoryStatus } from '../types/tradeHistory'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import Pagination from '../components/common/Pagination'
import SegmentedControl from '../components/common/SegmentedControl'
import Dropdown from '../components/common/Dropdown'
import Modal from '../components/common/Modal'
import { EmptyState } from '../components/common/StateView'
import { showIpcErrorToast } from '../components/common/Toast'
import { showComingSoon } from '../components/call/comingSoon'
import { isIpcError } from '../../lib/types/ipcError'
import { useConnectionStore } from '../store/useConnectionStore'
import { useUserStore } from '../store/useUserStore'
import { parseServerTime } from '../lib/serverTime'

/**
 * HistoryPage — 포트폴리오의 거래 내역 탭 (docs/design/screens/portfolio.md).
 *
 *  - Row 1: 요약 칩 (이번 페이지 건수 · 매수 · 매도) + 마지막 업데이트 + 새로고침.
 *  - Row 2 (필터 바): 세그먼트(전체/매수/매도/실패) + 드롭다운 2개 (기간/종목)
 *    + 검색 + CSV 내보내기.
 *  - Row 3 (표): 8컬럼. 정렬 표시는 자리만 두고 누르면 "준비 중" 을 알린다.
 *  - Footer: 총 N건 / Pagination / 페이지당 행 수.
 *  - 목록 조회가 실패하면 받아 둔 목록을 남기고 실패 띠를 띄운다. 받아 둔 목록이 없으면 실패 문구만 둔다.
 *
 * Trade 인터페이스 정책:
 *  - 기존 Trade 타입 (id, ticker, side, executedQty, executedPrice, status, createdAt)
 *    그대로 유지.
 *
 * 보안 메모:
 *  - CSV 내보내기는 IPC 핸들러 (`SHELL_SAVE_CSV`) 경유로 저장한다. 저장 위치와 파일명
 *    검증은 main 측이 맡는다.
 *  - 검색/필터는 클라이언트 측 필터링만 (백엔드 쿼리 확장은 별도 PR).
 */

interface Trade {
  id: number
  ticker: string
  side: 'BUY' | 'SELL'
  orderType?: 'MARKET' | 'LIMIT' | null
  orderQty?: number | null
  price?: number | null
  executedQty: number
  executedPrice: number | null
  status: string
  createdAt: string // ISO 8601
}

const PAGE_SIZE_OPTIONS = ['12', '20', '50'] as const
type PageSizeOption = (typeof PAGE_SIZE_OPTIONS)[number]

type SegmentId = 'all' | 'buy' | 'sell' | 'failed'
type PeriodId = '7d' | '30d' | '90d' | 'all'

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [totalPages, setTotalPages] = useState(0)

  const [segment, setSegment] = useState<SegmentId>('all')
  const [period, setPeriod] = useState<PeriodId>('7d')
  const [tickerFilter, setTickerFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [pageSize, setPageSize] = useState<PageSizeOption>('12')
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null)
  /** 마지막 목록 조회가 실패했는지. 성공하면 풀린다 — "불러오는 중" 과 "실패" 를 구분하기 위해 따로 든다. */
  const [loadFailed, setLoadFailed] = useState(false)
  const [detailRow, setDetailRow] = useState<HistoryRow | null>(null)

  const navigate = useNavigate()
  const setAuthenticated = useConnectionStore((s) => s.setAuthenticated)
  const clearUser = useUserStore((s) => s.clear)
  /** 체결 동기화 중복 실행 가드. */
  const reconcilingRef = useRef(false)
  /** 목록 요청 세대 — 늦게 도착한 옛 응답이 최신 목록을 덮지 않도록. */
  const loadGenerationRef = useRef(0)

  useEffect(() => {
    setPage(0)
    // 화면 진입/기간 변경 시 미체결 주문을 한 번 확인한 뒤 목록을 읽는다.
    reconcileThenLoad(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period])

  /**
   * @param p          요청할 페이지 번호 (0-base).
   * @param sizeOverride  page size 변경과 동시에 호출될 때 신규 size 전달용.
   *                      React state setter (setPageSize) 는 비동기 업데이트라
   *                      같은 tick 의 closure 가 옛 pageSize 를 캡처한다.
   *                      sizeOverride 가 주어지면 우선 적용한다.
   */
  function periodToStartDate(p: PeriodId): string | undefined {
    if (p === 'all') return undefined
    const days = p === '7d' ? 7 : p === '30d' ? 30 : 90
    const d = new Date()
    d.setDate(d.getDate() - days)
    // ISO 8601 — 백엔드 @DateTimeFormat(iso = ISO.DATE_TIME) 파싱 형식
    return d.toISOString().replace('Z', '')
  }

  /**
   * 미체결(PENDING) 주문의 체결 여부를 KIS 에 재조회해 백엔드 상태를 맞춘 뒤 목록을 다시 읽는다.
   *
   * 주문 직후 1회 조회로 확정하는 구조라 그 순간 체결이 반영되지 않은 주문은 PENDING 으로
   * 남고 이후 아무도 확인하지 않았다. 주기 폴링을 두는 대신(KIS 초당 호출 제한) 이 화면에
   * 들어올 때 1회와 새로고침 때만 확인한다. 실패는 조용히 넘긴다 — 목록 조회 자체는 되어야
   * 하고, 동기화는 부가 작업이다.
   */
  async function reconcileThenLoad(p: number) {
    // 새로고침 연타나 mount effect 와의 중첩을 막는다. 중복 실행은 KIS 조회를 낭비하고,
    // loadTrades 가 요청 순서와 무관하게 setTrades 하므로 옛 응답이 최신을 덮을 수 있다.
    if (reconcilingRef.current) return
    reconcilingRef.current = true
    setLoading(true)
    try {
      await ipc.invoke<{ checked: number; reconciled: number; failed: number }>(
        IPC_CHANNELS.TRADES_RECONCILE_PENDING,
      )
    } catch (e) {
      // 동기화는 부가 작업이다 — 실패해도 목록 조회는 그대로 진행한다.
      console.warn('체결 상태 동기화 실패:', e)
    }
    try {
      // setLoading(false) 를 여기서 하지 않는다. 중간에 false 프레임이 렌더되면
      // 갱신 전 데이터가 "로딩 아님" 으로 잠깐 보인다.
      await loadTrades(p, undefined, { keepLoading: true })
    } finally {
      setLoading(false)
      reconcilingRef.current = false
    }
  }

  async function loadTrades(
    p: number,
    sizeOverride?: number,
    opts?: { keepLoading?: boolean },
  ) {
    const generation = ++loadGenerationRef.current
    setLoading(true)
    try {
      const size = sizeOverride ?? Number(pageSize)
      const startDate = periodToStartDate(period)
      const data = await ipc.invoke<{ content: Trade[]; totalPages: number }>(
        IPC_CHANNELS.TRADES_GET,
        { page: p, size, ...(startDate ? { startDate } : {}) },
      )
      // 더 새로운 요청이 이미 떠 있으면 이 응답은 버린다.
      if (generation !== loadGenerationRef.current) return
      setTrades(data.content ?? [])
      setTotalPages(data.totalPages ?? 0)
      setLastUpdatedAt(Date.now())
      setLoadFailed(false)
    } catch (e: unknown) {
      console.error('거래 내역 조회 실패:', e)
      // 더 새로운 요청이 떠 있으면 그 결과가 상태를 정한다
      if (generation === loadGenerationRef.current) setLoadFailed(true)
      showIpcErrorToast(e, {
        onNavigate:
          isIpcError(e) && e.code === 'AUTH_EXPIRED'
            ? () => {
                setAuthenticated(false)
                clearUser()
                navigate('/auth')
              }
            : undefined,
      })
    } finally {
      // reconcileThenLoad 가 감싸는 경우에는 그쪽에서 내린다 — 중간에 로딩이 풀려
      // 옛 데이터가 노출되는 프레임을 막기 위해.
      if (!opts?.keepLoading) setLoading(false)
    }
  }

  function handlePageChange(p: number) {
    setPage(p)
    loadTrades(p)
  }

  async function handleCsvExport() {
    const rows = filtered
    if (rows.length === 0) return
    const headers = ['일시', '종목', '방향', '주문수량', '체결수량', '주문가', '체결가', '체결금액', '상태']
    const lines = [
      headers.join(','),
      ...rows.map((r) =>
        [
          formatCsvDateTime(r.createdAt),
          r.ticker,
          r.side,
          r.orderQty ?? '',
          r.executedQty,
          r.price ?? '',
          r.executedPrice ?? '',
          r.amount ?? '',
          r.status,
        ].join(','),
      ),
    ]
    const csvContent = lines.join('\n')
    const periodLabel = period === 'all' ? 'all' : period
    const filename = `trades_${periodLabel}_${new Date().toISOString().slice(0, 10)}`
    await ipc.invoke(IPC_CHANNELS.SHELL_SAVE_CSV, { filename, csvContent })
  }

  // 표시 행: 백엔드가 준 체결 내역만 쓴다.
  // DEV 에서 거래가 없으면 목업 내역을 대신 띄우고 있었는데, 그러면 체결이 없는 것과
  // 연동이 끊긴 것을 화면에서 구별할 수 없다.
  const displayRows: HistoryRow[] = useMemo(() => {
    return trades.map((t) => ({
      id: t.id,
      ticker: t.ticker,
      side: t.side,
      orderType: t.orderType ?? null,
      orderQty: t.orderQty ?? null,
      price: t.price ?? null,
      executedQty: t.executedQty,
      executedPrice: t.executedPrice,
      amount:
        t.executedPrice != null ? t.executedPrice * t.executedQty : null,
      status: (t.status === 'EXECUTED' || t.status === 'PENDING'
        ? t.status
        : 'FAILED') as HistoryStatus,
      createdAt: t.createdAt,
    }))
  }, [trades])

  // 클라이언트 필터링 (백엔드 쿼리 확장은 별도 PR)
  const filtered = useMemo(() => {
    return displayRows.filter((r) => {
      if (segment === 'buy' && r.side !== 'BUY') return false
      if (segment === 'sell' && r.side !== 'SELL') return false
      if (segment === 'failed' && r.status !== 'FAILED') return false
      if (tickerFilter !== 'all' && r.ticker !== tickerFilter) return false
      if (search.trim()) {
        const q = search.trim().toUpperCase()
        if (!r.ticker.includes(q)) return false
      }
      return true
    })
  }, [displayRows, segment, tickerFilter, search])

  // 요약: 페이지 단위 집계. 거래가 없으면 0 이 맞다.
  const summary = useMemo(() => {
    return {
      todayCount: trades.length,
      buyCount: trades.filter((t) => t.side === 'BUY').length,
      sellCount: trades.filter((t) => t.side === 'SELL').length,
      totalCount: trades.length,
    }
  }, [trades])

  // 종목 드롭다운 옵션 (현재 화면의 ticker 들에서 추출)
  const tickerOptions = useMemo(() => {
    const set = new Set(displayRows.map((r) => r.ticker))
    return [
      { value: 'all', label: '전체' },
      ...Array.from(set).map((t) => ({ value: t, label: t })),
    ]
  }, [displayRows])

  const reload = () => reconcileThenLoad(page)
  const hasRows = displayRows.length > 0

  return (
    <div className="flex flex-col gap-4 h-full min-h-0">
      {/* Row 1: 요약 + 새로고침 */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex gap-2">
          <SummaryChip>
            오늘 <span><b className="tabular-nums text-ink-1 font-semibold">{summary.todayCount}</b>건</span>
          </SummaryChip>
          <SummaryChip>
            <span className="text-up">▲ 매수</span>{' '}
            <span><b className="tabular-nums text-up font-semibold">{summary.buyCount}</b>건</span>
          </SummaryChip>
          <SummaryChip>
            <span className="text-down">▼ 매도</span>{' '}
            <span><b className="tabular-nums text-down font-semibold">{summary.sellCount}</b>건</span>
          </SummaryChip>
        </div>
        <div className="ml-auto flex items-center gap-3 text-[12.5px] text-ink-3 whitespace-nowrap">
          {lastUpdatedAt && (
            <span>
              마지막 업데이트 <span className="num">{formatDateTime(lastUpdatedAt)}</span>
            </span>
          )}
          <button type="button" onClick={reload} disabled={loading} className="gbtn rim gbtn-sm">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M2 6a4 4 0 017-2.5M10 6a4 4 0 01-7 2.5M9 2v2h-2M3 10V8h2" />
            </svg>
            새로고침
          </button>
        </div>
      </div>

      {/* Row 2: 필터 바 */}
      <div className="shrink-0 flex items-center gap-3 flex-wrap">
        <SegmentedControl<SegmentId>
          items={[
            { id: 'all', label: '전체' },
            { id: 'buy', label: '매수' },
            { id: 'sell', label: '매도' },
            { id: 'failed', label: '실패만' },
          ]}
          activeId={segment}
          onChange={setSegment}
        />
        <Dropdown<PeriodId>
          prefix="기간:"
          value={period}
          onChange={setPeriod}
          options={[
            { value: '7d', label: '최근 7일' },
            { value: '30d', label: '최근 30일' },
            { value: '90d', label: '최근 90일' },
            { value: 'all', label: '전체' },
          ]}
          ariaLabel="기간 필터"
        />
        <Dropdown
          prefix="종목:"
          value={tickerFilter}
          onChange={setTickerFilter}
          options={tickerOptions}
          ariaLabel="종목 필터"
        />

        <label className="ml-auto glass rim flex items-center gap-2 rounded-full px-4 h-9 w-[220px]
                          focus-within:outline focus-within:outline-2 focus-within:outline-gold-hi focus-within:outline-offset-[3px]">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-ink-3" aria-hidden="true">
            <circle cx="5" cy="5" r="3.5" />
            <path d="M8 8l2.5 2.5" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="티커 검색"
            aria-label="티커 검색"
            className="flex-1 min-w-0 bg-transparent text-[13px] text-ink-1 placeholder:text-ink-3 outline-none"
          />
        </label>

        <button type="button" onClick={handleCsvExport} disabled={filtered.length === 0} className="gbtn rim gbtn-sm">
          CSV 내보내기
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M5 1v6M2 5l3 3 3-3M1.5 9h7" />
          </svg>
        </button>
      </div>

      {/* 실패: 받아 둔 목록이 있으면 남기고 위에 알린다 */}
      {loadFailed && hasRows && !loading && (
        <div role="alert" className="shrink-0 flex items-center gap-3 rounded-full glass rim on-glass px-5 h-11 text-[13px]">
          <span className="text-danger font-semibold">조회 실패</span>
          <span className="text-ink-2">
            거래 내역을 새로 불러오지 못했습니다. 아래는 마지막으로 받은 목록입니다
            {lastUpdatedAt && <> · <span className="num">{formatDateTime(lastUpdatedAt)}</span></>}
          </span>
          <button type="button" onClick={reload} className="gbtn rim gbtn-sm ml-auto">
            다시 시도
          </button>
        </div>
      )}

      {/* Row 3: 표 */}
      <div className="frost rim rounded-[28px] overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="overflow-y-auto flex-1 min-h-0 px-3 pt-2">
          <table className="w-full table-fixed border-separate border-spacing-0">
            <caption className="sr-only">거래 내역</caption>
            <colgroup>
              <col style={{ width: 140 }} />
              <col style={{ width: 84 }} />
              <col style={{ width: 76 }} />
              <col style={{ width: 72 }} />
              <col style={{ width: 96 }} />
              <col style={{ width: 112 }} />
              <col style={{ width: 80 }} />
              <col style={{ width: 64 }} />
            </colgroup>
            <thead>
              <tr>
                <Th>일시 <SortPlaceholder /></Th>
                <Th>종목</Th>
                <Th>방향</Th>
                <Th align="right">체결수량</Th>
                <Th align="right">체결가 <SortPlaceholder /></Th>
                <Th align="right">체결금액 <SortPlaceholder /></Th>
                <Th>상태</Th>
                <Th align="center">상세</Th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} />)
              ) : loadFailed && !hasRows ? (
                <tr>
                  <td colSpan={8}>
                    <EmptyState
                      message="거래 내역을 불러오지 못했습니다."
                      action={
                        <button type="button" onClick={reload} className="gbtn rim gbtn-sm">
                          다시 시도
                        </button>
                      }
                    />
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <EmptyState
                      message={
                        hasRows
                          ? '조건에 맞는 거래 내역이 없습니다.'
                          : '이 기간에 거래 내역이 없습니다.'
                      }
                    />
                  </td>
                </tr>
              ) : (
                filtered.map((r) => <Row key={r.id} row={r} onDetail={() => setDetailRow(r)} />)
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="h-14 shrink-0 flex items-center justify-between px-6 gap-3 border-t border-white/[0.08]">
          <div className="text-[12.5px] text-ink-3 whitespace-nowrap">
            총 <b className="tabular-nums text-ink-1 font-semibold">{summary.totalCount}</b>건 중{' '}
            <b className="tabular-nums text-ink-1 font-semibold">
              {filtered.length === 0 ? 0 : 1}–{filtered.length}
            </b>{' '}
            표시
          </div>
          <div className="flex-1 flex items-center justify-center">
            {totalPages > 1 && (
              <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
            )}
          </div>
          <Dropdown<PageSizeOption>
            value={pageSize}
            onChange={(v) => {
              setPageSize(v)
              setPage(0)
              // setPageSize 는 비동기 업데이트 → 다음 렌더 전엔 옛 pageSize 캡처.
              // sizeOverride 로 신규 size 를 명시 전달해 첫 호출부터 정확한 페이지 사이즈 사용.
              loadTrades(0, Number(v))
            }}
            options={PAGE_SIZE_OPTIONS.map((s) => ({
              value: s,
              label: `페이지당 ${s}행`,
            }))}
            ariaLabel="페이지당 행 수"
          />
        </div>
      </div>
      <TradeDetailModal row={detailRow} onClose={() => setDetailRow(null)} />
    </div>
  )
}

function SummaryChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="glass rim inline-flex items-center gap-1.5 px-3.5 h-8 rounded-full text-[12px] font-semibold text-ink-3 whitespace-nowrap">
      {children}
    </span>
  )
}

/** 정렬은 아직 없다 — 자리만 두고 누르면 "준비 중" 을 알린다 (#158 범위 밖). */
function SortPlaceholder() {
  return (
    <button
      type="button"
      onClick={() => showComingSoon('정렬')}
      aria-label="정렬 (준비 중)"
      className="ml-1 opacity-50 hover:opacity-80"
    >
      ↕
    </button>
  )
}

/** 머리 행 바탕은 서리 유리가 창 바탕 위에 겹친 색 — 스크롤해도 판과 띠가 지지 않는다. */
function Th({
  children,
  align = 'left',
}: {
  children: React.ReactNode
  align?: 'left' | 'right' | 'center'
}) {
  return (
    <th
      scope="col"
      className={`sticky top-0 z-[1] bg-[#17181b] text-[12px] font-medium text-ink-3
                  px-3 h-10 whitespace-nowrap border-b border-white/[0.08]
                  ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'}`}
    >
      {children}
    </th>
  )
}

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 8 }).map((_, j) => (
        <td key={j} className="px-3 h-12 border-b border-white/[0.06]">
          <div className="skeleton h-3.5" />
        </td>
      ))}
    </tr>
  )
}

function Row({ row, onDetail }: { row: HistoryRow; onDetail: () => void }) {
  const isFailed = row.status === 'FAILED'
  const td = 'px-3 h-12 align-middle border-b border-white/[0.06]'

  return (
    <tr
      className="hover:bg-white/[0.04] transition-colors duration-200"
      title={row.failureReason ? `거부 사유: ${row.failureReason}` : undefined}
    >
      <td className={`${td} num text-[12px] text-ink-2`}>{formatDateTime(row.createdAt)}</td>
      <td className={td}>
        <span className="num text-[13px] font-semibold text-ink-1">{row.ticker}</span>
      </td>
      <td className={td}>
        <DirLabel side={row.side} />
      </td>
      <td className={`${td} text-right text-[13px] text-ink-2 tabular-nums`}>{row.executedQty}</td>
      <td className={`${td} text-right text-[13px] tabular-nums ${isFailed ? 'line-through text-ink-3' : 'text-ink-2'}`}>
        {row.executedPrice != null ? `$${row.executedPrice.toFixed(2)}` : '—'}
      </td>
      <td className={`${td} text-right text-[13px] tabular-nums ${isFailed ? 'line-through text-ink-3' : 'text-ink-1'}`}>
        {row.amount != null
          ? `$${row.amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
          : '—'}
      </td>
      <td className={td}>
        <StatusLabel status={row.status} reason={row.failureReason} />
      </td>
      <td className={`${td} text-center`}>
        <button type="button" onClick={onDetail} className="text-[12.5px] text-ink-3 hover:text-ink-1">
          보기
        </button>
      </td>
    </tr>
  )
}

/** 매수 · 매도 글자는 가격 방향과 이어지므로 상승 빨강 · 하락 파랑을 쓴다 (design-system 가격). */
function DirLabel({ side }: { side: 'BUY' | 'SELL' }) {
  return (
    <span className={`text-[13px] font-semibold ${side === 'BUY' ? 'text-up' : 'text-down'}`}>
      {side === 'BUY' ? '▲ 매수' : '▼ 매도'}
    </span>
  )
}

const STATUS_META: Record<HistoryStatus, { label: string; className: string }> = {
  EXECUTED: { label: '체결', className: 'text-ok' },
  // tailwind 에는 caution 이름이 없어(예전 이름 warning) 토큰 변수를 직접 쓴다
  PENDING: { label: '대기', className: 'text-[var(--caution)]' },
  FAILED: { label: '실패', className: 'text-danger' },
}

/** 상태 색은 작은 점과 글자에만 쓰고 늘 문구와 함께 둔다. */
function StatusLabel({ status, reason }: { status: HistoryStatus; reason?: string }) {
  const meta = STATUS_META[status]
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[12.5px] font-semibold ${meta.className}`}
      title={status === 'FAILED' && reason ? `거부 사유: ${reason}` : undefined}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" aria-hidden="true" />
      {meta.label}
    </span>
  )
}

function TradeDetailModal({ row, onClose }: { row: HistoryRow | null; onClose: () => void }) {
  const fields: [string, string][] = row
    ? [
        ['일시', formatDateTime(row.createdAt)],
        ['종목', row.ticker],
        ['방향', row.side === 'BUY' ? '매수' : '매도'],
        ['주문유형', row.orderType === 'MARKET' ? '시장가' : row.orderType === 'LIMIT' ? '지정가' : '—'],
        ['주문수량', row.orderQty != null ? String(row.orderQty) : '—'],
        ['주문가', row.price != null ? `$${row.price.toFixed(2)}` : '—'],
        ['체결수량', String(row.executedQty)],
        ['체결가', row.executedPrice != null ? `$${row.executedPrice.toFixed(2)}` : '—'],
        ['체결금액', row.amount != null ? `$${row.amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'],
        ['상태', STATUS_META[row.status].label],
        ...(row.failureReason ? [['거부 사유', row.failureReason] as [string, string]] : []),
      ]
    : []
  return (
    <Modal open={row != null} onClose={onClose} ariaLabel="거래 상세">
      <div className="w-[420px] max-w-[90vw] max-h-[80vh] overflow-y-auto p-7">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-[18px] font-semibold text-ink-1">거래 상세</h3>
          <button type="button" onClick={onClose} aria-label="닫기" className="gbtn rim gbtn-icon gbtn-sm">
            <svg width="14" height="14" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M3 3l6 6M9 3l-6 6" />
            </svg>
          </button>
        </div>
        <dl className="flex flex-col gap-3">
          {fields.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-4">
              <dt className="text-[13px] text-ink-3 whitespace-nowrap">{label}</dt>
              <dd className="text-[14px] text-ink-1 tabular-nums truncate text-right">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Modal>
  )
}

/** CSV 용 로컬 시각 "YYYY-MM-DD HH:mm:ss". 화면 일시와 같은 시간대로 맞춘다. */
function formatCsvDateTime(value: string): string {
  const d = parseServerTime(value)
  if (Number.isNaN(d.getTime())) return value
  return `${d.getFullYear()}-${formatDateTime(d.getTime())}`
}

/** ISO → 로컬 시각 "MM-DD HH:mm:ss". 시간대 표기 없는 백엔드 시각은 UTC 로 읽는다. */
/**
 * 목록의 일시 컬럼과 헤더의 "마지막 업데이트" 가 같은 형식이어야 하므로 한 함수로 둔다.
 * ISO 문자열(백엔드 응답)과 timestamp(Date.now()) 를 모두 받는다.
 */
function formatDateTime(value: string | number): string {
  const d = parseServerTime(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}:${ss}`
}

