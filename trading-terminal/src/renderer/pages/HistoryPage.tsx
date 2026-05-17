import { useEffect, useMemo, useState } from 'react'
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
import {
  historyRowsDevMock,
  historySummaryDevMock,
  type HistoryRowMock,
  type HistoryMode,
  type HistoryStatus,
} from '../fixtures/historyRows.dev-mock'

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
 *  - DEV 빌드: dev-mock 의 HistoryRowMock 으로 mode / AI 컬럼 표시.
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
  orderQty: number
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

  const navigate = useNavigate()
  const setAuthenticated = useConnectionStore((s) => s.setAuthenticated)
  const clearUser = useUserStore((s) => s.clear)

  useEffect(() => {
    loadTrades(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * @param p          요청할 페이지 번호 (0-base).
   * @param sizeOverride  page size 변경과 동시에 호출될 때 신규 size 전달용.
   *                      React state setter (setPageSize) 는 비동기 업데이트라
   *                      같은 tick 의 closure 가 옛 pageSize 를 캡처한다.
   *                      sizeOverride 가 주어지면 우선 적용한다.
   */
  async function loadTrades(p: number, sizeOverride?: number) {
    setLoading(true)
    try {
      const size = sizeOverride ?? Number(pageSize)
      const data = await ipc.invoke<{ content: Trade[]; totalPages: number }>(
        IPC_CHANNELS.TRADES_GET,
        { page: p, size },
      )
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
      setLoading(false)
    }
  }

  function handlePageChange(p: number) {
    setPage(p)
    loadTrades(p)
  }

  // 표시 행: DEV 에서는 fixture (mode/AI 컬럼 시연용), PROD 에서는 실제 trades.
  const displayRows: HistoryRowMock[] = useMemo(() => {
    if (import.meta.env.DEV && trades.length === 0) {
      return [...historyRowsDevMock]
    }
    return trades.map((t) => ({
      id: t.id,
      ticker: t.ticker,
      side: t.side,
      mode: 'MANUAL' as HistoryMode, // prod fallback — 실제 mode 정보 없음
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
      // period 필터: dev-mock 은 고정 날짜이므로 UI 만 표시 (실제 필터 효과 없음)
      // TODO(impl): TRADES_GET 에 period 쿼리 파라미터 추가 후 백엔드 필터링.
      return true
    })
  }, [displayRows, segment, modeFilter, tickerFilter, search])

  // 요약: DEV 에서는 fixture summary, PROD 에서는 페이지 단위 집계.
  const summary = useMemo(() => {
    if (import.meta.env.DEV && trades.length === 0) {
      return historySummaryDevMock
    }
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
              <span className="num">{formatAgo(lastUpdatedAt)}</span>
            </span>
          )}
          <button
            type="button"
            onClick={() => loadTrades(page)}
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
          onClick={() => {
            // TODO(impl): SHELL_SAVE_CSV IPC 핸들러 추가 후 연결.
            //   - main 측에서 path traversal 방지 (다운로드 디렉터리 화이트리스트).
            //   - 파일명 sanitize ([A-Za-z0-9_-]).
            //   - 사용자 권한 + KIS 토큰 유효성 검증.
            //   - CSV 인코딩: UTF-8 + BOM (Excel 한글 호환).
            //   - 민감 데이터(체결가/금액) 포함 — 사용자 확인 다이얼로그 필요.
            console.warn('[HistoryPage] CSV 내보내기는 다음 PR 에서 구현됩니다.')
          }}
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
                <Th align="right">수량</Th>
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
                filtered.map((r) => <Row key={r.id} row={r} />)
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

function Row({ row }: { row: HistoryRowMock }) {
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
          // TODO(impl): 상세 화면 라우트 도입 후 navigate(`/history/${id}`).
          onClick={() => {
            console.warn('[HistoryPage] 상세 화면은 다음 PR 에서 구현됩니다.', row.id)
          }}
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

/** ISO → "MM-DD HH:mm:ss" (KST 가정 — fixture 의 +09:00 시간대 준수). */
function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}:${ss}`
}

function formatAgo(ts: number): string {
  const sec = Math.floor((Date.now() - ts) / 1000)
  if (sec < 60) return `${Math.max(1, sec)}초 전`
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`
  return `${Math.floor(sec / 3600)}시간 전`
}
