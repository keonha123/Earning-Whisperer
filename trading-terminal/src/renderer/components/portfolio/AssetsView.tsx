import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import { usePortfolioStore, type Holding } from '../../store/usePortfolioStore'
import { useUserStore } from '../../store/useUserStore'
import { useConnectionStore } from '../../store/useConnectionStore'
import { useDrawerStore } from '../../store/useDrawerStore'
import { useStockMarketStore } from '../../store/useStockMarketStore'
import { usePrices } from '../../hooks/usePrices'
import { useEarningsTimeline } from '../../hooks/useEarningsTimeline'
import { COMPANY_META } from '../../constants/companyMeta'
import { isIpcError } from '../../../lib/types/ipcError'
import { showIpcErrorToast } from '../common/Toast'
import StaleDataOverlay from '../common/StaleDataOverlay'
import { EmptyState, LoadingBlock } from '../common/StateView'
import AssetSummary from './AssetSummary'
import AssetTrendCard from './AssetTrendCard'
import HoldingsTable, { type HoldingRow, type UpcomingCall } from './HoldingsTable'

const TIME = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/**
 * 포트폴리오의 자산 · 보유 탭 — 예전 대시보드의 캐러셀 4장 · 자산 추이 · 보유 표를 한 화면에 펼친다.
 *
 * 들어올 때 잔고를 한 번 다시 조회한다. 순서와 오류 처리는 홈의 잔고 동기화와 같다
 * (KIS_GET_BALANCE → setBalance → HOLDINGS_TICKERS_UPDATE). 조회에 실패하면 store 의 마지막 값을
 * 그대로 두고 StaleDataOverlay 로 실패 사유 · 시각 · 다시 조회를 덮어 보여 준다.
 */
