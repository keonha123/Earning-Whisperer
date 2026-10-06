import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { usePortfolioStore } from '../store/usePortfolioStore'
import { useUserStore } from '../store/useUserStore'
import { useDrawerStore } from '../store/useDrawerStore'
import { useConnectionStore } from '../store/useConnectionStore'
import { useStockMarketStore } from '../store/useStockMarketStore'
import { useMarketIndices } from '../hooks/useMarketIndices'
import { useWatchlist } from '../hooks/useWatchlist'
import { usePrices } from '../hooks/usePrices'
import { useEarningsTimeline } from '../hooks/useEarningsTimeline'
import { ACCOUNT_LABELS, useOrderAccount } from '../hooks/useOrderAccount'
import { DEMO_START_PARAM, DEMO_START_VALUE, DEMO_TICKER } from '../constants/demo'
import { showIpcErrorToast } from '../components/common/Toast'
import { ComingSoon, EmptyState, LoadingBlock } from '../components/common/StateView'
import { isIpcError } from '../../lib/types/ipcError'
import type {
  EarningsEvent,
  EarningsGroup,
  EarningsLiveEvent,
} from '../../lib/types/earningsTimeline'
import type { MarketIndexItem } from '../store/useMarketIndicesStore'

type MineTag = '보유' | '관심'

/**
 * 홈 — 어닝콜 중심 첫 화면 (docs/design/screens/home.md).
 *
 * 주인공은 진행 중인 콜과 내 종목(관심 + 보유)의 다가오는 콜이다. 전체 일정과 지난 콜이 뒤따르고,
 * 시장 지수와 계좌 요약은 오른쪽 좁은 열에 둔다. 시연 재생의 진입점은 이 화면 하나뿐이다.
 *
 * 잔고 동기화(KIS_GET_BALANCE → 보유 종목 시세 폴링 등록)는 앱 첫 화면인 이 화면이 맡는다.
 */
