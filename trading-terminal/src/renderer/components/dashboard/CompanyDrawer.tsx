import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import SidePanel from '../common/SidePanel'
import CompanyLogo from '../common/CompanyLogo'
import MiniLineChart from './MiniLineChart'
import { useDrawerStore } from '../../store/useDrawerStore'
import { useCompanyDetail } from '../../hooks/useCompanyDetail'
import { usePrices } from '../../hooks/usePrices'
import { useWatchlist } from '../../hooks/useWatchlist'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import type { StockDetailResponsePayload } from '../../../lib/types/stockDetail'
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
  dDayLabel,
  formatScheduledAt,
  formatPeriodChangeLabel,
  formatDayChangeLabel,
  pickChartDirection,
  trimDateLabel,
} from '../../lib/companyDetailFormatters'

/**
 * CompanyDrawer — 우측 400px 슬라이드 패널.
 *
 * Phase 5:
 *  - dev-mock fixture 의존 제거. STOCK_GET_DETAIL IPC 로 백엔드 응답 fetch.
 *  - "다음 어닝" 섹션 신설 (어닝 분석 코어 데이터).
 *  - 섹션 순서: 다음 어닝 → 기본 정보 → 30일 차트 → 어닝 히스토리 → AI 요약.
 *  - 관심종목 toggle 실 IPC 연결 (WATCHLIST_ADD/REMOVE) — broadcast 가 store 자동 갱신.
 *  - 실시간 가격 갱신 (PRICES_UPDATE → usePrices store 반영).
 *  - active=false (S&P 500 외) 종목은 어닝 섹션 "지원 외" placeholder 표시.
 *
 * 보안:
 *  - useDrawerStore.open 이 ticker 정규식 검증 후 set.
 *  - main 의 STOCK_GET_DETAIL handler 도 동일 정규식으로 재검증.
 *  - AI 요약 텍스트는 plain string, dangerouslySetInnerHTML 미사용.
 *
 * 트리거:
 *  - useDrawerStore.openTicker 가 non-null 인 동안 표시.
 *  - 닫기: X 버튼 / Esc / 오버레이 클릭.
 */
export default function CompanyDrawer() {
  const openTicker = useDrawerStore((s) => s.openTicker)
  const close = useDrawerStore((s) => s.close)
  const navigate = useNavigate()

  const { data, loading, error } = useCompanyDetail(openTicker)
  const { prices } = usePrices()
  const { items: watchlistItems } = useWatchlist()

  const isOpen = openTicker != null
  const livePrice = openTicker ? (prices[openTicker]?.currentPrice ?? null) : null
  const isWatched = openTicker
    ? watchlistItems.some((w) => w.ticker === openTicker)
    : false

  const onEnterTradingRoom = useCallback(
    (ticker: string) => {
      close()
      navigate(`/trading-room?ticker=${encodeURIComponent(ticker)}`)
    },
    [close, navigate],
  )

  return (
    <SidePanel
      open={isOpen}
      onClose={close}
      width={400}
      ariaLabel={openTicker ? `${openTicker} 상세 정보` : '회사 상세'}
    >
      {loading && <SkeletonContent ticker={openTicker ?? ''} onClose={close} />}
      {!loading && error && (
        <ErrorContent ticker={openTicker ?? ''} message={error.message} onClose={close} />
      )}
      {!loading && !error && data && (
        <DrawerContent
          data={data}
          livePrice={livePrice}
          isWatched={isWatched}
          onEnterTradingRoom={onEnterTradingRoom}
          onClose={close}
        />
      )}
      {!loading && !error && !data && openTicker && (
        // 정상 상태가 아닌데 응답도 비어있는 (mockApi fallback 등) edge case.
        <ErrorContent
          ticker={openTicker}
          message="상세 정보를 불러올 수 없습니다."
          onClose={close}
        />
      )}
    </SidePanel>
  )
}

/* ============================================================================
 * Drawer 본문 — 응답 도착 후 표시.
 * ========================================================================== */

interface DrawerContentProps {
  data: StockDetailResponsePayload
  /** PRICES_UPDATE push 로 받은 실시간 가격. 없으면 null → currentPrice fallback. */
  livePrice: number | null
  isWatched: boolean
  onEnterTradingRoom: (ticker: string) => void
  onClose: () => void
}

