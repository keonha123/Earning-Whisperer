import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import SidePanel from '../common/SidePanel'
import CompanyLogo from '../common/CompanyLogo'
import MiniLineChart from './MiniLineChart'
import { useDrawerStore } from '../../store/useDrawerStore'
import { useCompanyDetail } from '../../hooks/useCompanyDetail'
import { usePrices } from '../../hooks/usePrices'
import { useWatchlist } from '../../hooks/useWatchlist'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import type { StockDetailResponsePayload } from '../../../lib/types/stockDetail'
import { showIpcErrorToast } from '../common/Toast'
import {
  pickYTicks as pickYTicksUtil,
  pickXLabels as pickXLabelsUtil,
} from '../../lib/chartUtils'
import {
  formatMarketCap,
  formatPrice,
  formatRevenue,
  formatEps,
  formatEpsEstimate,
  formatDividendYield,
  formatDirectPercent,
  formatPeriodChangeLabel,
  formatDayChangeLabel,
  pickChartDirection,
  trimDateLabel,
} from '../../lib/companyDetailFormatters'
import { ComingSoon, EmptyState, LoadingBlock } from '../common/StateView'
import { countdownParts } from '../../lib/callScreen'

/**
 * 종목 브리핑 — 어느 화면에서나 오른쪽에 여는 패널 (docs/design/screens/stock-brief.md).
 *
 * "이 종목의 다음 콜을 들을 준비" 를 위에서부터 둔다: 다음 콜 → 최근 어닝 반응 → 30일 종가 →
 * 기본 정보 → AI 요약 자리. 아래 행동 줄의 `콜 화면 열기` 가 이 패널의 주 행동이다.
 *
 *  - 데이터는 STOCK_GET_DETAIL(useCompanyDetail), 실시간 가격은 PRICES_UPDATE(usePrices).
 *  - 관심종목 추가 · 제거는 WATCHLIST_ADD/REMOVE. store 는 WATCHLIST_UPDATE 방송으로 갱신된다.
 *  - S&P 500 밖 종목(active=false)은 어닝 분석을 지원하지 않는다고 쓴다.
 *  - ticker 는 useDrawerStore.open 과 main 핸들러가 모두 정규식으로 검사한다.
 *  - 닫기: 닫기 버튼 / Esc / 바깥 클릭.
 */
export default function CompanyDrawer() {
  const openTicker = useDrawerStore((s) => s.openTicker)
  const close = useDrawerStore((s) => s.close)
  const navigate = useNavigate()
  const location = useLocation()

  const { data, loading, error } = useCompanyDetail(openTicker)
  const { prices } = usePrices()
  const { items: watchlistItems } = useWatchlist()

  const isOpen = openTicker != null
  const livePrice = openTicker ? (prices[openTicker]?.currentPrice ?? null) : null
  const isWatched = openTicker ? watchlistItems.some((w) => w.ticker === openTicker) : false
  // 그 종목의 콜 화면에서 연 브리핑이면 콜 화면 열기는 지금 화면으로 다시 가는 버튼이라 두지 않는다.
  const onThisCall =
    location.pathname === '/call' && new URLSearchParams(location.search).get('ticker') === openTicker

  const onOpenCall = useCallback(
    (ticker: string) => {
      close()
      navigate(`/call?ticker=${encodeURIComponent(ticker)}`)
    },
    [close, navigate],
  )

  return (
    <SidePanel
      open={isOpen}
      onClose={close}
      width={420}
      ariaLabel={openTicker ? `${openTicker} 종목 브리핑` : '종목 브리핑'}
    >
      {loading && (
        <>
          <PanelHeader ticker={openTicker ?? ''} onClose={close} />
          <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-8">
            <LoadingBlock lines={3} lineHeight={20} />
            <LoadingBlock lines={4} lineHeight={16} />
            <div className="skeleton" style={{ height: 120 }} aria-hidden />
          </div>
        </>
      )}
      {!loading && (error || !data) && openTicker && (
        <>
          <PanelHeader ticker={openTicker} onClose={close} />
          <div className="flex-1 flex items-center justify-center px-6">
            <EmptyState message="종목 정보를 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요." />
          </div>
        </>
      )}
      {!loading && !error && data && (
        <BriefContent
          data={data}
          livePrice={livePrice}
          isWatched={isWatched}
          onOpenCall={onThisCall ? null : onOpenCall}
          onClose={close}
        />
      )}
    </SidePanel>
  )
}

