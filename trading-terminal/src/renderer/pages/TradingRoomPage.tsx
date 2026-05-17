import { useMemo, useState } from 'react'
import { useTradingStore, type SignalFeedItem } from '../store/useTradingStore'
import { useUserStore } from '../store/useUserStore'
import { usePortfolioStore } from '../store/usePortfolioStore'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import ModeSelector from '../components/common/ModeSelector'
import EmaChart from '../components/trading/EmaChart'
import SignalFeed from '../components/trading/SignalFeed'
import STTScriptPanel from '../components/trading/STTScriptPanel'
import OrderBar, { type OrderBarSubmitPayload } from '../components/trading/OrderBar'
import TradingRoomHeader from '../components/trading/TradingRoomHeader'
import { showIpcErrorToast } from '../components/common/Toast'
import {
  sttTranscriptDevMock,
  type TranscriptLine,
} from '../fixtures/sttTranscript.dev-mock'
import {
  liveSessionDevMock,
  livePriceSeriesDevMock,
  type PricePoint,
} from '../fixtures/liveSession.dev-mock'
import { useLiveTranscript } from '../hooks/useLiveTranscript'
import type { TranscriptSegment } from '../store/useTranscriptStore'
// liveAiScoreSeriesDevMock 은 향후 EmaChart 가 보라색 AI 점수 라인으로 재활용 예정.
// fixture export 자체는 유지하되, 본 페이지에서는 사용처가 없어 import 하지 않는다
// (tsconfig 의 noUnusedLocals 가 켜지면 빌드 실패 가능).

type SignalFilter = 'ALL' | 'BUY' | 'SELL' | 'FAILED'

const TIMEFRAMES = ['1m', '5m', '1H', '1D', '1W', '1M'] as const
type Timeframe = (typeof TIMEFRAMES)[number]

const EMPTY_TRANSCRIPT: readonly TranscriptLine[] = []
const EMPTY_PRICES: readonly PricePoint[] = []