function DrawerContent({
  data,
  livePrice,
  isWatched,
  onEnterTradingRoom,
  onClose,
}: DrawerContentProps) {
  const supportsEarnings = data.active // S&P 500 편입 종목만 어닝 분석 지원
  const displayPrice = livePrice ?? data.currentPrice
  const isLive = livePrice != null

  // 차트 색은 첫/끝 가격 비교로 단순 판정 (백엔드가 별도 direction 미제공).
  const chartDirection = pickChartDirection(data.chart30d)

  return (
    <>
      <DrawerHeader
        ticker={data.ticker}
        companyName={data.companyName}
        active={data.active}
        partial={data.partial}
        isLive={isLive}
        onClose={onClose}
      />

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {/* 1. 다음 어닝 — earning 코어 섹션. nextEarning 없거나 active=false 면 처리 분기. */}
        {(data.nextEarning != null || !supportsEarnings) && (
          <Section title="다음 어닝">
            {!supportsEarnings ? (
              <UnsupportedEarningPlaceholder />
            ) : data.nextEarning ? (
              <NextEarningRow next={data.nextEarning} />
            ) : null}
          </Section>
        )}

        {/* 2. 기본 정보 */}
        <Section title="기본 정보">
          {data.basic ? (
            <BasicInfoGrid
              sector={data.sector}
              basic={data.basic}
            />
          ) : (
            <PlaceholderRow text="기본 정보가 아직 동기화되지 않았습니다." />
          )}
        </Section>

        {/* 3. 30일 일봉 */}
        <Section
          title="30일 일봉"
          right={
            data.chart30d.length > 0 ? (
              <div className="text-[10px] text-text-tertiary num">
                기간{' '}
                <span className={chartDirection === 'down' ? 'text-sell' : 'text-buy'}>
                  {formatPeriodChangeLabel(data.chart30d)}
                </span>
              </div>
            ) : null
          }
        >
          {data.chart30d.length > 0 ? (
            <ChartBlock
              chart30d={data.chart30d}
              displayPrice={displayPrice}
              direction={chartDirection}
            />
          ) : (
            <PlaceholderRow text="차트 데이터가 아직 동기화되지 않았습니다." />
          )}
        </Section>

        {/* 4. 최근 어닝 반응 */}
        <Section title="최근 어닝 반응">
          {!supportsEarnings ? (
            <UnsupportedEarningPlaceholder />
          ) : data.earningsHistory.length > 0 ? (
            <EarningsHistoryList rows={data.earningsHistory} />
          ) : (
            <PlaceholderRow text="아직 보고된 어닝 히스토리가 없습니다." />
          )}
        </Section>

        {/* 5. AI 분석 요약 — 본 phase 시점 항상 null. */}
        <Section title="AI 분석 요약" subtitle="· 최근 어닝콜" isLast>
          <p className="text-[12px] text-text-disabled leading-[1.6]">
            AI 분석 데이터 준비 중입니다.
          </p>
        </Section>
      </div>

      {/* Action bar */}
      <ActionBar
        ticker={data.ticker}
        isWatched={isWatched}
        onEnterTradingRoom={onEnterTradingRoom}
      />
    </>
  )
}

/* ============================================================================
 * 헤더 / 액션 바 / 섹션
 * ========================================================================== */

function DrawerHeader({
  ticker,
  companyName,
  active,
  partial,
  isLive,
  onClose,
}: {
  ticker: string
  companyName: string
  active: boolean
  partial: boolean
  isLive: boolean
  onClose: () => void
}) {
  return (
    <div className="h-12 px-3.5 flex items-center justify-between border-b border-border-subtle gap-2.5 shrink-0">
      <div className="flex items-center gap-2.5 min-w-0">
        <CompanyLogo ticker={ticker} size={28} />
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="num text-[18px] font-bold text-text-primary tracking-[0.01em]">
              {ticker}
            </span>
            {!active && (
              <span
                className="num text-[9px] font-bold tracking-[0.14em] inline-flex items-center
                           px-1.5 py-0.5 rounded-[3px]
                           bg-neutral/10 border border-neutral/30 text-neutral"
                title="S&P 500 외 종목"
              >
                지원 외
              </span>
            )}
            {isLive && (
              <span
                className="num text-[9px] font-bold tracking-[0.14em] inline-flex items-center gap-1
                           px-1.5 py-0.5 rounded-[3px]
                           bg-buy/10 border border-buy/30 text-buy"
              >
                <span className="w-1 h-1 rounded-full bg-buy animate-pulse" /> LIVE
              </span>
            )}
            {partial && (
              <span
                className="text-[9px] font-semibold tracking-[0.08em] inline-flex items-center
                           px-1.5 py-0.5 rounded-[3px]
                           bg-warning/10 border border-warning/30 text-warning"
                title="일부 데이터 동기화 중"
              >
                동기화 중
              </span>
            )}
          </div>
          <div className="text-[12px] text-text-secondary truncate">{companyName}</div>
        </div>
      </div>
      <button
        type="button"
        aria-label="닫기"
        onClick={onClose}
        className="w-7 h-7 grid place-items-center rounded-md
                   text-text-tertiary hover:bg-surface-2 hover:text-text-primary
                   transition-colors duration-100"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>
  )
}