export default function AssetsView() {
  const {
    orderableCash,
    totalCash,
    holdings,
    lastSyncedAt,
    isSyncing,
    balanceFetchError,
    setBalance,
    startSync,
    setSyncing,
    setError,
    setBalanceFetchError,
  } = usePortfolioStore()
  const clearUser = useUserStore((s) => s.clear)
  const setAuthenticated = useConnectionStore((s) => s.setAuthenticated)
  const openDrawer = useDrawerStore((s) => s.open)
  const navigate = useNavigate()
  const accountLabel = useAccountLabel()

  async function syncBalance() {
    startSync()
    try {
      const balance = await ipc.invoke<{ orderableCash: number; totalCash: number; holdings: Holding[] }>(
        IPC_CHANNELS.KIS_GET_BALANCE,
      )
      setBalance(balance.orderableCash, balance.totalCash, balance.holdings)
      // 보유 0개로 줄어든 경우도 폴링 대상에서 빠지도록 빈 배열도 보낸다
      const tickers = (balance.holdings ?? []).map((h) => h.ticker)
      try {
        await ipc.invoke(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE, { tickers })
      } catch (e) {
        console.error('[AssetsView] HOLDINGS_TICKERS_UPDATE 실패:', e)
        showIpcErrorToast(e)
      }
    } catch (e: unknown) {
      console.error('잔고 조회 실패:', e)
      setError('잔고 조회에 실패했습니다.')
      setBalanceFetchError(e)
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
      setSyncing(false)
    }
  }

  useEffect(() => {
    void syncBalance()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { prices } = usePrices()
  const { data: timeline, status: callStatus, retry: retryCalls } = useEarningsTimeline()

  // 회사명은 종목 화면과 같은 백엔드 목록에서 찾는다. 로고 색은 COMPANY_META 에만 있다.
  const stockList = useStockMarketStore((s) => s.list)
  const loadStockList = useStockMarketStore((s) => s.loadList)
  useEffect(() => {
    void loadStockList()
  }, [loadStockList])
  const nameByTicker = useMemo(() => new Map(stockList.map((s) => [s.ticker, s.companyName])), [stockList])

  const view = useMemo(() => {
    const callOf = (ticker: string): UpcomingCall => {
      if (timeline.live?.ticker === ticker) return { kind: 'live' }
      for (const group of timeline.groups) {
        const event = group.events.find((e) => e.ticker === ticker)
        if (event) return { kind: 'scheduled', at: event.scheduledAt }
      }
      return null
    }

    // 폴러 가격을 먼저 쓰고, 없으면 잔고 응답의 현재가로 떨어진다
    const priced = holdings.map((h) => {
      const current = prices[h.ticker]?.currentPrice ?? h.currentPrice
      const prevClose = prices[h.ticker]?.previousClose ?? 0
      return { h, current, prevClose, value: h.qty * current }
    })
    const stockValue = priced.reduce((sum, p) => sum + p.value, 0)
    const totalAsset = totalCash + stockValue
    const costBasis = holdings.reduce((sum, h) => sum + h.qty * h.avgPrice, 0)
    const unrealizedPnl = stockValue - costBasis
    // 홈과 같은 규칙: 전일 종가를 모르는 종목이 하나라도 있으면 합계를 내지 않는다 (일부 합이 전체로 읽히지 않게)
    const dailyPnl =
      priced.length > 0 && priced.every((p) => p.prevClose > 0)
        ? priced.reduce((sum, p) => sum + (p.current - p.prevClose) * p.h.qty, 0)
        : null

    const rows: HoldingRow[] = priced.map(({ h, current, prevClose, value }) => {
      const meta = COMPANY_META[h.ticker]
      const pnl = (current - h.avgPrice) * h.qty
      return {
        ticker: h.ticker,
        name: nameByTicker.get(h.ticker) ?? meta?.name ?? h.ticker,
        qty: h.qty,
        avgPrice: h.avgPrice,
        currentPrice: current,
        dailyChangePct: prevClose > 0 ? ((current - prevClose) / prevClose) * 100 : null,
        marketValue: value,
        weight: totalAsset > 0 ? value / totalAsset : 0,
        unrealizedPnl: pnl,
        unrealizedPct: h.avgPrice > 0 ? ((current - h.avgPrice) / h.avgPrice) * 100 : 0,
        call: callOf(h.ticker),
        logoBg: meta?.logoBg,
        logoFg: meta?.logoFg,
        logoLabel: meta?.logoLabel,
      }
    })

    return {
      rows,
      stockValue,
      totalAsset,
      unrealizedPnl,
      unrealizedPct: costBasis > 0 ? (unrealizedPnl / costBasis) * 100 : 0,
      dailyPnl,
    }
  }, [holdings, prices, totalCash, timeline, nameByTicker])

  // 한 번도 잔고를 받지 못했으면 보여 줄 마지막 값이 없다 — 0 을 값처럼 보이지 않게 따로 그린다
  const hasBalance = lastSyncedAt != null
  const failedWithoutBalance = !hasBalance && balanceFetchError != null && !isSyncing

  const retryButton = (
    <button type="button" className="gbtn rim gbtn-sm" onClick={() => void syncBalance()} disabled={isSyncing}>
      {isSyncing ? '조회 중' : '다시 조회'}
    </button>
  )

  return (
    <div className="h-full min-h-0 flex flex-col gap-4">
      <div className="grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-4 shrink-0 h-[300px]">
        <section className="relative glass rim on-glass rounded-[28px] p-6 flex flex-col gap-5" aria-label="계좌 요약">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-baseline gap-2 min-w-0">
              <h2 className="text-[18px] font-semibold text-ink-1 whitespace-nowrap">계좌</h2>
              <span className="text-[13px] text-ink-3 truncate">
                {accountLabel ?? '계좌 확인 중'}
                {lastSyncedAt != null && (
                  <>
                    {' · '}동기화 <span className="num">{TIME.format(new Date(lastSyncedAt * 1000))}</span>
                  </>
                )}
              </span>
            </div>
            <button
              type="button"
              className="gbtn rim gbtn-sm shrink-0"
              onClick={() => void syncBalance()}
              disabled={isSyncing}
            >
              {isSyncing ? '동기화 중' : '동기화'}
            </button>
          </div>
          {failedWithoutBalance ? (
            <EmptyState message="잔고를 불러오지 못했습니다." action={retryButton} className="flex-1" />
          ) : !hasBalance ? (
            <LoadingBlock lines={4} lineHeight={22} />
          ) : (
            <AssetSummary
              totalAsset={view.totalAsset}
              totalCash={totalCash}
              orderableCash={orderableCash}
              stockValue={view.stockValue}
              unrealizedPnl={view.unrealizedPnl}
              unrealizedPct={view.unrealizedPct}
              dailyPnl={view.dailyPnl}
            />
          )}
          {hasBalance && (
            <StaleDataOverlay
              error={balanceFetchError}
              onRetry={() => void syncBalance()}
              isRetrying={isSyncing}
              lastSyncedAt={lastSyncedAt}
            />
          )}
        </section>
        <AssetTrendCard />
      </div>

      <section className="relative frost rim rounded-[28px] flex-1 min-h-[240px] overflow-hidden" aria-label="보유 종목">
        {failedWithoutBalance ? (
          <EmptyState message="잔고를 불러오지 못해 보유 종목을 표시할 수 없습니다." action={retryButton} className="h-full" />
        ) : !hasBalance ? (
          <div className="p-6">
            <LoadingBlock lines={5} lineHeight={28} />
          </div>
        ) : (
          <HoldingsTable rows={view.rows} onRowClick={openDrawer} callStatus={callStatus} onRetryCalls={retryCalls} />
        )}
        {hasBalance && (
          <StaleDataOverlay
            error={balanceFetchError}
            onRetry={() => void syncBalance()}
            isRetrying={isSyncing}
            lastSyncedAt={lastSyncedAt}
          />
        )}
      </section>
    </div>
  )
}

const ACCOUNT_LABELS = {
  KIS_PAPER: 'KIS 모의투자',
  KIS_REAL: 'KIS 실전투자',
  SELF_PAPER: '페이퍼 계정',
} as const

/**
 * 잔고가 나오는 계좌 종류. 판단 방식과 문구는 hooks/useOrderAccount.ts(#156)와 같다.
 * 그 hook 이 main 에 들어오면 이 함수를 지우고 그 hook 과 ACCOUNT_LABELS 를 쓴다.
 */
function useAccountLabel(): string | null {
  const accountType = useUserStore((s) => s.accountType)
  const [isPaperTrading, setIsPaperTrading] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    ipc
      .invoke<boolean>(IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING)
      .then((v) => {
        if (!cancelled) setIsPaperTrading(v !== false)
      })
      .catch(() => {
        // 모르는 채로 둔다 — "계좌 확인 중" 으로 남는다
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (accountType === 'SELF_PAPER') return ACCOUNT_LABELS.SELF_PAPER
  if (accountType == null || isPaperTrading === null) return null
  return isPaperTrading ? ACCOUNT_LABELS.KIS_PAPER : ACCOUNT_LABELS.KIS_REAL
}