export default function TradingRoomPage() {
  const { mode, setMode, signalHistory, activeSignal } = useTradingStore()
  const { plan, settings, setSettings } = useUserStore()
  const orderableCash = usePortfolioStore((s) => s.orderableCash)

  // ── DEV-only fixtures (prod 빌드에서는 빈 배열/null) ─────────────────────────
  const priceSeries = import.meta.env.DEV ? livePriceSeriesDevMock : EMPTY_PRICES
  const liveMeta = import.meta.env.DEV ? liveSessionDevMock : null

  // ticker / 회사명 / 현재가 / WPM 우선순위:
  //  1) activeSignal (실데이터)
  //  2) liveMeta (DEV fixture)
  //  3) null
  const ticker = activeSignal?.ticker ?? liveMeta?.ticker ?? null

  // ── 실시간 트랜스크립트 (Contract 4.5 STOMP /topic/transcript/{ticker}) ──────
  // ticker 변경 시 자동 SUBSCRIBE/UNSUBSCRIBE. segment 는 store 에 누적된다.
  const { segments: liveSegments, endedCallIds } = useLiveTranscript(ticker)

  // segment → TranscriptLine 어댑터 (STTScriptPanel 의 기존 인터페이스 보존).
  const liveTranscript = useMemo<readonly TranscriptLine[]>(
    () => liveSegments.map(toTranscriptLine),
    [liveSegments],
  )

  // DEV 환경 + store 가 비어있을 때 fixture 폴백 (안전망 — backend 미가동 시).
  // - prod 빌드: 항상 store 데이터 또는 빈 배열 (fixture 미접근).
  // - DEV: 실데이터 도착 즉시 fixture 자동 대체.
  const transcript: readonly TranscriptLine[] =
    liveTranscript.length > 0
      ? liveTranscript
      : import.meta.env.DEV
        ? sttTranscriptDevMock
        : EMPTY_TRANSCRIPT

  // 활성 callId — 가장 최근 segment 의 callId. 없으면 null.
  const activeCallId =
    liveSegments.length > 0
      ? liveSegments[liveSegments.length - 1].callId
      : null

  // LIVE 판정 (Contract 4.5 반영):
  //  - 활성 트랜스크립트 세션이 있고 (activeCallId 존재),
  //  - 그 callId 가 endedCallIds 에 포함되지 않을 때 LIVE.
  //  - fallback: 실데이터 없는 DEV 환경에서는 기존 activeSignal 기반 LIVE 판정 유지.
  const isLive =
    activeCallId != null
      ? !endedCallIds.has(activeCallId)
      : activeSignal != null
  const companyName = liveMeta?.companyName ?? null
  const currentPrice = liveMeta?.currentPrice ?? null
  const changePercent = liveMeta?.changePercent
  const sessionLabel = liveMeta?.sessionLabel ?? null
  // 경과 시간 라벨 — fixture 정적값 ("25:14"). 실시간 헬퍼는 본 PR 범위 외.
  const elapsedLabel = liveMeta?.elapsedLabel ?? null

  // ── 신호 필터 (로컬 state) ────────────────────────────────────────────────────
  const [filter, setFilter] = useState<SignalFilter>('ALL')

  const filteredSignals = useMemo(
    () => filterSignals(signalHistory, filter),
    [signalHistory, filter],
  )

  const counts = useMemo(() => countByCategory(signalHistory), [signalHistory])

  // ── 타임프레임 (UI only — fixture 단일 시계열만 표시) ──────────────────────────
  const [timeframe, setTimeframe] = useState<Timeframe>('1D')

  async function handleModeChange(newMode: typeof mode) {
    try {
      await ipc.invoke(IPC_CHANNELS.SETTINGS_UPDATE, {
        tradingMode: newMode,
        maxBuyRatio: settings.maxBuyRatio,
        maxHoldingRatio: settings.maxHoldingRatio,
        cooldownMinutes: settings.cooldownMinutes,
      })
      setMode(newMode)
      setSettings({ tradingMode: newMode })
    } catch (e) {
      console.error('모드 변경 실패:', e)
      showIpcErrorToast(e)
    }
  }

  async function handleOrderSubmit(payload: OrderBarSubmitPayload) {
    if (!ticker) return
    // TODO(impl): 수동 주문 IPC — 현재 KIS_PLACE_ORDER 는 TradeSignal 형식만 받으므로
    //   manual order 전용 채널 (e.g. KIS_PLACE_MANUAL_ORDER) 이 필요하다.
    //   별도 PR 에서 main 측 핸들러 추가 + qty/price/side 시그니처 정의 후 연결.
    //
    //   안전 장치:
    //   - prod 빌드에서는 OrderBar 의 disabled prop 으로 입력 자체를 막고 있으므로 본
    //     함수가 호출될 가능성은 사실상 없으나, 방어적으로 noop 처리.
    //   - DEV 빌드에서는 콘솔로 호출 사실만 남긴다. ticker/qty/price 같은 사용자 입력
    //     페이로드는 DevTools 로그에 그대로 노출되지 않도록 redact (prod DevTools 우발
    //     활성화 시 정보 누출 방지).
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.info('[TradingRoom] manual order DEV noop:', {
        side: payload.side,
        qtyClass: payload.qty > 100 ? 'large' : 'small',
        orderType: payload.price == null ? 'market' : 'limit',
      })
    }
  }

  return (
    <div className="flex flex-col h-full -m-6">
      {/* ── 페이지 내부 상단 헤더 행 (LIVE + ticker + 종목정보 + 메타 + ModeSelector) */}
      <div className="px-4 flex items-center justify-between gap-3 border-b border-border-subtle bg-surface-0">
        <TradingRoomHeader
          ticker={ticker}
          companyName={companyName}
          sessionLabel={sessionLabel}
          elapsedLabel={elapsedLabel}
          wpm={liveMeta?.wpm}
          isLive={isLive}
        />
        <div className="w-72 shrink-0">
          <ModeSelector
            currentMode={mode}
            userPlan={plan}
            onChange={handleModeChange}
            size="compact"
          />
        </div>
      </div>

      {/* ── 3-column body ───────────────────────────────────────────────────────── */}
      <div
        className="flex-1 grid gap-3 p-3 min-h-0"
        style={{ gridTemplateColumns: '35fr 40fr 25fr' }}
      >
        {/* LEFT 35% — STT 스크립트 */}
        <STTScriptPanel
          transcript={transcript}
          isLive={isLive && transcript.length > 0}
          wpm={liveMeta?.wpm}
        />

        {/* MIDDLE 40% — 가격 차트 (상) + AI 점수 차트 (하) */}
        <section className="card p-0 flex flex-col overflow-hidden min-h-0">
          <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
            <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
              <span className="w-2 h-2 rounded-sm bg-accent-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
              {ticker ?? '—'} · 실시간 차트
            </span>
            <TimeframeToggle value={timeframe} onChange={setTimeframe} />
          </div>

          <div className="flex-1 flex flex-col min-h-0">
            {/* 가격 pane */}
            <ChartPane
              kind="price"
              priceLabel={liveMeta?.currentPriceLabel ?? '—'}
              changePercent={changePercent}
              changeAmount={liveMeta?.changeAmount}
              volumeLabel={liveMeta?.volumeLabel}
              marketSession={liveMeta?.marketSession}
              series={priceSeries}
              isLive={isLive}
            />

            {/* AI Score pane (기존 EmaChart 재사용 — 신호 마커 포함) */}
            <div className="flex-1 flex flex-col min-h-0 border-t border-border-subtle bg-surface-1">
              <div className="h-[34px] px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0 gap-2">
                <span className="text-[10.5px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
                  <span
                    className="w-2 h-2 rounded-sm"
                    // design-canvas: AI score purple (#a78bfa, violet-400) — 디자인 시스템에
                    // 등록되지 않은 신규 색. 본 PR 에서는 토큰화 보류 (별도 PR 에서 ai-* 토큰
                    // 정식 정의 후 일괄 치환 예정).
                    style={{ background: '#a78bfa', boxShadow: '0 0 8px rgba(167,139,250,.5)' }}
                  />
                  AI 점수 차트
                </span>
                <div className="flex items-center gap-2.5">
                  <span
                    className="num text-sm font-bold tabular-nums"
                    // design-canvas: AI score purple (violet-400) — 토큰화 보류 사유 위와 동일.
                    style={{ color: '#a78bfa', letterSpacing: '-0.01em' }}
                  >
                    {activeSignal
                      ? formatSigned(activeSignal.ai_score)
                      : liveMeta
                        ? formatSigned(liveMeta.currentAiScore)
                        : '—'}
                  </span>
                  {(activeSignal || liveMeta) && (
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold tracking-[0.08em] border"
                      // design-canvas: AI score purple chip (bg/border 는 violet-400 alpha,
                      // text 는 violet-300 #c4b5fd). 토큰화 보류 사유 위와 동일.
                      style={{
                        background: 'rgba(167,139,250,0.14)',
                        color: '#c4b5fd',
                        borderColor: 'rgba(167,139,250,0.35)',
                      }}
                    >
                      {activeSignal?.action === 'SELL' || liveMeta?.aiDirection === 'SELL'
                        ? '▼ SELL'
                        : '▲ BUY'}
                      {liveMeta && ` · ${liveMeta.aiStrength}`}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex-1 min-h-0 p-2">
                <EmaChart signalHistory={signalHistory} />
              </div>
            </div>
          </div>
        </section>

        {/* RIGHT 25% — 신호 피드 + 필터 칩 */}
        <section className="card p-0 flex flex-col overflow-hidden min-h-0">
          <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
            <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
              신호 피드 ·{' '}
              <span className="num text-text-primary tracking-normal normal-case">
                {signalHistory.length}
              </span>
            </span>
            <span className="num text-[11px] text-text-tertiary">auto</span>
          </div>

          {/* 필터 칩 4개 */}
          <div className="flex gap-1 px-2.5 pt-2 pb-1 shrink-0">
            <FilterChip
              label="전체"
              count={counts.total}
              active={filter === 'ALL'}
              onClick={() => setFilter('ALL')}
            />
            <FilterChip
              label="BUY"
              count={counts.buy}
              active={filter === 'BUY'}
              onClick={() => setFilter('BUY')}
            />
            <FilterChip
              label="SELL"
              count={counts.sell}
              active={filter === 'SELL'}
              onClick={() => setFilter('SELL')}
            />
            <FilterChip
              label="FAILED"
              count={counts.failed}
              active={filter === 'FAILED'}
              onClick={() => setFilter('FAILED')}
            />
          </div>

          <div className="flex-1 overflow-y-auto min-h-0">
            <SignalFeed items={filteredSignals} />
          </div>
        </section>
      </div>

      {/* ── 하단 80px 고정 OrderBar ─────────────────────────────────────────────── */}
      {/*
        prod 빌드에서는 manual order IPC (KIS_PLACE_MANUAL_ORDER) 가 아직 없으므로
        OrderBar 자체를 명시적 disabled 로 표시한다 (silent noop 회피 — 사용자가
        클릭 시 "주문된 줄" 알 수 없는 상태 방지).
        DEV 빌드에서는 정상 입력 + DEV noop 로그.
      */}
      <OrderBar
        ticker={ticker}
        currentPrice={currentPrice}
        changePercent={changePercent}
        orderableCash={orderableCash}
        mode={mode}
        onSubmit={handleOrderSubmit}
        disabled={!import.meta.env.DEV}
        disabledLabel="수동 주문은 다음 업데이트에서 지원됩니다"
      />
    </div>
  )
}

/** ─────────────────────────────────────────────────────────────────────────────
 * 내부 헬퍼 컴포넌트 / 함수
 * ──────────────────────────────────────────────────────────────────────────── */

interface FilterChipProps {
  label: string
  count: number
  active: boolean
  onClick: () => void
}

function FilterChip({ label, count, active, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        'text-[10px] px-2 py-[3px] rounded border tracking-[0.06em] transition-colors duration-100 ' +
        (active
          ? 'bg-surface-2 text-text-primary border-border-strong'
          : 'bg-transparent text-text-tertiary border-border-subtle hover:text-text-primary')
      }
    >
      {label} <span className="num text-[10px] ml-0.5">{count}</span>
    </button>
  )
}

