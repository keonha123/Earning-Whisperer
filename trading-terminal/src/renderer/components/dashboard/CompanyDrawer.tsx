import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SidePanel from '../common/SidePanel'
import CompanyLogo from '../common/CompanyLogo'
import MiniGauge from '../common/MiniGauge'
import EarningsHistoryTable from './EarningsHistoryTable'
import MiniLineChart from './MiniLineChart'
import { useDrawerStore } from '../../store/useDrawerStore'
import { companyDetailDevMock, type CompanyDetailFixture } from '../../fixtures/companyDetail.dev-mock'
// chartUtils 통합 (PR #4) — DashboardPage 와 중복이었던 pickXLabels/pickYTicks 추출.
// 30일 일봉은 수백 단위 가격이므로 step=10 으로 호출.
import { pickYTicks as pickYTicksUtil, pickXLabels as pickXLabelsUtil } from '../../lib/chartUtils'

/**
 * CompanyDrawer — 우측 400px 슬라이드 패널.
 *
 * 디자인 매칭: CompanyDrawer.html 전체.
 *
 * 데이터 소스:
 *  - 현재 PR: companyDetail.dev-mock 만 (DEV 가드).
 *  - 추후 PR: KIS_GET_COMPANY_DETAIL IPC 채널 도입 후 fetch.
 *
 * 보안:
 *  - useDrawerStore.open 이 ticker 정규식 검증 후 set.
 *  - AI 요약 텍스트는 plain string, dangerouslySetInnerHTML 미사용.
 *  - fixture 미존재 ticker 는 placeholder 표시 (디자인 캔버스에 fallback 정의는
 *    없으나, 가짜 데이터를 임의로 출력하지 않는 안전 fallback).
 *
 * 트리거:
 *  - useDrawerStore.openTicker 가 non-null 인 동안 표시.
 *  - 닫기: X 버튼 / Esc / 오버레이 클릭.
 */
export default function CompanyDrawer() {
  const openTicker = useDrawerStore((s) => s.openTicker)
  const close = useDrawerStore((s) => s.close)
  const navigate = useNavigate()

  const isOpen = openTicker != null
  // dev-mock 은 DEV 빌드에서만 의미. prod 에서는 lookup 실패 → placeholder.
  const detail: CompanyDetailFixture | undefined =
    openTicker && import.meta.env.DEV ? companyDetailDevMock[openTicker] : undefined

  return (
    <SidePanel
      open={isOpen}
      onClose={close}
      width={400}
      ariaLabel={openTicker ? `${openTicker} 상세 정보` : '회사 상세'}
    >
      {detail ? (
        <DrawerContent detail={detail} onEnterTradingRoom={(t) => {
          close()
          navigate(`/trading-room?ticker=${encodeURIComponent(t)}`)
        }} onClose={close} />
      ) : (
        <PlaceholderContent ticker={openTicker ?? ''} onClose={close} />
      )}
    </SidePanel>
  )
}

