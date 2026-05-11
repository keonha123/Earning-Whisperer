import { useEffect, useMemo, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useTradingStore } from '../store/useTradingStore'
import { usePortfolioStore } from '../store/usePortfolioStore'
import { useUserStore } from '../store/useUserStore'
import { useDrawerStore } from '../store/useDrawerStore'

import ModeSelector from '../components/common/ModeSelector'
import PortfolioCard from '../components/portfolio/PortfolioCard'

import MarketStrip from '../components/dashboard/MarketStrip'
import EarningsTimeline from '../components/dashboard/EarningsTimeline'
import HoldingsTable, { type HoldingsTableRow } from '../components/dashboard/HoldingsTable'
import MiniLineChart from '../components/dashboard/MiniLineChart'

import { marketIndexDevMock } from '../fixtures/marketIndex.dev-mock'
import { useMarketIndices } from '../hooks/useMarketIndices'
import { useWatchlist } from '../hooks/useWatchlist'
import { usePrices } from '../hooks/usePrices'
import { earningsTimelineDevMock } from '../fixtures/earningsTimeline.dev-mock'
// watchlistDevMock 은 이번 PR 에서 제거 (실 IPC 사용). holdings.dev-mock 파일 자체는 보존.
import { holdingsDevMock } from '../fixtures/holdings.dev-mock'
import { companyDetailDevMock } from '../fixtures/companyDetail.dev-mock'
import { useNavigate } from 'react-router-dom'
import type { EarningsTimelineData } from '../../lib/types/earningsTimeline'
// chartUtils 통합 (PR #4) — 동일 시그니처 함수가 CompanyDrawer 와 중복이었다.
// step=100 (수십만~수백만 단위 자산 차트) 으로 호출.
import { pickYTicks as pickYTicksUtil, pickXLabels as pickXLabelsUtil } from '../lib/chartUtils'
import { showIpcErrorToast } from '../components/common/Toast'
import { useConnectionStore } from '../store/useConnectionStore'
import { isIpcError } from '../../lib/types/ipcError'

/**
 * DashboardPage — 4-Row 레이아웃.
 *
 *  Row 0 (헤더): 제목 + 마지막 동기화 + 동기화 버튼 + ModeSelector.
 *  Row 1 (MarketStrip): 글로벌 지수 5종 (DEV 가드).
 *  Row 2 (Portfolio + AssetChart): PortfolioCard + 30D SVG 차트.
 *  Row 3 (Holdings + Earnings): HoldingsTable + EarningsTimeline.
 *
 *  Drawer: CompanyDrawer 는 AppLayout 에 전역 단일 mount (PR #4 리뷰 반영).
 *    페이지에서는 useDrawerStore.open(ticker) 호출만으로 트리거.
 *
 * 보존 동작:
 *  - 마운트 시 KIS_GET_BALANCE 1회.
 *  - 모드 변경 시 SETTINGS_UPDATE.
 *  - PortfolioCard 컴포넌트 (PR #1 잔존) 그대로 사용.
 *  - SignalFeed 는 import 제거 — PR #4 TradingRoom 에서 사용 예정.
 */