interface TimeframeToggleProps {
  value: Timeframe
  onChange: (tf: Timeframe) => void
}

function TimeframeToggle({ value, onChange }: TimeframeToggleProps) {
  return (
    <div
      role="tablist"
      aria-label="차트 타임프레임"
      className="inline-flex bg-surface-2 border border-border-subtle rounded p-px"
    >
      {TIMEFRAMES.map((tf) => {
        const active = tf === value
        return (
          <button
            key={tf}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tf)}
            className={
              'num px-2.5 py-[3px] rounded-[3px] text-[10.5px] font-semibold tracking-[0.04em] ' +
              (active
                ? 'text-accent-300 bg-accent-500/[0.16] shadow-[inset_0_0_0_1px_rgba(16,185,129,0.4)]'
                : 'text-text-tertiary hover:text-text-secondary')
            }
          >
            {tf}
          </button>
        )
      })}
    </div>
  )
}

interface ChartPaneProps {
  kind: 'price'
  priceLabel: string
  changePercent?: number
  changeAmount?: number
  volumeLabel?: string
  marketSession?: 'REGULAR' | 'AFTER_HOURS' | 'PRE_MARKET'
  series: readonly PricePoint[]
  isLive: boolean
}

/**
 * ChartPane (price) — 디자인 캔버스의 mid-pane price 영역.
 *
 * SVG + fixture (PR #3 MiniLineChart 패턴 일관). lightweight-charts 미사용 —
 * 가격 차트는 단순 라인이고, 실시간 IPC 가 정의되기 전까지는 fixture 만 표시한다.
 *
 * NaN/Infinity 가드: validPoints 필터링 — 결측치가 섞이면 SVG path 가 깨진다
 * (MiniLineChart 와 동일 패턴).
 */