export default function HomePage() {
  const navigate = useNavigate()
  const openDrawer = useDrawerStore((s) => s.open)

  const { syncBalance } = useBalanceSync()
  const { prices } = usePrices()
  const { items: watchlist } = useWatchlist()
  const holdings = usePortfolioStore((s) => s.holdings)
  const { data: timeline, status: timelineStatus, retry: retryTimeline } = useEarningsTimeline()

  const stockList = useStockMarketStore((s) => s.list)
  const loadStockList = useStockMarketStore((s) => s.loadList)
  useEffect(() => {
    void loadStockList()
  }, [loadStockList])

  // 관심과 보유가 겹치면 보유로 표시한다 — 내 돈이 걸린 쪽이 더 중요한 정보다.
  const mineTags = useMemo(() => {
    const map = new Map<string, MineTag>()
    for (const w of watchlist) map.set(w.ticker, '관심')
    for (const h of holdings) map.set(h.ticker, '보유')
    return map
  }, [watchlist, holdings])

  const myUpcoming = useMemo(() => {
    const events = timeline.groups.flatMap((g) => g.events).filter((e) => mineTags.has(e.ticker))
    return [...events].sort((a, b) => a.scheduledAt - b.scheduledAt)
  }, [timeline, mineTags])

  const openCall = (ticker: string) => navigate(`/call?ticker=${encodeURIComponent(ticker)}`)
  const startDemo = () =>
    navigate(`/call?ticker=${DEMO_TICKER}&${DEMO_START_PARAM}=${DEMO_START_VALUE}`)

  const demoName = stockList.find((s) => s.ticker === DEMO_TICKER)?.companyName ?? 'Walmart'
  // 색상 유리 주 버튼은 화면에 하나 — 진행 중인 콜이 있으면 그쪽, 없으면 시연 재생.
  const liveIsPrimary = timeline.live != null

  return (
    <div className="flex flex-col gap-6 max-w-[1320px]">
      <header className="flex items-center justify-between gap-4 pt-2">
        <h1 className="text-[24px] font-bold tracking-[-0.02em] text-ink-1">홈</h1>
        <div className="flex items-center gap-3">
          <span className="text-[12.5px] text-ink-3">
            시연 · <span className="num">{DEMO_TICKER}</span> {demoName} 실적 콜 재생
          </span>
          <button
            type="button"
            onClick={startDemo}
            className={`gbtn rim gbtn-sm ${liveIsPrimary ? '' : 'gbtn-lapis'}`}
          >
            <PlayIcon />
            시연 재생
          </button>
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-6 items-start">
        <div className="flex flex-col gap-6 min-w-0">
          {timeline.live && (
            <LiveCallCard
              event={timeline.live}
              tag={mineTags.get(timeline.live.ticker)}
              onOpen={() => openCall(timeline.live!.ticker)}
            />
          )}

          <Panel title="내 종목의 다가오는 콜" meta="관심 · 보유 종목">
            {timelineStatus === 'loading' ? (
              <LoadingBlock lines={3} lineHeight={20} className="px-5 pb-5" />
            ) : timelineStatus === 'error' ? (
              <TimelineError onRetry={retryTimeline} />
            ) : mineTags.size === 0 ? (
              <EmptyState
                message="관심 종목이나 보유 종목이 없습니다. 종목 브리핑에서 관심 종목을 더하면 여기에 콜 일정이 모입니다."
                action={
                  <button type="button" className="gbtn rim gbtn-sm" onClick={() => navigate('/stocks')}>
                    종목 찾기
                  </button>
                }
              />
            ) : myUpcoming.length === 0 ? (
              <EmptyState message="내 종목 중 다가오는 실적 콜이 없습니다. 일정이 잡히면 여기에 나타납니다." />
            ) : (
              <EventList events={myUpcoming} tags={mineTags} showDate onPick={openDrawer} />
            )}
          </Panel>

          <Panel title="전체 일정" meta="KST">
            {timelineStatus === 'loading' ? (
              <LoadingBlock lines={5} lineHeight={20} className="px-5 pb-5" />
            ) : timelineStatus === 'error' ? (
              <TimelineError onRetry={retryTimeline} />
            ) : timeline.groups.every((g) => g.events.length === 0) ? (
              <EmptyState message="예정된 실적 콜이 없습니다." />
            ) : (
              <div className="flex flex-col pb-2">
                {timeline.groups
                  .filter((g) => g.events.length > 0)
                  .map((g) => (
                    <GroupBlock key={g.kind} group={g} tags={mineTags} onPick={openDrawer} />
                  ))}
              </div>
            )}
          </Panel>

          <ComingSoon
            title="지난 콜"
            note="지난 콜의 자막 · 대조 · 판단 다시 보기는 서버가 콜 결과를 저장한 뒤에 생깁니다"
          />
        </div>

        <aside className="flex flex-col gap-6">
          <AccountSummary prices={prices} onRetry={syncBalance} onMore={() => navigate('/portfolio')} />
          <MarketIndices />
        </aside>
      </div>
    </div>
  )
}

// ── 데이터 ────────────────────────────────────────────────────────────

/**
 * 잔고 동기화. 마운트 시 한 번 KIS_GET_BALANCE 를 부르고, 보유 종목을 main 시세 폴링에 등록한다.
 * 실패하면 store 에 실패를 남겨 마지막 값 위에 실패를 표시하고, 인증 만료면 다시 로그인으로 보낸다.
 */