/* ============================================================================
 * 본문
 * ========================================================================== */

interface BriefContentProps {
  data: StockDetailResponsePayload
  /** PRICES_UPDATE 로 받은 실시간 가격. 없으면 null → 응답의 currentPrice. */
  livePrice: number | null
  isWatched: boolean
  /** null 이면 콜 화면 열기를 두지 않는다(이미 그 종목의 콜 화면). */
  onOpenCall: ((ticker: string) => void) | null
  onClose: () => void
}

function BriefContent({ data, livePrice, isWatched, onOpenCall, onClose }: BriefContentProps) {
  const supportsEarnings = data.active // S&P 500 편입 종목만 어닝 분석 지원
  const displayPrice = livePrice ?? data.currentPrice
  // 최근 분기부터. 응답 순서에 기대지 않고 발표 시각으로 정렬한다.
  const history = [...data.earningsHistory].sort((a, b) => b.announcedAt - a.announcedAt)

  return (
    <>
      <PanelHeader
        ticker={data.ticker}
        companyName={data.companyName}
        badges={
          <>
            {!data.active && <Chip title="S&P 500 밖 종목">지원 외</Chip>}
            {data.partial && <Chip title="일부 데이터를 아직 받지 못했습니다">일부 동기화 중</Chip>}
          </>
        }
        price={displayPrice}
        isLivePrice={livePrice != null}
        onClose={onClose}
      />

      <div className="flex-1 overflow-y-auto overflow-x-hidden px-6 pb-6 flex flex-col gap-7">
        <Section title="다음 콜">
          {!supportsEarnings ? (
            <Muted>어닝 분석은 S&amp;P 500 종목만 지원합니다.</Muted>
          ) : data.nextEarning ? (
            <NextCall next={data.nextEarning} />
          ) : (
            <Muted>예정된 실적 발표가 없습니다.</Muted>
          )}
        </Section>

        <Section title="최근 어닝 반응">
          {!supportsEarnings ? (
            <Muted>어닝 분석은 S&amp;P 500 종목만 지원합니다.</Muted>
          ) : history.length > 0 ? (
            <EarningsReactions rows={history} />
          ) : (
            <Muted>지난 실적 기록이 없습니다.</Muted>
          )}
        </Section>

        <Section
          title="30일 종가"
          right={data.chart30d.length > 1 ? <SignedPercent label={formatPeriodChangeLabel(data.chart30d)} /> : null}
        >
          {data.chart30d.length > 0 ? (
            <ChartBlock chart30d={data.chart30d} />
          ) : (
            <Muted>차트 데이터를 아직 받지 못했습니다.</Muted>
          )}
        </Section>

        <Section title="기본 정보">
          {data.basic ? (
            <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-[13.5px]">
              <KV k="섹터" v={data.sector ?? '—'} />
              <KV k="시가총액" v={formatMarketCap(data.basic.marketCapUsd)} />
              <KV k="52주 고가" v={formatPrice(data.basic.high52w)} />
              <KV k="52주 저가" v={formatPrice(data.basic.low52w)} />
              <KV k="배당수익률" v={formatDividendYield(data.basic.dividendYield)} />
            </dl>
          ) : (
            <Muted>기본 정보를 아직 받지 못했습니다.</Muted>
          )}
        </Section>

        <ComingSoon title="AI 요약" note="지난 콜을 요약하는 기능은 준비 중입니다" className="py-6" />
      </div>

      <ActionBar ticker={data.ticker} isWatched={isWatched} onOpenCall={onOpenCall} />
    </>
  )
}

/* ============================================================================
 * 머리 · 행동 줄 · 섹션
 * ========================================================================== */

function PanelHeader({
  ticker,
  companyName,
  badges,
  price,
  isLivePrice,
  onClose,
}: {
  ticker: string
  companyName?: string
  badges?: React.ReactNode
  price?: number | null
  isLivePrice?: boolean
  onClose: () => void
}) {
  return (
    <div className="px-6 pt-5 pb-5 flex items-start gap-3 shrink-0">
      <CompanyLogo ticker={ticker || 'NA'} size={36} />
      <div className="min-w-0 flex-1 flex flex-col gap-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="num text-[18px] font-semibold text-ink-1">{ticker || '—'}</span>
          {badges}
        </div>
        {companyName && <span className="text-[13.5px] text-ink-2 truncate">{companyName}</span>}
        {price !== undefined && (
          <span className="text-[13px] text-ink-3">
            <span className="tabular-nums text-ink-1 text-[15px] font-semibold">{formatPrice(price)}</span>
            {isLivePrice && <span> · 실시간</span>}
          </span>
        )}
      </div>
      <button type="button" aria-label="닫기" onClick={onClose} className="gbtn rim gbtn-icon gbtn-sm">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>
  )
}