function ActionBar({
  ticker,
  isWatched,
  onEnterTradingRoom,
}: {
  ticker: string
  isWatched: boolean
  onEnterTradingRoom: (ticker: string) => void
}) {
  const toggleWatchlist = useCallback(async () => {
    try {
      if (isWatched) {
        await ipc.invoke(IPC_CHANNELS.WATCHLIST_REMOVE, { ticker })
      } else {
        await ipc.invoke(IPC_CHANNELS.WATCHLIST_ADD, { ticker })
      }
      // store 는 WATCHLIST_UPDATE broadcast 로 자동 갱신 — 별도 setState 불요.
    } catch (e) {
      // optimistic update 미적용 — broadcast 가 빠름. 실패는 콘솔에만 남기고
      // 사용자 알림 toast 는 본 PR 범위 외.
      // eslint-disable-next-line no-console
      console.error('[CompanyDrawer] watchlist toggle 실패:', e)
    }
  }, [isWatched, ticker])

  return (
    <div className="px-4 py-3 flex gap-2 border-t border-border-subtle bg-surface-0 shrink-0">
      <button
        type="button"
        onClick={toggleWatchlist}
        className="flex-1 h-9 px-3.5 rounded-md
                   bg-surface-2 border border-border-strong text-text-primary
                   hover:bg-surface-3 text-[12px] font-semibold
                   inline-flex items-center justify-center gap-1.5"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          {isWatched ? <path d="M3 7h8" /> : <path d="M7 2v10M2 7h10" />}
        </svg>
        {isWatched ? '관심종목 제거' : '관심종목 추가'}
      </button>
      <button
        type="button"
        onClick={() => onEnterTradingRoom(ticker)}
        className="flex-[1.3] h-9 px-3.5 rounded-md
                   bg-accent-500 hover:bg-accent-600 text-accent-foreground
                   text-[12px] font-bold tracking-[0.04em]
                   inline-flex items-center justify-center gap-1.5"
      >
        TradingRoom 진입
        <svg
          width="12"
          height="12"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M3 7h8M8 4l3 3-3 3" />
        </svg>
      </button>
    </div>
  )
}

function Section({
  title,
  subtitle,
  right,
  isLast,
  children,
}: {
  title: string
  subtitle?: string
  right?: React.ReactNode
  isLast?: boolean
  children: React.ReactNode
}) {
  return (
    <section className={`px-4 py-3.5 ${isLast ? '' : 'border-b border-border-subtle'}`}>
      <div className="flex items-center justify-between mb-2.5">
        <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.14em]">
          {title}
          {subtitle && (
            <span className="ml-1 text-[9px] text-text-disabled tracking-[0.08em] normal-case">
              {subtitle}
            </span>
          )}
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

/* ============================================================================
 * 섹션 본문 컴포넌트
 * ========================================================================== */

function NextEarningRow({
  next,
}: {
  next: NonNullable<StockDetailResponsePayload['nextEarning']>
}) {
  const dDay = dDayLabel(next.scheduledAt)
  const absoluteLabel = formatScheduledAt(next.scheduledAt)

  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="num text-[16px] font-bold text-text-primary tabular-nums">
          {dDay}
        </span>
        <span className="text-[11px] text-text-secondary num tabular-nums">
          {absoluteLabel}
        </span>
        {next.confirmed ? (
          <span
            className="num text-[9px] font-bold tracking-[0.14em] inline-flex items-center
                       px-1.5 py-0.5 rounded-[3px]
                       bg-buy/10 border border-buy/30 text-buy"
          >
            확정
          </span>
        ) : (
          <span
            className="num text-[9px] font-bold tracking-[0.14em] inline-flex items-center
                       px-1.5 py-0.5 rounded-[3px]
                       bg-warning/10 border border-warning/30 text-warning"
          >
            미확정
          </span>
        )}
      </div>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-[12px]">
        <KV k="EPS 컨센서스" v={formatEpsEstimate(next.epsEstimate)} />
        <KV k="매출 컨센서스" v={formatRevenue(next.revenueEstimate)} />
      </dl>
    </div>
  )
}