function ChartPane({
  priceLabel,
  changePercent,
  changeAmount,
  volumeLabel,
  marketSession,
  series,
  isLive,
}: ChartPaneProps) {
  const VIEW_W = 500
  const VIEW_H = 130
  const PAD_TOP = 8
  const PAD_BOTTOM = 22

  const { linePath, areaPath, lastX, lastY, hasData } = useMemo(() => {
    const valid = series.filter((p) => Number.isFinite(p.price))
    if (valid.length === 0) {
      return { linePath: '', areaPath: '', lastX: 0, lastY: 0, hasData: false }
    }
    const prices = valid.map((p) => p.price)
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const range = max - min || 1
    const drawH = VIEW_H - PAD_TOP - PAD_BOTTOM
    const stepX = valid.length > 1 ? VIEW_W / (valid.length - 1) : 0

    const coords = valid.map((pt, i) => {
      const x = i * stepX
      const y = PAD_TOP + ((max - pt.price) / range) * drawH
      return { x, y }
    })
    const lp = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(' ')
    const last = coords[coords.length - 1]
    const ap = lp + ` L${last.x.toFixed(2)},${VIEW_H} L0,${VIEW_H} Z`
    return { linePath: lp, areaPath: ap, lastX: last.x, lastY: last.y, hasData: true }
  }, [series])

  // Y축 라벨 (4단계, 최고 → 최저).
  const yTicks = useMemo(() => {
    const valid = series.filter((p) => Number.isFinite(p.price))
    if (valid.length === 0) return []
    const prices = valid.map((p) => p.price)
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const slice = (max - min) / 4
    return [max, max - slice, max - slice * 2, max - slice * 3, min]
  }, [series])

  // X축 라벨 (5개 균등 시간).
  const xTicks = useMemo(() => {
    if (series.length === 0) return [] as string[]
    if (series.length <= 6) return series.map((p) => p.time)
    const out: string[] = []
    for (let i = 0; i < 6; i++) {
      const idx = Math.round((i * (series.length - 1)) / 5)
      out.push(series[idx].time)
    }
    return out
  }, [series])

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-surface-1 relative">
      {/* pane-hd */}
      <div className="h-[34px] px-3.5 flex items-center border-b border-border-subtle shrink-0 gap-2.5">
        <span className="num text-[13px] font-semibold text-text-primary">{priceLabel}</span>
        {changePercent != null && Number.isFinite(changePercent) && (
          <span
            className={`num text-[11px] font-semibold px-1.5 py-px rounded ${
              changePercent >= 0 ? 'bg-buy/[0.14] text-buy' : 'bg-sell/[0.14] text-sell'
            }`}
          >
            {changePercent >= 0 ? '+' : ''}{changePercent.toFixed(2)}%
          </span>
        )}
        {changeAmount != null && Number.isFinite(changeAmount) && (
          <span className="num text-[11px] text-text-tertiary">
            {changeAmount >= 0 ? '+' : '-'}${Math.abs(changeAmount).toFixed(2)}
          </span>
        )}
        {volumeLabel && (
          <span className="text-[10.5px] text-text-tertiary">Vol {volumeLabel}</span>
        )}
        {marketSession && (
          <span className="num text-[10.5px] text-text-tertiary ml-auto">
            {marketSession === 'AFTER_HOURS'
              ? 'After Hours'
              : marketSession === 'PRE_MARKET'
                ? 'Pre Market'
                : 'Regular'}
          </span>
        )}
      </div>

      {/* chart-wrap */}
      <div className="relative flex-1 min-h-0 px-3.5 pt-2 pb-[22px]">
        {/* Y축 */}
        <div
          className="absolute left-0.5 top-2 w-9 flex flex-col justify-between
                     num text-[8.5px] text-text-tertiary text-right pr-1"
          style={{ bottom: '22px' }}
        >
          {yTicks.map((y, i) => (
            <span key={i}>${y.toFixed(0)}</span>
          ))}
        </div>

        {/* SVG */}
        {hasData ? (
          <svg
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            preserveAspectRatio="none"
            className="absolute"
            style={{ left: 42, right: 14, top: 8, bottom: 22, width: 'calc(100% - 56px)', height: 'calc(100% - 30px)' }}
            role="img"
            aria-label="가격 추이 차트"
          >
            {/* grid */}
            <line x1="0" y1="15" x2={VIEW_W} y2="15" stroke="#1e2738" strokeWidth="1" />
            <line x1="0" y1="50" x2={VIEW_W} y2="50" stroke="#1e2738" strokeWidth="1" />
            <line x1="0" y1="85" x2={VIEW_W} y2="85" stroke="#1e2738" strokeWidth="1" />
            <line x1="0" y1="115" x2={VIEW_W} y2="115" stroke="#1e2738" strokeWidth="1" />

            <path d={areaPath} fill="rgba(16,185,129,0.10)" />
            <path
              d={linePath}
              fill="none"
              stroke="#10b981"
              strokeWidth="1.5"
              strokeLinejoin="round"
            />
            <circle cx={lastX} cy={lastY} r="10" fill="rgba(16,185,129,0.18)" />
            <circle
              cx={lastX}
              cy={lastY}
              r="4"
              fill="#10b981"
              stroke="#0b1017"
              strokeWidth="2"
            />
          </svg>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-text-disabled text-xs">
            {isLive ? '실시간 데이터 동기화 중' : '데이터 없음'}
          </div>
        )}

        {/* X축 */}
        <div
          className="absolute flex justify-between num text-[8.5px] text-text-tertiary"
          style={{ left: 42, right: 14, bottom: 6 }}
        >
          {xTicks.map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

/** ─────────────────────────────────────────────────────────────────────────────
 * 순수 함수
 * ──────────────────────────────────────────────────────────────────────────── */

function filterSignals(items: SignalFeedItem[], filter: SignalFilter): SignalFeedItem[] {
  if (filter === 'ALL') return items
  if (filter === 'FAILED') return items.filter((s) => s.status === 'FAILED')
  return items.filter((s) => s.action === filter)
}

interface SignalCounts {
  total: number
  buy: number
  sell: number
  failed: number
}

function countByCategory(items: SignalFeedItem[]): SignalCounts {
  let buy = 0
  let sell = 0
  let failed = 0
  for (const s of items) {
    if (s.action === 'BUY') buy++
    else if (s.action === 'SELL') sell++
    if (s.status === 'FAILED') failed++
  }
  return { total: items.length, buy, sell, failed }
}

function formatSigned(v: number): string {
  if (!Number.isFinite(v)) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(2)
}

/**
 * TranscriptSegment (실시간 store) → TranscriptLine (STTScriptPanel UI 모델).
 *
 *  - id: `${callId}-${sequence}` — 동일 어닝콜 내 sequence 단조 증가가 보장하는 unique key.
 *  - timestamp: startMs 를 "mm:ss" 로 포맷 (어닝콜 시작 기준 경과 시간).
 *  - speaker: 누락 시 빈 문자열 ("[mm:ss] · ·" 가 되지 않도록 fallback).
 *  - ai_score: 별도 시그널 채널 (/user/queue/signals) 에서 매핑되므로 어댑터에서는 undefined.
 */
function toTranscriptLine(seg: TranscriptSegment): TranscriptLine {
  return {
    id: `${seg.callId}-${seg.sequence}`,
    timestamp: formatMmSs(seg.startMs),
    speaker: seg.speaker ?? '',
    text: seg.text,
    ai_score: undefined,
  }
}

/** ms → "mm:ss" 포맷. 음수/NaN/Infinity 는 "00:00" 으로 fallback. */
function formatMmSs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '00:00'
  const totalSeconds = Math.floor(ms / 1000)
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
