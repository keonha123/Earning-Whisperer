import { useEffect, useMemo, useRef, useState } from 'react'
import type { HistoryMode, HistoryRow, HistoryStatus } from '../types/tradeHistory'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import Pagination from '../components/common/Pagination'
import SegmentedControl from '../components/common/SegmentedControl'
import Dropdown from '../components/common/Dropdown'
import MiniGauge from '../components/common/MiniGauge'
import { showIpcErrorToast } from '../components/common/Toast'
import { isIpcError } from '../../lib/types/ipcError'
import { useConnectionStore } from '../store/useConnectionStore'
import { useUserStore } from '../store/useUserStore'

/**
 * HistoryPage — 체결 내역.
 *
 * 디자인 매칭: HistoryPage.html.
 *  - Row 1: 제목 + 요약 칩 (오늘/BUY/SELL) + 새로고침.
 *  - Row 2 (필터 바): 세그먼트(전체/BUY/SELL/실패) + 드롭다운 3개 (기간/종목/모드)
 *    + 검색 + CSV 내보내기 (noop).
 *  - Row 3 (테이블 카드): 10컬럼.
 *  - Footer: 총 N건 / Pagination / 페이지당 행 수.
 *
 * Trade 인터페이스 정책:
 *  - 기존 Trade 타입 (id, ticker, side, executedQty, executedPrice, status, createdAt)
 *    그대로 유지. mode/ai_score 필드는 추가하지 않는다.
 *  - mode / AI 컬럼은 백엔드가 값을 주지 않으므로 "—" 로 표시한다.
 *  - PROD 빌드: 백엔드에서 받은 Trade 만 표시, mode / AI 셀은 "—".
 *
 * 보안 메모:
 *  - CSV 내보내기는 본 PR 에서 noop. 다음 PR 에서 IPC 핸들러 (`SHELL_SAVE_CSV`)
 *    경유로 구현 예정. main 측에서 path traversal 방지(다운로드 디렉터리 화이트리스트
 *    + 파일명 sanitize), 사용자 권한 검증 필요.
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
type ModeFilterId = 'all' | 'AUTO' | 'SEMI' | 'MANUAL'

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [totalPages, setTotalPages] = useState(0)

  const [segment, setSegment] = useState<SegmentId>('all')
  const [period, setPeriod] = useState<PeriodId>('7d')
  const [tickerFilter, setTickerFilter] = useState<string>('all')
  const [modeFilter, setModeFilter] = useState<ModeFilterId>('all')
  const [search, setSearch] = useState('')
  const [pageSize, setPageSize] = useState<PageSizeOption>('12')
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null)
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
    } catch (e: unknown) {
      console.error('거래 내역 조회 실패:', e)
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
    const headers = ['일시', '종목', '방향', '모드', '주문수량', '체결수량', '주문가', '체결가', '체결금액', '상태']
    const lines = [
      headers.join(','),
      ...rows.map((r) =>
        [
          r.createdAt,
          r.ticker,
          r.side,
          r.mode,
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
      mode: 'MANUAL' as HistoryMode, // prod fallback — 실제 mode 정보 없음
      orderType: t.orderType ?? null,
      orderQty: t.orderQty ?? null,
      price: t.price ?? null,
      executedQty: t.executedQty,
      executedPrice: t.executedPrice,
      amount:
        t.executedPrice != null ? t.executedPrice * t.executedQty : null,
      ai_score: null, // prod 에서는 AI 점수 없음
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
      if (modeFilter !== 'all' && r.mode !== modeFilter) return false
      if (tickerFilter !== 'all' && r.ticker !== tickerFilter) return false
      if (search.trim()) {
        const q = search.trim().toUpperCase()
        if (!r.ticker.includes(q)) return false
      }
      return true
    })
  }, [displayRows, segment, modeFilter, tickerFilter, search])

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

  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      {/* Row 1: 헤더 */}
      <div className="flex items-center gap-3 shrink-0">
        <h2 className="text-[20px] font-semibold text-text-primary tracking-[-0.015em] whitespace-nowrap">
          체결 내역
        </h2>
        <div className="flex gap-1.5">
          <SummaryChip>
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" className="opacity-70">
              <circle cx="6" cy="6" r="4.5" />
              <path d="M6 3.5V6l1.8 1.2" />
            </svg>
            오늘 <b className="num text-text-primary font-semibold">{summary.todayCount}</b>건
          </SummaryChip>
          <SummaryChip>
            <span className="text-buy">▲ BUY</span>{' '}
            <b className="num text-buy font-semibold">{summary.buyCount}</b>건
          </SummaryChip>
          <SummaryChip>
            <span className="text-sell">▼ SELL</span>{' '}
            <b className="num text-sell font-semibold">{summary.sellCount}</b>건
          </SummaryChip>
        </div>
        <div className="ml-auto flex items-center gap-2 text-[11px] text-text-tertiary whitespace-nowrap">
          {lastUpdatedAt && (
            <span>
              마지막 업데이트{' '}
              <span className="num">{formatDateTime(lastUpdatedAt)}</span>
            </span>
          )}
          <button
            type="button"
            onClick={() => reconcileThenLoad(page)}
            className="px-2.5 py-1 rounded-md inline-flex items-center gap-1.5
                       text-text-secondary hover:bg-surface-2 hover:text-text-primary
                       text-[11px] font-medium"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 6a4 4 0 017-2.5M10 6a4 4 0 01-7 2.5M9 2v2h-2M3 10V8h2" />
            </svg>
            새로고침
          </button>
        </div>
      </div>

      {/* Row 2: 필터 바 */}
      <div className="shrink-0 bg-surface-1 border border-border-subtle rounded-lg
                      px-3 py-2.5 flex items-center gap-2.5 flex-wrap">
        <SegmentedControl<SegmentId>
          items={[
            { id: 'all', label: '전체' },
            { id: 'buy', label: 'BUY' },
            { id: 'sell', label: 'SELL' },
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
        <Dropdown<ModeFilterId>
          prefix="모드:"
          value={modeFilter}
          onChange={setModeFilter}
          options={[
            { value: 'all', label: '전체' },
            { value: 'AUTO', label: '🚀 AUTO' },
            { value: 'SEMI', label: '⚡ SEMI' },
            { value: 'MANUAL', label: '🛡 MANUAL' },
          ]}
          ariaLabel="모드 필터"
        />

        <div className="ml-auto flex items-center gap-2 bg-surface-3 border border-border-strong rounded-md px-2.5 h-[30px] w-[200px]">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-tertiary">
            <circle cx="5" cy="5" r="3.5" />
            <path d="M8 8l2.5 2.5" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ticker 검색…"
            className="flex-1 bg-transparent text-[12px] text-text-primary placeholder:text-text-disabled outline-none"
          />
        </div>

        <button
          type="button"
          onClick={handleCsvExport}
          className="h-[30px] px-3 inline-flex items-center gap-1.5 rounded-md
                     border border-accent-500/35 text-accent-400 hover:bg-accent-500/10 hover:text-accent-300
                     text-[11px] font-semibold whitespace-nowrap"
        >
          CSV 내보내기
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M5 1v6M2 5l3 3 3-3M1.5 9h7" />
          </svg>
        </button>
      </div>

      {/* Row 3: 테이블 */}
      <div className="card p-0 overflow-hidden flex flex-col flex-1 min-h-0 rounded-xl">
        <div className="overflow-y-auto flex-1 min-h-0">
          <table className="w-full table-fixed border-separate border-spacing-0">
            <colgroup>
              <col style={{ width: 130 }} />
              <col style={{ width: 78 }} />
              <col style={{ width: 72 }} />
              <col style={{ width: 98 }} />
              <col style={{ width: 52 }} />
              <col style={{ width: 84 }} />
              <col style={{ width: 104 }} />
              <col style={{ width: 82 }} />
              <col style={{ width: 80 }} />
              <col style={{ width: 62 }} />
            </colgroup>
            <thead>
              <tr>
                <Th>일시 <span className="opacity-50 ml-1">↕</span></Th>
                <Th>종목</Th>
                <Th>방향</Th>
                <Th>모드</Th>
                <Th align="right">체결수량</Th>
                <Th align="right">체결가 <span className="opacity-50 ml-1">↕</span></Th>
                <Th align="right">체결금액 <span className="opacity-50 ml-1">↕</span></Th>
                <Th align="right">AI</Th>
                <Th>상태</Th>
                <Th align="center">액션</Th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <SkeletonRow key={i} />
                ))
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-text-disabled text-xs">
                    조건에 맞는 거래 내역이 없습니다
                  </td>
                </tr>
              ) : (
                filtered.map((r) => <Row key={r.id} row={r} onDetail={() => setDetailRow(r)} />)
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="h-12 min-h-[48px] flex items-center justify-between
                        px-3.5 gap-3 border-t border-border-subtle"
             style={{ backgroundColor: '#0f1622' /* surface-0b — 디자인 캔버스 한정 */ }}>
          <div className="text-[11px] text-text-tertiary whitespace-nowrap">
            총 <b className="num text-text-primary">{summary.totalCount}</b>건 중{' '}
            <b className="num text-text-primary">
              {filtered.length === 0 ? 0 : 1}–{filtered.length}
            </b>{' '}
            표시
          </div>
          <div className="flex-1 flex items-center justify-center">
            {totalPages > 1 ? (
              <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
            ) : (
              // 디자인 캔버스 매칭용 더미 페이지네이션 (실제 totalPages 가 0/1 일 때)
              <div className="flex items-center gap-1 text-text-tertiary">
                <button className="pagination-btn-active">1</button>
              </div>
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
      {detailRow && (
        <TradeDetailModal row={detailRow} onClose={() => setDetailRow(null)} />
      )}
    </div>
  )
}

function SummaryChip({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md
                 bg-surface-2 border border-border-strong text-[11px] text-text-tertiary
                 whitespace-nowrap"
    >
      {children}
    </span>
  )
}

/**
 * 테이블 헤더 셀. 배경은 surface-0b (#0f1622) — 디자인 캔버스 한정 색으로
 * tailwind.config 토큰에 미승격, HistoryPage 의 table header/footer 에서만 사용.
 * (footer 의 동일 색과 정합 유지.)
 */
function Th({
  children,
  align = 'left',
}: {
  children: React.ReactNode
  align?: 'left' | 'right' | 'center'
}) {
  return (
    <th
      className={`bg-[#0f1622] /* surface-0b — HistoryPage 캔버스 한정 */
                  text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.12em]
                  px-2 h-10 whitespace-nowrap border-b border-border-subtle sticky top-0 z-[1]
                  ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'}`}
    >
      {children}
    </th>
  )
}

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 10 }).map((_, j) => (
        <td key={j} className="px-2 h-11 border-b border-border-subtle">
          <div className="h-3 bg-surface-2 rounded animate-pulse" />
        </td>
      ))}
    </tr>
  )
}