function BasicInfoGrid({
  sector,
  basic,
}: {
  sector: string | null
  basic: NonNullable<StockDetailResponsePayload['basic']>
}) {
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-[12px]">
      <KV k="섹터" v={sector ?? '—'} kind="sub" />
      <KV k="시가총액" v={formatMarketCap(basic.marketCapUsd)} />
      <KV k="52주 고가" v={formatPrice(basic.high52w)} />
      <KV k="52주 저가" v={formatPrice(basic.low52w)} />
      <KV k="배당수익률" v={formatDividendYield(basic.dividendYield)} kind="sub" />
    </dl>
  )
}

function ChartBlock({
  chart30d,
  displayPrice,
  direction,
}: {
  chart30d: StockDetailResponsePayload['chart30d']
  displayPrice: number | null
  direction: 'up' | 'down' | 'neutral'
}) {
  // MiniLineChart 가 요구하는 ChartPoint shape ({date, price}) 로 변환.
  const points = chart30d.map((p) => ({ date: trimDateLabel(p.date), price: p.close }))
  const prices = points.map((p) => p.price)
  const dayChangeLabel = formatDayChangeLabel(chart30d)

  return (
    <>
      <div className="flex items-baseline gap-2 mb-1">
        <span className="num text-[14px] font-semibold text-text-primary tabular-nums">
          {formatPrice(displayPrice)}
        </span>
        {dayChangeLabel && (
          <span
            className={`num text-[11px] tabular-nums ${
              direction === 'down' ? 'text-sell' : 'text-buy'
            }`}
          >
            {dayChangeLabel}
          </span>
        )}
      </div>
      <div className="relative h-[100px] mt-1">
        <div
          className="absolute left-0 top-0 bottom-3.5 w-10 flex flex-col justify-between
                     num text-[9px] text-text-tertiary text-right pr-1"
        >
          {pickYTicks(prices).map((y) => (
            <span key={y}>${y.toFixed(0)}</span>
          ))}
        </div>
        <div className="absolute left-11 right-0.5 top-0 bottom-3.5">
          <MiniLineChart
            points={points}
            color={direction === 'down' ? 'sell' : 'accent'}
            viewWidth={320}
            viewHeight={86}
          />
        </div>
        <div
          className="absolute left-11 right-0.5 bottom-0 flex justify-between
                     num text-[9px] text-text-tertiary"
        >
          {pickXLabels(points).map((p, i) => (
            <span key={`${p.date}-${i}`}>{p.date}</span>
          ))}
        </div>
      </div>
    </>
  )
}