function DrawerContent({
  detail,
  onEnterTradingRoom,
  onClose,
}: {
  detail: CompanyDetailFixture
  onEnterTradingRoom: (ticker: string) => void
  onClose: () => void
}) {
  // 관심종목 toggle (UI 전용 — IPC 미존재).
  const [isWatched, setIsWatched] = useState(false)

  const directionColor = detail.chartCurrent.direction === 'up' ? 'accent' : 'sell'
  const biasColor =
    detail.ai.bias === 'BUY'
      ? 'accent'
      : detail.ai.bias === 'SELL'
        ? 'sell'
        : 'neutral'

  // AI 점수 라벨 → 0~1 범위 ratio (절대값 / 1) 으로 게이지.
  const aiAbs = Math.abs(parseFloat(detail.ai.avgScoreLabel.replace(/[^\d.\-]/g, ''))) || 0
  const aiRatio = Math.min(1, aiAbs)

  return (
    <>
      {/* Header */}
      <div className="h-12 px-3.5 flex items-center justify-between border-b border-border-subtle gap-2.5 shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <CompanyLogo
            ticker={detail.ticker}
            label={detail.logoLabel}
            bg={detail.logoBg}
            fg={detail.logoFg}
            size={28}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="num text-[18px] font-bold text-text-primary tracking-[0.01em]">
                {detail.ticker}
              </span>
              {detail.isLive && (
                <span
                  className="num text-[9px] font-bold tracking-[0.14em] inline-flex items-center gap-1
                             px-1.5 py-0.5 rounded-[3px]
                             bg-buy/10 border border-buy/30 text-buy"
                >
                  <span className="w-1 h-1 rounded-full bg-buy animate-pulse" /> LIVE
                </span>
              )}
            </div>
            <div className="text-[12px] text-text-secondary truncate">{detail.name}</div>
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

      {/* Scroll body */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {/* 기본 정보 */}
        <Section title="기본 정보">
          <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-[12px]">
            <KV k="섹터" v={detail.basic.sector} kind="sub" />
            <KV k="시가총액" v={detail.basic.marketCap} />
            <KV k="52주 고가" v={detail.basic.high52w} />
            <KV k="52주 저가" v={detail.basic.low52w} />
            <KV k="배당수익률" v={detail.basic.dividendYield} kind="sub" />
          </dl>
        </Section>

        {/* 30일 차트 */}
        <Section
          title="30일 일봉"
          right={
            <div className="text-[10px] text-text-tertiary num">
              기간{' '}
              <span className={detail.chartCurrent.direction === 'down' ? 'text-sell' : 'text-buy'}>
                {detail.chartCurrent.periodChangeLabel}
              </span>
            </div>
          }
        >
          <div className="flex items-baseline gap-2 mb-1">
            <span className="num text-[14px] font-semibold text-text-primary tabular-nums">
              {detail.chartCurrent.priceLabel}
            </span>
            <span
              className={`num text-[11px] tabular-nums ${
                detail.chartCurrent.direction === 'down' ? 'text-sell' : 'text-buy'
              }`}
            >
              {detail.chartCurrent.dayChangeLabel}
            </span>
          </div>
          <div className="relative h-[100px] mt-1">
            <div className="absolute left-0 top-0 bottom-3.5 w-10 flex flex-col justify-between
                            num text-[9px] text-text-tertiary text-right pr-1">
              {pickYTicks(detail.chart30d.map((p) => p.price)).map((y) => (
                <span key={y}>${y.toFixed(0)}</span>
              ))}
            </div>
            <div className="absolute left-11 right-0.5 top-0 bottom-3.5">
              <MiniLineChart
                points={detail.chart30d}
                color={directionColor as 'accent' | 'sell'}
                viewWidth={320}
                viewHeight={86}
              />
            </div>
            <div className="absolute left-11 right-0.5 bottom-0 flex justify-between
                            num text-[9px] text-text-tertiary">
              {pickXLabels(detail.chart30d).map((d) => (
                <span key={d}>{d}</span>
              ))}
            </div>
          </div>
        </Section>

        {/* 어닝 히스토리 */}
        <Section title="최근 어닝 반응">
          <EarningsHistoryTable rows={detail.earningsHistory} />
        </Section>

        {/* AI 요약 */}
        <Section
          title="AI 분석 요약"
          subtitle="· 최근 어닝콜"
          isLast
        >
          <p className="text-[12px] text-text-secondary leading-[1.6]">
            {detail.ai.summary}
          </p>
          <div
            className={`inline-flex items-center gap-1.5 mt-2.5 px-2.5 py-1 rounded
                        num text-[11px] font-semibold tracking-[0.02em]
                        ${
                          biasColor === 'accent'
                            ? 'bg-buy/10 border border-buy/30 text-buy'
                            : biasColor === 'sell'
                              ? 'bg-sell/10 border border-sell/30 text-sell'
                              : 'bg-neutral/10 border border-neutral/30 text-neutral'
                        }`}
          >
            <MiniGauge
              value={aiRatio}
              size={14}
              color={biasColor}
              showValue={false}
              ariaLabel={`평균 AI 점수 ${detail.ai.avgScoreLabel}`}
            />
            평균 AI 점수 <b className="font-bold">{detail.ai.avgScoreLabel}</b> ·{' '}
            {detail.ai.bias === 'BUY' ? 'BUY 우세' : detail.ai.bias === 'SELL' ? 'SELL 우세' : '중립'}
          </div>
        </Section>
      </div>

      {/* Action bar */}
      <div className="px-4 py-3 flex gap-2 border-t border-border-subtle bg-surface-0 shrink-0">
        <button
          type="button"
          onClick={() => {
            // TODO(impl): WATCHLIST_ADD / WATCHLIST_REMOVE IPC 추가 후 연결.
            //   - main 측 핸들러에서 ticker 정규식 + 사용자 권한 검증 필요.
            setIsWatched((v) => !v)
          }}
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
            {isWatched ? (
              <path d="M3 7h8" />
            ) : (
              <path d="M7 2v10M2 7h10" />
            )}
          </svg>
          {isWatched ? '관심종목 제거' : '관심종목 추가'}
        </button>
        <button
          type="button"
          onClick={() => onEnterTradingRoom(detail.ticker)}
          className="flex-[1.3] h-9 px-3.5 rounded-md
                     bg-accent-500 hover:bg-accent-600 text-accent-foreground
                     text-[12px] font-bold tracking-[0.04em]
                     inline-flex items-center justify-center gap-1.5"
        >
          TradingRoom 진입
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 7h8M8 4l3 3-3 3" />
          </svg>
        </button>
      </div>
    </>
  )
}

function PlaceholderContent({
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
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>
      <div className="flex-1 flex items-center justify-center p-6 text-center">
        <p className="text-[12px] text-text-disabled leading-[1.6]">
          상세 정보를 불러올 수 없습니다.
          <br />
          <span className="text-[10px]">
            (백엔드 연동 전 — 향후 PR 에서 KIS_GET_COMPANY_DETAIL 추가 예정)
          </span>
        </p>
      </div>
    </>
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
    <section
      className={`px-4 py-3.5 ${isLast ? '' : 'border-b border-border-subtle'}`}
    >
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

function KV({ k, v, kind }: { k: string; v: string; kind?: 'sub' }) {
  return (
    <>
      <dt className="text-[11px] text-text-tertiary">{k}</dt>
      <dd
        className={`num text-right tabular-nums ${
          kind === 'sub' ? 'text-text-secondary font-normal font-sans' : 'text-text-primary font-medium'
        }`}
      >
        {v}
      </dd>
    </>
  )
}

/** 가격 시계열 → 4단계 Y축 레이블 (디자인 캔버스: $130/$120/$110/$100). */
function pickYTicks(prices: number[]): number[] {
  return pickYTicksUtil(prices, 4, 10)
}

/** 시계열에서 5개 X축 레이블 균등 추출 (디자인 캔버스: 03-20 / 03-28 / 04-05 / 04-13 / 04-20). */
function pickXLabels(points: { date: string }[]): string[] {
  return pickXLabelsUtil(points, 5).map((p) => p.date)
}