function ActionBar({
  ticker,
  isWatched,
  onOpenCall,
}: {
  ticker: string
  isWatched: boolean
  onOpenCall: ((ticker: string) => void) | null
}) {
  // 응답(WATCHLIST_UPDATE 방송)이 오기 전에 다시 누르면 같은 요청이 두 번 나가므로 그동안 막는다.
  const [busy, setBusy] = useState(false)
  const toggleWatchlist = useCallback(async () => {
    setBusy(true)
    try {
      if (isWatched) {
        await ipc.invoke(IPC_CHANNELS.WATCHLIST_REMOVE, { ticker })
      } else {
        await ipc.invoke(IPC_CHANNELS.WATCHLIST_ADD, { ticker })
      }
      // store 는 WATCHLIST_UPDATE 방송으로 갱신된다.
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[CompanyDrawer] watchlist toggle 실패:', e)
      showIpcErrorToast(e)
    } finally {
      setBusy(false)
    }
  }, [isWatched, ticker])

  return (
    <div className="px-6 py-4 flex gap-3 border-t border-white/[0.08] shrink-0">
      <button
        type="button"
        onClick={toggleWatchlist}
        disabled={busy}
        className="gbtn rim flex-1"
        aria-pressed={isWatched}
      >
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          {isWatched ? <path d="M3 7h8" /> : <path d="M7 2v10M2 7h10" />}
        </svg>
        {isWatched ? '관심 해제' : '관심 추가'}
      </button>
      {onOpenCall && (
        <button type="button" onClick={() => onOpenCall(ticker)} className="gbtn gbtn-lapis rim flex-[1.4]">
          콜 화면 열기
        </button>
      )}
    </div>
  )
}

function Section({
  title,
  right,
  children,
}: {
  title: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-3" aria-label={title}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[13px] font-semibold text-ink-2">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  )
}

/* ============================================================================
 * 섹션 본문
 * ========================================================================== */

function NextCall({ next }: { next: NonNullable<StockDetailResponsePayload['nextEarning']> }) {
  // 패널을 열어 둔 동안에도 남은 시간이 맞도록 30초마다 다시 계산한다.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="flex items-baseline gap-2">
          <span className="text-[20px] font-semibold text-ink-1">{untilLabel(next.scheduledAt, now)}</span>
          <span className="text-[12.5px] text-ink-3">{next.confirmed ? '확정' : '예정'}</span>
        </span>
        <span className="text-[13.5px] text-ink-2">
          {formatKst(next.scheduledAt)} KST
          <span className="text-ink-3"> (미 동부 {formatEt(next.scheduledAt)})</span>
        </span>
      </div>
      <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-[13.5px]">
        <KV k="EPS 컨센서스" v={formatEpsEstimate(next.epsEstimate)} />
        <KV k="매출 컨센서스" v={formatRevenue(next.revenueEstimate)} />
      </dl>
    </div>
  )
}