function EarningsHistoryList({
  rows,
}: {
  rows: StockDetailResponsePayload['earningsHistory']
}) {
  return (
    <table className="w-full border-collapse text-[11px] table-fixed">
      <thead>
        <tr>
          <Th align="left">분기</Th>
          <Th>EPS 예상</Th>
          <Th>EPS 실제</Th>
          <Th>Surprise</Th>
          <Th>당일</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.fiscalPeriodLabel}-${r.announcedAt}`}>
            <td className="num text-left text-text-primary text-[10px] font-medium tracking-[0.06em] py-1.5 px-1 border-b border-border-subtle">
              {r.fiscalPeriodLabel}
            </td>
            <td className="num text-right py-1.5 px-1 border-b border-border-subtle text-text-secondary tabular-nums">
              {formatEps(r.epsEstimate)}
            </td>
            <td className="num text-right py-1.5 px-1 border-b border-border-subtle text-text-secondary tabular-nums">
              {formatEps(r.epsActual)}
            </td>
            <PercentTd value={r.surprisePercent} />
            <PercentTd value={r.priceReactionPercent} />
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Th({
  children,
  align = 'right',
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
}) {
  return (
    <th
      className={`text-[9px] font-semibold text-text-tertiary uppercase tracking-[0.12em]
                  py-1.5 px-1 border-b border-border-subtle ${
                    align === 'left' ? 'text-left' : 'text-right'
                  }`}
    >
      {children}
    </th>
  )
}

function PercentTd({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <td className="num text-right py-1.5 px-1 border-b border-border-subtle tabular-nums text-text-tertiary">
        —
      </td>
    )
  }
  const cls = value > 0 ? 'text-buy' : value < 0 ? 'text-sell' : 'text-text-tertiary'
  return (
    <td
      className={`num text-right py-1.5 px-1 border-b border-border-subtle tabular-nums ${cls}`}
    >
      {formatDirectPercent(value, true)}
    </td>
  )
}

function KV({
  k,
  v,
  kind,
}: {
  k: string
  v: string
  kind?: 'sub'
}) {
  return (
    <>
      <dt className="text-[11px] text-text-tertiary">{k}</dt>
      <dd
        className={`num text-right tabular-nums ${
          kind === 'sub'
            ? 'text-text-secondary font-normal font-sans'
            : 'text-text-primary font-medium'
        }`}
      >
        {v}
      </dd>
    </>
  )
}

function PlaceholderRow({ text }: { text: string }) {
  return <p className="text-[11px] text-text-disabled py-1">{text}</p>
}

function UnsupportedEarningPlaceholder() {
  return (
    <p className="text-[11px] text-text-disabled leading-[1.6]">
      어닝 분석은 S&amp;P 500 종목만 지원합니다.
    </p>
  )
}

/* ============================================================================
 * 비-정상 상태
 * ========================================================================== */

function SkeletonContent({
  ticker,
  onClose,
}: {
  ticker: string
  onClose: () => void
}) {
  return (
    <>
      <div className="h-12 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2.5">
          <CompanyLogo ticker={ticker || 'NA'} size={28} />
          <span className="num text-[16px] font-semibold text-text-primary">
            {ticker || '—'}
          </span>
        </div>
        <button
          type="button"
          aria-label="닫기"
          onClick={onClose}
          className="w-7 h-7 grid place-items-center rounded-md text-text-tertiary
                     hover:bg-surface-2 hover:text-text-primary"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3.5 space-y-4">
        <SkeletonBlock heightPx={48} />
        <SkeletonBlock heightPx={80} />
        <SkeletonBlock heightPx={120} />
        <SkeletonBlock heightPx={60} />
      </div>
    </>
  )
}

function SkeletonBlock({ heightPx }: { heightPx: number }) {
  return (
    <div
      style={{ height: heightPx }}
      className="rounded-md bg-surface-2 animate-pulse"
      aria-hidden="true"
    />
  )
}

function ErrorContent({
  ticker,
  message,
  onClose,
}: {
  ticker: string
  message: string
  onClose: () => void
}) {
  return (
    <>
      <div className="h-12 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2.5">
          <CompanyLogo ticker={ticker || 'NA'} size={28} />
          <span className="num text-[16px] font-semibold text-text-primary">
            {ticker || '—'}
          </span>
        </div>
        <button
          type="button"
          aria-label="닫기"
          onClick={onClose}
          className="w-7 h-7 grid place-items-center rounded-md text-text-tertiary
                     hover:bg-surface-2 hover:text-text-primary"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>
      <div className="flex-1 flex items-center justify-center p-6 text-center">
        <p className="text-[12px] text-text-disabled leading-[1.6]">
          상세 정보를 불러올 수 없습니다.
          <br />
          <span className="text-[10px]">{message}</span>
        </p>
      </div>
    </>
  )
}

/** 가격 시계열 → 4단계 Y축 레이블. step=10 (수백 단위 가격 매칭). */
function pickYTicks(prices: number[]): number[] {
  return pickYTicksUtil(prices, 4, 10)
}

/** 시계열에서 5개 X축 레이블 균등 추출. */
function pickXLabels(points: { date: string }[]): { date: string }[] {
  return pickXLabelsUtil(points, 5)
}