export default function DashboardPage() {
  const { mode, setMode } = useTradingStore()
  const {
    orderableCash,
    totalCash,
    holdings: storeHoldings,
    lastSyncedAt,
    isSyncing,
    error,
    balanceFetchError,
    setBalance,
    startSync,
    setSyncing,
    setError,
    setBalanceFetchError,
  } = usePortfolioStore()
  const { plan, settings, setSettings, clear: clearUser } = useUserStore()
  const setAuthenticated = useConnectionStore((s) => s.setAuthenticated)

  const openDrawer = useDrawerStore((s) => s.open)
  const navigate = useNavigate()

  // AUTH_EXPIRED toast 의 "다시 로그인" 클릭 핸들러.
  // KIS_GET_BALANCE 등 인증 만료 시 호출됨 — 인증 store/유저 store 정리 후 라우팅.
  function handleAuthExpiredNavigate(): void {
    setAuthenticated(false)
    clearUser()
    navigate('/auth')
  }

  useEffect(() => {
    syncBalance()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function syncBalance() {
    startSync()
    try {
      const balance = await ipc.invoke<{
        orderableCash: number
        totalCash: number
        holdings: any[]
      }>(IPC_CHANNELS.KIS_GET_BALANCE)
      setBalance(balance.orderableCash, balance.totalCash, balance.holdings)

      // main PricePoller 에 보유종목 ticker 변경 통보 — 빈 배열도 보내서
      // 보유 0개로 줄어든 케이스도 폴링 대상에서 제외되게 함.
      const tickers = (balance.holdings ?? []).map((h: any) => h.ticker)
      try {
        await ipc.invoke(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE, { tickers })
      } catch (e) {
        console.error('[DashboardPage] HOLDINGS_TICKERS_UPDATE 실패:', e)
        showIpcErrorToast(e)
      }
    } catch (e: unknown) {
      console.error('잔고 조회 실패:', e)
      // 기존 인라인 에러 배지(setError) 는 유지 + toast 추가.
      // AUTH_EXPIRED 의 경우 "다시 로그인" 액션으로 라우팅 정리.
      setError('잔고 조회에 실패했습니다. KIS 토큰 상태를 확인해주세요.')
      // F-2: store 에 IpcError 정규화 기록 → PortfolioCard / HoldingsTable 의
      // stale overlay 가 자동으로 mount. 성공 응답 도착 시 setBalance 가 자동 clear.
      setBalanceFetchError(e)
      showIpcErrorToast(e, {
        onNavigate:
          isIpcError(e) && e.code === 'AUTH_EXPIRED'
            ? handleAuthExpiredNavigate
            : undefined,
      })
    } finally {
      setSyncing(false)
    }
  }

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

  // 시세 폴링 캐시 — main PricePoller 가 ticker 별 KIS 가격을 1차 캐싱.
  // useEffect 로 PRICES_GET 1회 + PRICES_UPDATE 구독 시작.
  const { prices } = usePrices()

  // Holdings 평가금액 계산: poller 가 받은 가격이 있으면 우선, 없으면 store fallback.
  const totalAsset =
    totalCash +
    storeHoldings.reduce((sum, h) => {
      const live = prices[h.ticker]?.currentPrice
      const px = live ?? h.currentPrice
      return sum + h.qty * px
    }, 0)

  // Holdings/Watchlist 표시 행:
  //  - 실제 store 의 holdings 우선 사용. fixture 의 메타데이터 (회사명/로고색) 와 매핑.
  //  - store 가 비어있는 DEV 환경에서는 fixture rows 자체를 표시.
  //  - prod 에서 fixture 미존재 ticker 는 logoBg/fg 미설정 → CompanyLogo fallback.
  //  - currentPrice/평가% 는 PricePoller 가 push 한 가격을 우선 사용.
  const holdingRows: HoldingsTableRow[] = useMemo(() => {
    const getEarningsBadge = (ticker: string): HoldingsTableRow['earningsBadge'] => {
      if (earningsData.live?.ticker === ticker) return 'LIVE'
      for (const group of earningsData.groups) {
        if (!group.events.some((e) => e.ticker === ticker)) continue
        if (group.kind === 'today') return 'D-1'
        if (group.kind === 'tomorrow') return 'D-2'
        if (group.kind === 'week') return 'D-3'
      }
      return null
    }

    if (storeHoldings.length === 0 && import.meta.env.DEV) {
      return holdingsDevMock.map((h) => ({
        ticker: h.ticker,
        name: h.name,
        currentPrice: h.currentPrice,
        dailyChangePercent: h.dailyChangePercent,
        pnlPercent: h.pnlPercent,
        earningsBadge: getEarningsBadge(h.ticker),
        logoBg: h.logoBg,
        logoFg: h.logoFg,
        logoLabel: h.logoLabel,
      }))
    }
    return storeHoldings.map((h) => {
      const meta = holdingsDevMock.find((m) => m.ticker === h.ticker)
      // 폴러 가격 우선, 없으면 KIS_GET_BALANCE 응답에 포함된 currentPrice fallback.
      const livePrice = prices[h.ticker]?.currentPrice ?? h.currentPrice
      const prevClose = prices[h.ticker]?.previousClose ?? 0
      const dailyChangePct = prevClose > 0 ? ((livePrice - prevClose) / prevClose) * 100 : 0
      const pnlPct =
        h.avgPrice > 0 ? ((livePrice - h.avgPrice) / h.avgPrice) * 100 : 0
      return {
        ticker: h.ticker,
        name: meta?.name ?? h.ticker,
        currentPrice: livePrice,
        dailyChangePercent: dailyChangePct,
        pnlPercent: pnlPct,
        earningsBadge: getEarningsBadge(h.ticker),
        logoBg: meta?.logoBg,
        logoFg: meta?.logoFg,
        logoLabel: meta?.logoLabel,
      }
    })
  }, [storeHoldings, prices, earningsData])

  // 관심종목 — 백엔드 GET /api/v1/watchlist 캐시 (main 5분 폴링).
  // currentPrice / dailyChangePercent 는 PricePoller 가 push 한 가격 사용.
  const { items: watchlistItems } = useWatchlist()
  const watchRows: HoldingsTableRow[] = useMemo(() => {
    const getEarningsBadge = (ticker: string): HoldingsTableRow['earningsBadge'] => {
      if (earningsData.live?.ticker === ticker) return 'LIVE'
      for (const group of earningsData.groups) {
        if (!group.events.some((e) => e.ticker === ticker)) continue
        if (group.kind === 'today') return 'D-1'
        if (group.kind === 'tomorrow') return 'D-2'
        if (group.kind === 'week') return 'D-3'
      }
      return null
    }

    return watchlistItems.map((w) => {
      const entry = prices[w.ticker]
      const cur = entry?.currentPrice ?? 0
      const prev = entry?.previousClose ?? 0
      return {
        ticker: w.ticker,
        name: w.companyName,
        currentPrice: cur,
        dailyChangePercent: prev > 0 ? ((cur - prev) / prev) * 100 : 0,
        earningsBadge: getEarningsBadge(w.ticker),
      }
    })
  }, [watchlistItems, prices, earningsData])

  // MarketStrip 데이터:
  //  - useMarketIndices: 마운트 시 REST 1회 + STOMP 구독으로 store 채우고
  //    indices/isLoaded/lastUpdatedAt 을 함께 반환 (store selector 중복 호출 회피).
  //  - prod: backend 미연동 시 빈 배열 → MarketStrip placeholder.
  //  - DEV: backend 미연동 (isLoaded === false) 시에만 mock fallback,
  //         실제 데이터 수신 시 자동 전환.
  const { indices, isLoaded } = useMarketIndices()
  const marketItems = !isLoaded && import.meta.env.DEV ? marketIndexDevMock : indices
  // 어닝콜 타임라인 — 실 IPC 연동. DEV에서 백엔드 미실행 시 fixture fallback.
  const [earningsData, setEarningsData] = useState<EarningsTimelineData>(
    import.meta.env.DEV ? earningsTimelineDevMock : { live: null, groups: [] },
  )

  useEffect(() => {
    let cancelled = false

    ipc.invoke<EarningsTimelineData>(IPC_CHANNELS.EARNINGS_TIMELINE_GET)
      .then((data) => { if (!cancelled) setEarningsData(data) })
      .catch(() => { /* DEV: fixture 유지, prod: 빈 상태 유지 */ })

    const unsub = ipc.on(IPC_CHANNELS.EARNINGS_TIMELINE_UPDATE, (data: EarningsTimelineData) => {
      setEarningsData(data)
    })

    return () => {
      cancelled = true
      unsub()
    }
  }, [])

  // Asset chart: 현재 IPC 미존재 — NVDA fixture 차트를 시각화 더미로 사용 (DEV).
  //  TODO(impl): KIS_GET_ASSET_TIMESERIES 도입 후 실제 시계열 사용.
  //  (보안: 시계열은 사용자별이므로 IPC payload 에 userId 필요 + main 측 인증 검증).
  const assetChartPoints = useMemo(() => {
    if (!import.meta.env.DEV) return []
    return companyDetailDevMock.NVDA.chart30d.map((p) => ({
      date: p.date,
      // 가격 → 가공된 자산 추정치 (실제 수치는 실제 데이터로 교체 필요)
      price: 11900 + (p.price - 110) * 25,
    }))
  }, [])

  return (
    <div className="flex flex-col gap-2.5 h-full min-h-0">
      {/* Row 0: 헤더 */}
      <div className="flex items-center justify-between shrink-0 h-9">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[18px] font-bold text-text-primary tracking-[-0.01em]">
            대시보드
          </h2>
          <p className="text-[11px] text-text-tertiary">
            마지막 동기화{' '}
            <b className="num text-text-secondary font-medium">
              {lastSyncedAt
                ? new Date(lastSyncedAt * 1000).toLocaleTimeString('ko-KR')
                : '—'}
            </b>{' '}
            · KIS 모의투자
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={syncBalance}
            disabled={isSyncing}
            className="h-7 px-2.5 inline-flex items-center gap-1.5 rounded-md
                       bg-surface-2 border border-border-strong text-text-primary
                       hover:bg-surface-3 text-[12px] font-medium disabled:opacity-40"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className={isSyncing ? 'animate-spin' : ''}
            >
              <path d="M2 6a4 4 0 017-2.5M10 6a4 4 0 01-7 2.5M9 2v2h-2M3 10V8h2" />
            </svg>
            {isSyncing ? '동기화 중' : '동기화'}
          </button>
          <ModeSelector
            currentMode={mode}
            userPlan={plan}
            onChange={handleModeChange}
            size="compact"
          />
        </div>
      </div>

      {error && (
        <div className="shrink-0 px-3 py-2 rounded bg-sell/20 border border-sell/40 text-xs text-sell">
          {error}
        </div>
      )}

      {/* Row 1: Market strip */}
      <MarketStrip items={marketItems} />

      {/* Row 2: Portfolio + Asset chart */}
      <div className="grid grid-cols-[40fr_60fr] gap-2.5 shrink-0 h-[180px]">
        {/* Portfolio card (좌측 emerald gradient 바 추가는 PortfolioCard 컨테이너에서) */}
        <section className="rounded-lg bg-surface-1 border border-border-subtle relative overflow-hidden">
          {/* 좌측 2px gradient 바 — 디자인 캔버스 `.pf::before` */}
          <span
            aria-hidden="true"
            className="absolute left-0 top-0 bottom-0 w-0.5 opacity-50"
            style={{
              background:
                'linear-gradient(180deg, #34d399, transparent)',
            }}
          />
          <PortfolioCard
            orderableCash={orderableCash}
            totalCash={totalCash}
            holdings={storeHoldings}
            totalAsset={totalAsset}
            balanceFetchError={balanceFetchError}
            onRetryBalance={syncBalance}
            isSyncing={isSyncing}
            lastSyncedAt={lastSyncedAt}
          />
        </section>

        <AssetChartCard points={assetChartPoints} />
      </div>

      {/* Row 3: Holdings + Earnings timeline */}
      <div className="grid grid-cols-2 gap-2.5 flex-1 min-h-0">
        <HoldingsTable
          holdings={holdingRows}
          watchlist={watchRows}
          onRowClick={(t) => openDrawer(t)}
          rightMeta={
            totalAsset > 0
              ? `평가 $${(totalAsset - totalCash).toLocaleString('en-US', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : undefined
          }
          balanceFetchError={balanceFetchError}
          onRetryBalance={syncBalance}
          isSyncing={isSyncing}
          lastSyncedAt={lastSyncedAt}
        />
        <EarningsTimeline
          data={earningsData}
          onPickTicker={(t) => openDrawer(t)}
          onEnterLive={(t) =>
            navigate(`/trading-room?ticker=${encodeURIComponent(t)}`)
          }
        />
      </div>
    </div>
  )
}

/**
 * Row 2 의 자산 추이 카드. 30D 라인 차트 + Y/X 축 라벨 + 범위 버튼 (UI 전용).
 * 별도 컴포넌트로 분리하지 않고 페이지 내부 헬퍼로 (재사용 없음).
 */
function AssetChartCard({ points }: { points: { date: string; price: number }[] }) {
  if (points.length === 0) {
    return (
      <section className="rounded-lg bg-surface-1 border border-border-subtle flex items-center justify-center text-[11px] text-text-disabled">
        자산 추이 동기화 중…
      </section>
    )
  }

  const prices = points.map((p) => p.price)
  const start = prices[0]
  const end = prices[prices.length - 1]
  const change = end - start
  const changePct = (change / start) * 100
  const min = Math.min(...prices)
  const max = Math.max(...prices)

  return (
    <section className="rounded-lg bg-surface-1 border border-border-subtle flex flex-col min-h-0 overflow-hidden">
      {/* card header */}
      <div className="h-[38px] px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <div className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
          자산 추이
        </div>
        <div className="inline-flex bg-surface-2 border border-border-subtle rounded-md p-0.5">
          {(['7D', '30D', '90D'] as const).map((r) => (
            <button
              key={r}
              type="button"
              className={`num px-2.5 py-0.5 rounded text-[10px] font-semibold tracking-[0.08em]
                          ${r === '30D' ? 'bg-surface-3 text-text-primary' : 'text-text-tertiary hover:text-text-primary'}`}
              // TODO(impl): 범위 변경 → IPC fetch (KIS_GET_ASSET_TIMESERIES)
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-start justify-between gap-3 px-3.5 pt-2.5 pb-1">
        <div className="flex gap-3.5 text-[10px] text-text-tertiary">
          <div>
            시작{' '}
            <b className="num text-text-secondary font-medium">
              ${start.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </b>
          </div>
          <div>
            고점{' '}
            <b className="num text-text-secondary font-medium">
              ${max.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </b>
          </div>
          <div>
            저점{' '}
            <b className="num text-text-secondary font-medium">
              ${min.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </b>
          </div>
        </div>
        <div className="flex gap-3.5 text-[10px] text-text-secondary">
          <div>
            기간 손익{' '}
            <b className={`num font-medium ${change >= 0 ? 'text-buy' : 'text-sell'}`}>
              {change >= 0 ? '+' : ''}${change.toFixed(2)}
            </b>
          </div>
          <div>
            수익률{' '}
            <b className={`num font-medium ${changePct >= 0 ? 'text-buy' : 'text-sell'}`}>
              {changePct >= 0 ? '+' : ''}
              {changePct.toFixed(2)}%
            </b>
          </div>
        </div>
      </div>

      <div className="relative flex-1 px-2.5 pb-2 min-h-0">
        <div className="absolute left-0.5 top-1 bottom-4 w-11 flex flex-col justify-between
                        num text-[9px] text-text-tertiary text-right pr-1">
          {pickYTicks(prices).map((y) => (
            <span key={y}>${y.toLocaleString()}</span>
          ))}
        </div>
        {/* Y축 라벨 영역(w-11=44px) + 8px 갭 = 52px. tailwind 기본 spacing 에 13(52px) 이
            없으므로 임의값 사용. CompanyDrawer (w-10 + left-11=4px gap) 와는 의도적으로
            다름 — 자산 추이 카드의 Y축 라벨이 더 길다 ($1,234,567 등). */}
        <div className="absolute left-[52px] right-2.5 top-1 bottom-4">
          <MiniLineChart
            points={points}
            color={change >= 0 ? 'accent' : 'sell'}
            viewWidth={600}
            viewHeight={110}
          />
        </div>
        <div className="absolute left-[52px] right-2.5 bottom-1 flex justify-between
                        num text-[9px] text-text-tertiary">
          {pickXLabels(points).map((d) => (
            <span key={d}>{d}</span>
          ))}
        </div>
      </div>
    </section>
  )
}

function pickYTicks(prices: number[]): number[] {
  return pickYTicksUtil(prices, 4, 100)
}

function pickXLabels(points: { date: string }[]): string[] {
  return pickXLabelsUtil(points, 5).map((p) => p.date)
}