function EarningsReactions({ rows }: { rows: StockDetailResponsePayload['earningsHistory'] }) {
  return (
    <table className="w-full border-collapse text-[13px] table-fixed">
      <thead>
        <tr className="text-[12px] text-ink-3">
          <th className="text-left font-normal pb-1.5 w-[28%]">분기</th>
          <th className="text-right font-normal pb-1.5">EPS 예상 → 실제</th>
          <th className="text-right font-normal pb-1.5 w-[24%]">발표일 주가</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.fiscalPeriodLabel}-${r.announcedAt}`} className="border-t border-white/[0.06]">
            <td className="py-2 text-ink-2">{r.fiscalPeriodLabel}</td>
            <td className="py-2 text-right tabular-nums text-ink-2">
              {formatEps(r.epsEstimate)} → <span className="text-ink-1">{formatEps(r.epsActual)}</span>
            </td>
            <td className="py-2 text-right">
              <Reaction value={r.priceReactionPercent} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ChartBlock({ chart30d }: { chart30d: StockDetailResponsePayload['chart30d'] }) {
  const points = chart30d.map((p) => ({ date: trimDateLabel(p.date), price: p.close }))
  const prices = points.map((p) => p.price)
  const direction = pickChartDirection(chart30d)
  const dayChange = formatDayChangeLabel(chart30d)

  return (
    <div className="flex flex-col gap-2">
      {dayChange && (
        <span className="text-[12.5px] text-ink-3">
          마지막 거래일 <SignedPercent label={dayChange} />
        </span>
      )}
      <div className="relative h-[110px]">
        <div className="absolute left-0 top-0 bottom-4 w-10 flex flex-col justify-between text-[11px] tabular-nums text-ink-3 text-right pr-1">
          {pickYTicks(prices).map((y, i) => (
            <span key={`${y}-${i}`}>${y.toFixed(0)}</span>
          ))}
        </div>
        <div className="absolute left-11 right-0.5 top-0 bottom-4">
          <MiniLineChart
            points={points}
            color={direction === 'down' ? 'sell' : direction === 'up' ? 'accent' : 'neutral'}
            viewWidth={340}
            viewHeight={90}
          />
        </div>
        <div className="absolute left-11 right-0.5 bottom-0 flex justify-between text-[11px] tabular-nums text-ink-3">
          {pickXLabels(points).map((p, i) => (
            <span key={`${p.date}-${i}`}>{p.date}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

/** "+1.32%" · "-0.40% · -$0.12" 처럼 부호로 시작하는 라벨을 부호에 맞는 가격색으로 쓴다. */
function SignedPercent({ label }: { label: string }) {
  if (!label) return null
  // 변화가 없으면(+0.00%) 무채색이다.
  const pct = Number.parseFloat(label)
  const color = !Number.isFinite(pct) || pct === 0 ? 'var(--ink-3)' : pct > 0 ? 'var(--up)' : 'var(--down)'
  return (
    <span className="text-[12.5px] tabular-nums font-semibold" style={{ color }}>
      {label}
    </span>
  )
}

function Reaction({ value }: { value: number | null }) {
  if (value == null || !Number.isFinite(value)) return <span className="tabular-nums text-ink-3">—</span>
  if (value === 0) return <span className="tabular-nums text-ink-3">{formatDirectPercent(0)}</span>
  const up = value > 0
  return (
    <span className="tabular-nums font-semibold" style={{ color: up ? 'var(--up)' : 'var(--down)' }}>
      {up ? '▲' : '▼'} {formatDirectPercent(Math.abs(value))}
    </span>
  )
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-ink-3">{k}</dt>
      <dd className="text-right tabular-nums text-ink-1">{v}</dd>
    </>
  )
}

function Chip({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11.5px] font-semibold text-ink-3 border border-white/15"
      title={title}
    >
      {children}
    </span>
  )
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p className="text-[13px] text-ink-3">{children}</p>
}

const KST = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'long',
  day: 'numeric',
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
})

const ET = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'America/New_York',
  hour: 'numeric',
  minute: '2-digit',
})

/** 콜 시작까지 남은 시간. 하루 안이면 시간 · 분, 그 밖이면 일 단위. */
function untilLabel(sec: number, nowMs: number): string {
  const parts = countdownParts(sec, nowMs)
  if (!parts) return '예정 시각이 지났습니다'
  if (parts.days > 0) return `${parts.days}일 뒤`
  if (parts.hours > 0) return `${parts.hours}시간 ${parts.minutes}분 뒤`
  return `${Math.max(parts.minutes, 1)}분 뒤`
}

function formatKst(sec: number): string {
  return KST.format(new Date(sec * 1000))
}

function formatEt(sec: number): string {
  return ET.format(new Date(sec * 1000))
}

/** 가격 시계열 → 4단계 Y축 레이블. 1달러 단위 — 10달러 단위면 30일 범위가 좁을 때 눈금이 겹친다. */
function pickYTicks(prices: number[]): number[] {
  return pickYTicksUtil(prices, 4, 1)
}

/** 시계열에서 5개 X축 레이블 균등 추출. */
function pickXLabels(points: { date: string }[]): { date: string }[] {
  return pickXLabelsUtil(points, 5)
}