function Row({ row, onDetail }: { row: HistoryRow; onDetail: () => void }) {
  const isFailed = row.status === 'FAILED'
  const showAi = import.meta.env.DEV && row.ai_score != null

  return (
    <tr
      className="group h-11 hover:bg-surface-2 transition-colors duration-100"
      title={row.failureReason ? `거부 사유: ${row.failureReason}` : undefined}
    >
      <td className="px-2 align-middle border-b border-border-subtle text-[11px]
                     num text-text-secondary tracking-[0.01em]
                     group-hover:shadow-[inset_3px_0_0_var(--color-accent-500,#10b981)]">
        {formatDateTime(row.createdAt)}
      </td>
      <td className="px-2 align-middle border-b border-border-subtle">
        <span className="num text-[12px] font-semibold text-text-primary tracking-[0.02em]">
          {row.ticker}
        </span>
      </td>
      <td className="px-2 align-middle border-b border-border-subtle">
        <DirBadge side={row.side} />
      </td>
      <td className="px-2 align-middle border-b border-border-subtle">
        {import.meta.env.DEV ? <ModeBadge mode={row.mode} /> : <span className="text-text-disabled">—</span>}
      </td>
      <td className="px-2 num text-right align-middle border-b border-border-subtle text-[12px] text-text-secondary tabular-nums">
        {row.executedQty}
      </td>
      <td className={`px-2 num text-right align-middle border-b border-border-subtle text-[12px] tabular-nums ${
        isFailed ? 'line-through text-text-disabled' : 'text-text-secondary'
      }`}>
        {row.executedPrice != null ? `$${row.executedPrice.toFixed(2)}` : '—'}
      </td>
      <td className={`px-2 num text-right align-middle border-b border-border-subtle text-[12px] tabular-nums ${
        isFailed ? 'line-through text-text-disabled' : 'text-text-primary'
      }`}>
        {row.amount != null
          ? `$${row.amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
          : '—'}
      </td>
      <td className="px-2 align-middle border-b border-border-subtle text-right">
        {showAi && row.ai_score != null ? (
          <span className="inline-flex items-center justify-end w-full">
            <MiniGauge
              value={row.ai_score}
              color={
                row.ai_score >= 0.7 ? 'accent' : row.ai_score >= 0.5 ? 'warning' : 'neutral'
              }
              ariaLabel={`AI 점수 ${row.ai_score.toFixed(2)}`}
            />
          </span>
        ) : (
          <span className="text-text-disabled text-[10px]">—</span>
        )}
      </td>
      <td className="px-2 align-middle border-b border-border-subtle">
        <StatusBadge status={row.status} reason={row.failureReason} />
      </td>
      <td className="px-2 text-center align-middle border-b border-border-subtle">
        <button
          type="button"
          onClick={onDetail}
          className="text-[11px] text-text-tertiary hover:text-accent-400
                     inline-flex items-center gap-0.5"
        >
          상세 ↗
        </button>
      </td>
    </tr>
  )
}

function DirBadge({ side }: { side: 'BUY' | 'SELL' }) {
  return (
    <span
      className={`num inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold tracking-[0.04em] ${
        side === 'BUY' ? 'bg-buy/10 text-buy' : 'bg-sell/10 text-sell'
      }`}
    >
      {side === 'BUY' ? '▲' : '▼'} {side}
    </span>
  )
}

function ModeBadge({ mode }: { mode: HistoryMode }) {
  const label =
    mode === 'AUTO' ? '🚀 AUTO' : mode === 'SEMI' ? '⚡ SEMI' : '🛡 MANUAL'
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded
                 text-[10px] font-semibold tracking-[0.06em] whitespace-nowrap
                 border border-white/[0.22] text-text-primary"
    >
      {label}
    </span>
  )
}

function StatusBadge({ status, reason }: { status: HistoryStatus; reason?: string }) {
  if (status === 'EXECUTED') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-info">
        <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M2.5 6l2.5 2.5L9.5 3.5" />
        </svg>
        체결
      </span>
    )
  }
  if (status === 'PENDING') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-warning">
        <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" />
        대기
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] font-semibold text-sell"
      title={reason ? `거부 사유: ${reason}` : undefined}
    >
      <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M3 3l6 6M9 3l-6 6" />
      </svg>
      실패
    </span>
  )
}

function TradeDetailModal({ row, onClose }: { row: HistoryRow; onClose: () => void }) {
  const fields: [string, string][] = [
    ['일시', formatDateTime(row.createdAt)],
    ['종목', row.ticker],
    ['방향', row.side],
    ['모드', row.mode],
    ['주문유형', row.orderType ?? '—'],
    ['주문수량', row.orderQty != null ? String(row.orderQty) : '—'],
    ['주문가', row.price != null ? `$${row.price.toFixed(2)}` : '—'],
    ['체결수량', String(row.executedQty)],
    ['체결가', row.executedPrice != null ? `$${row.executedPrice.toFixed(2)}` : '—'],
    ['체결금액', row.amount != null ? `$${row.amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'],
    ['상태', row.status],
    ...(row.failureReason ? [['거부 사유', row.failureReason] as [string, string]] : []),
    ...(row.ai_score != null ? [['AI 점수', row.ai_score.toFixed(3)] as [string, string]] : []),
  ]
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-surface-1 border border-border-subtle rounded-xl shadow-2xl w-[420px] max-w-[90vw] max-h-[80vh] overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-[14px] font-semibold text-text-primary">거래 상세</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-text-tertiary hover:text-text-primary"
          >
            <svg width="14" height="14" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 3l6 6M9 3l-6 6" />
            </svg>
          </button>
        </div>
        <dl className="space-y-2.5">
          {fields.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-4">
              <dt className="text-[11px] text-text-tertiary whitespace-nowrap">{label}</dt>
              <dd className="text-[12px] text-text-primary num font-medium truncate text-right">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}

/** ISO → "MM-DD HH:mm:ss" (KST 가정 — fixture 의 +09:00 시간대 준수). */
/**
 * 목록의 일시 컬럼과 헤더의 "마지막 업데이트" 가 같은 형식이어야 하므로 한 함수로 둔다.
 * ISO 문자열(백엔드 응답)과 timestamp(Date.now()) 를 모두 받는다.
 */
function formatDateTime(value: string | number): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}:${ss}`
}