function useBalanceSync() {
  const navigate = useNavigate()
  const clearUser = useUserStore((s) => s.clear)
  const setAuthenticated = useConnectionStore((s) => s.setAuthenticated)

  async function syncBalance() {
    const store = usePortfolioStore.getState()
    store.startSync()
    try {
      const balance = await ipc.invoke<{
        orderableCash: number
        totalCash: number
        holdings: any[]
      }>(IPC_CHANNELS.KIS_GET_BALANCE)
      store.setBalance(balance.orderableCash, balance.totalCash, balance.holdings)

      // 빈 배열도 보내서 보유가 0개로 줄어든 경우에도 폴링 대상에서 빠지게 한다.
      const tickers = (balance.holdings ?? []).map((h: any) => h.ticker)
      try {
        await ipc.invoke(IPC_CHANNELS.HOLDINGS_TICKERS_UPDATE, { tickers })
      } catch (e) {
        console.error('[HomePage] HOLDINGS_TICKERS_UPDATE 실패:', e)
        showIpcErrorToast(e)
      }
    } catch (e: unknown) {
      console.error('잔고 조회 실패:', e)
      store.setError('잔고 조회에 실패했습니다.')
      store.setBalanceFetchError(e)
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
      usePortfolioStore.getState().setSyncing(false)
    }
  }

  useEffect(() => {
    void syncBalance()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { syncBalance }
}

// ── 콜 ────────────────────────────────────────────────────────────────

/**
 * 진행 중인 콜. 서버가 예정 시각 창으로 추정한 것이라 실제로 시작했는지는 콜 화면의 자막으로 확인한다.
 * LIVE 는 무채색이다 — 빨강은 가격 상승에만 쓴다.
 */
function LiveCallCard({
  event,
  tag,
  onOpen,
}: {
  event: EarningsLiveEvent
  tag: MineTag | undefined
  onOpen: () => void
}) {
  return (
    <section
      className="glass glass-flat rim rim-float rounded-[28px] px-6 py-5 flex items-center gap-6"
      aria-label="진행 중인 콜"
    >
      <div className="flex flex-col gap-1.5 min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[12.5px] text-ink-2">
          <span className="w-1.5 h-1.5 rounded-full bg-ink-1 animate-pulse" aria-hidden />
          <span className="font-semibold tracking-[0.08em]">LIVE</span>
          <span className="text-ink-3">· 예정 시각 기준으로 진행 중인 것으로 보입니다</span>
        </div>
        <div className="flex items-baseline gap-3 min-w-0 on-glass">
          <span className="num text-[22px] font-semibold text-ink-1">{event.ticker}</span>
          <span className="text-[16px] text-ink-2 truncate">{event.name}</span>
          {tag && <Tag tag={tag} />}
        </div>
        <span className="text-[12.5px] text-ink-3">
          {event.callLabel} · 시작 {formatClock(event.scheduledAt)} KST · 경과{' '}
          <span className="num">{event.elapsed}</span>
        </span>
      </div>
      <button type="button" onClick={onOpen} className="gbtn gbtn-lapis rim">
        콜 화면 열기
      </button>
    </section>
  )
}

function GroupBlock({
  group,
  tags,
  onPick,
}: {
  group: EarningsGroup
  tags: ReadonlyMap<string, MineTag>
  onPick: (ticker: string) => void
}) {
  // 오늘 · 내일은 묶음 제목이 날짜를 말해 주므로 시각만, 그 뒤는 날짜도 쓴다.
  const showDate = group.kind !== 'today' && group.kind !== 'tomorrow'
  return (
    <div className="flex flex-col">
      <h3 className="px-5 pt-3 pb-1.5 text-[12.5px] font-semibold text-ink-3">
        {group.label}
        <span className="ml-1.5 font-normal tabular-nums">{group.events.length}</span>
      </h3>
      <EventList events={group.events} tags={tags} showDate={showDate} onPick={onPick} />
    </div>
  )
}

function EventList({
  events,
  tags,
  showDate,
  onPick,
}: {
  events: readonly EarningsEvent[]
  tags: ReadonlyMap<string, MineTag>
  showDate: boolean
  onPick: (ticker: string) => void
}) {
  return (
    <ul className="flex flex-col px-2 pb-2">
      {events.map((e) => {
        const tag = tags.get(e.ticker)
        return (
          <li key={`${e.ticker}-${e.scheduledAt}`}>
            <button
              type="button"
              onClick={() => onPick(e.ticker)}
              className="w-full grid grid-cols-[176px_64px_minmax(0,1fr)_auto_20px] items-center gap-3
                         px-3 py-2.5 rounded-[14px] text-left transition-colors duration-100
                         hover:bg-white/[0.05] focus-visible:outline focus-visible:outline-1 focus-visible:outline-gold"
            >
              <span className="text-[13px] text-ink-2 tabular-nums">
                {showDate ? formatDateTime(e.scheduledAt) : formatClock(e.scheduledAt)}
              </span>
              <span className="num text-[14px] font-semibold text-ink-1">{e.ticker}</span>
              <span className="text-[14px] text-ink-2 truncate">{e.name}</span>
              <span>{tag && <Tag tag={tag} />}</span>
              <BellIcon />
              <span className="sr-only">종목 브리핑 열기</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function TimelineError({ onRetry }: { onRetry: () => void }) {
  return (
    <EmptyState
      message="실적 콜 일정을 불러오지 못했습니다."
      action={
        <button type="button" className="gbtn rim gbtn-sm" onClick={onRetry}>
          다시 시도
        </button>
      }
    />
  )
}

function Tag({ tag }: { tag: MineTag }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11.5px] font-semibold border
                  ${tag === '보유' ? 'text-ink-1 border-white/25' : 'text-ink-3 border-white/10'}`}
    >
      {tag}
    </span>
  )
}

// ── 보조 열 ────────────────────────────────────────────────────────────

/**
 * 계좌 요약. 총자산 · 오늘 손익 · 예수금만 두고 자세한 것은 포트폴리오로 넘긴다.
 * 오늘 손익은 보유 종목의 전일 종가 대비이며, 전일 종가를 모르는 종목이 있으면 계산하지 않는다.
 */
function AccountSummary({
  prices,
  onRetry,
  onMore,
}: {
  prices: Record<string, { currentPrice: number; previousClose: number }>
  onRetry: () => void
  onMore: () => void
}) {
  const account = useOrderAccount()
  const { orderableCash, totalCash, holdings, lastSyncedAt, isSyncing, balanceFetchError } = usePortfolioStore()

  const evaluated = holdings.reduce((sum, h) => sum + h.qty * (prices[h.ticker]?.currentPrice ?? h.currentPrice), 0)
  const totalAsset = totalCash + evaluated

  const canComputeToday = holdings.every((h) => (prices[h.ticker]?.previousClose ?? 0) > 0)
  const todayPnl = canComputeToday
    ? holdings.reduce((sum, h) => {
        const p = prices[h.ticker]!
        return sum + h.qty * (p.currentPrice - p.previousClose)
      }, 0)
    : null

  const neverSynced = lastSyncedAt == null

  return (
    <Panel title="계좌" meta={account ? ACCOUNT_LABELS[account] : '계좌 확인 중'}>
      <div className="px-5 pb-5 flex flex-col gap-4">
        {neverSynced && !balanceFetchError ? (
          <LoadingBlock lines={3} lineHeight={18} />
        ) : neverSynced && balanceFetchError ? (
          <div className="flex flex-col items-start gap-3">
            <p className="text-[13px] text-ink-3">잔고를 불러오지 못했습니다.</p>
            <button type="button" className="gbtn rim gbtn-sm" onClick={onRetry} disabled={isSyncing}>
              다시 시도
            </button>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-1">
              <span className="text-[12.5px] text-ink-3">총자산</span>
              <span className="text-[26px] font-semibold tabular-nums tracking-[-0.01em] text-ink-1">
                {formatUsd(totalAsset)}
              </span>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[13.5px]">
              <dt className="text-ink-3">오늘 손익</dt>
              <dd className="text-right tabular-nums">
                {todayPnl == null ? (
                  <span className="text-ink-3">—</span>
                ) : (
                  <span style={{ color: todayPnl > 0 ? 'var(--up)' : todayPnl < 0 ? 'var(--down)' : undefined }}>
                    {todayPnl > 0 ? '+' : todayPnl < 0 ? '−' : ''}
                    {formatUsd(Math.abs(todayPnl))}
                  </span>
                )}
              </dd>
              <dt className="text-ink-3">주문 가능</dt>
              <dd className="text-right tabular-nums text-ink-1">{formatUsd(orderableCash)}</dd>
              <dt className="text-ink-3">보유 종목</dt>
              <dd className="text-right tabular-nums text-ink-1">{holdings.length}개</dd>
            </dl>
            {balanceFetchError && (
              <div className="flex items-center justify-between gap-2 text-[12px]">
                <span style={{ color: 'var(--caution)' }}>
                  동기화 실패 · {lastSyncedAt ? `${formatSyncTime(lastSyncedAt)} 값` : '이전 값'}
                </span>
                <button type="button" className="gbtn rim gbtn-sm" onClick={onRetry} disabled={isSyncing}>
                  다시 시도
                </button>
              </div>
            )}
          </>
        )}
        <button type="button" className="gbtn rim gbtn-sm self-start" onClick={onMore}>
          포트폴리오에서 자세히
        </button>
      </div>
    </Panel>
  )
}

function MarketIndices() {
  const { indices, isLoaded } = useMarketIndices()
  return (
    <Panel title="시장">
      {!isLoaded || indices.length === 0 ? (
        <p className="px-5 pb-5 text-[13px] text-ink-3">시장 지수를 아직 받지 못했습니다.</p>
      ) : (
        <ul className="px-5 pb-4 flex flex-col">
          {indices.map((it) => (
            <IndexRow key={it.symbol} item={it} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

function IndexRow({ item }: { item: MarketIndexItem }) {
  const price =
    item.format === 'percent'
      ? `${item.price.toFixed(2)}%`
      : item.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const chg = item.changePercent
  const sign = chg > 0 ? '+' : chg < 0 ? '−' : ''
  // 금리처럼 % 로 표시하는 지표의 등락은 %p 다.
  const chgLabel = `${sign}${Math.abs(chg).toFixed(2)}${item.format === 'percent' ? '%p' : '%'}`
  return (
    <li className="flex items-baseline gap-3 py-2 border-b border-white/[0.06] last:border-b-0">
      <span className="num text-[12.5px] font-semibold text-ink-3 w-10">{item.symbol}</span>
      <span className="flex-1 text-right text-[14px] tabular-nums text-ink-1">{price}</span>
      <span
        className="w-16 text-right text-[12.5px] tabular-nums"
        style={{ color: chg > 0 ? 'var(--up)' : chg < 0 ? 'var(--down)' : 'var(--ink-3)' }}
      >
        {chgLabel}
      </span>
    </li>
  )
}

// ── 공통 ──────────────────────────────────────────────────────────────

function Panel({ title, meta, children }: { title: string; meta?: string; children: React.ReactNode }) {
  return (
    <section className="glass glass-flat rim rounded-[28px] flex flex-col" aria-label={title}>
      <div className="flex items-baseline justify-between gap-3 px-5 pt-4 pb-2">
        <h2 className="text-[16px] font-semibold text-ink-1 on-glass">{title}</h2>
        {meta && <span className="text-[12px] text-ink-3">{meta}</span>}
      </div>
      {children}
    </section>
  )
}

/** 콜 시작 알림 자리. 알림 기능이 생기기 전까지 흐리게 둔다. */
function BellIcon() {
  return (
    <span className="text-ink-3 opacity-40" title="콜 시작 알림은 준비 중입니다" aria-hidden>
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
        <path d="M4 11V7a4 4 0 0 1 8 0v4l1 1.5H3L4 11zM6.5 14a1.5 1.5 0 0 0 3 0" strokeLinejoin="round" />
      </svg>
    </span>
  )
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M5 3.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L5.9 2.7a.6.6 0 0 0-.9.5z" />
    </svg>
  )
}

const CLOCK = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: 'numeric', minute: '2-digit' })
const DATE_TIME = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'long',
  day: 'numeric',
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
})
const SYNC_TIME = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit' })

function formatClock(sec: number): string {
  return CLOCK.format(new Date(sec * 1000))
}

function formatDateTime(sec: number): string {
  return DATE_TIME.format(new Date(sec * 1000))
}

function formatSyncTime(sec: number): string {
  return SYNC_TIME.format(new Date(sec * 1000))
}

function formatUsd(v: number): string {
  return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
