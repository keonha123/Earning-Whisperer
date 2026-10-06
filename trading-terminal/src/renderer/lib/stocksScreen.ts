import type { Sp500Stock } from '../../lib/types/stockList'
import type { EarningsGroupKind, EarningsTimelineData } from '../../lib/types/earningsTimeline'

/**
 * 종목 화면(docs/design/screens/stocks.md)의 필터 · 표시 계산.
 * 화면과 떼어 두어 단위 테스트로 기준을 고정한다.
 */

export type StockFilter = 'all' | 'watch' | 'held' | 'week'

/** "이번 주 콜" 에 넣는 일정 묶음. 진행 중인 콜(live)도 함께 넣는다. */
const WEEK_KINDS: ReadonlySet<EarningsGroupKind> = new Set(['today', 'tomorrow', 'week'])

/** 이번 주 콜이 있는 종목 → 가장 이른 예정 시각(epoch 초). */
export function weeklyCallTimes(timeline: EarningsTimelineData): Map<string, number> {
  const map = new Map<string, number>()
  const put = (ticker: string, at: number) => {
    const prev = map.get(ticker)
    if (prev === undefined || at < prev) map.set(ticker, at)
  }
  if (timeline.live) put(timeline.live.ticker, timeline.live.scheduledAt)
  for (const g of timeline.groups) {
    if (!WEEK_KINDS.has(g.kind)) continue
    for (const e of g.events) put(e.ticker, e.scheduledAt)
  }
  return map
}

export interface StockFilterSets {
  watch: ReadonlySet<string>
  held: ReadonlySet<string>
  week: ReadonlyMap<string, number>
}

export function matchesFilter(ticker: string, filter: StockFilter, sets: StockFilterSets): boolean {
  switch (filter) {
    case 'watch':
      return sets.watch.has(ticker)
    case 'held':
      return sets.held.has(ticker)
    case 'week':
      return sets.week.has(ticker)
    default:
      return true
  }
}

/** 검색은 고른 필터 안에서 티커 · 회사명에 대해 대소문자 없이 찾는다. 순서(시가총액 순)는 유지한다. */
export function filterStocks(
  list: readonly Sp500Stock[],
  filter: StockFilter,
  query: string,
  sets: StockFilterSets,
): Sp500Stock[] {
  const q = query.trim().toLowerCase()
  return list.filter(
    (s) =>
      matchesFilter(s.ticker, filter, sets) &&
      (!q || s.ticker.toLowerCase().includes(q) || s.companyName.toLowerCase().includes(q)),
  )
}

/** 필터 결과가 비었을 때의 문구. 무엇이 없는지와 언제 생기는지를 한 문장으로 쓴다. */
export function emptyFilterMessage(filter: StockFilter): string {
  switch (filter) {
    case 'watch':
      return '관심 종목이 없습니다. 종목 브리핑에서 관심 종목을 더하면 여기에 모입니다.'
    case 'held':
      return '보유 종목이 없습니다. 주문이 체결되면 여기에 나타납니다.'
    case 'week':
      return '이번 주 예정된 실적 콜이 없습니다. 일정이 잡히면 여기에 나타납니다.'
    default:
      return '종목 목록이 비어 있습니다.'
  }
}

/** 실시간 시세가 있으면 그 값으로, 없으면 목록에 실려 온 값으로 현재가 · 일일 등락률을 정한다. */
export function resolveQuote(
  stock: Sp500Stock,
  live: { currentPrice: number; previousClose: number } | undefined,
): { price: number | null; changePct: number | null } {
  if (!live) return { price: stock.currentPrice, changePct: stock.changePercent }
  const changePct =
    live.previousClose > 0 ? ((live.currentPrice - live.previousClose) / live.previousClose) * 100 : null
  return { price: live.currentPrice, changePct }
}

export function formatMarketCap(usd: number | null): string {
  if (usd == null) return '—'
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(1)}T`
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(0)}B`
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`
  return `$${usd.toFixed(0)}`
}

export function formatPrice(price: number | null): string {
  return price == null ? '—' : `$${price.toFixed(2)}`
}

/** 등락률. 색만으로 구분하지 않도록 ▲ ▼ 를 붙이고, 음수는 마이너스 기호(−)를 쓴다. */
export function formatChange(pct: number | null): { text: string; dir: 'up' | 'down' | 'flat' | null } {
  if (pct == null) return { text: '—', dir: null }
  const abs = Math.abs(pct).toFixed(2)
  if (abs === '0.00') return { text: '0.00%', dir: 'flat' }
  return pct > 0 ? { text: `▲ +${abs}%`, dir: 'up' } : { text: `▼ −${abs}%`, dir: 'down' }
}

const KST_DATE = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'numeric',
  day: 'numeric',
  weekday: 'short',
})

/** 이번 주 콜 표시용 날짜(KST). 예: "10/9 (목)". */
export function formatCallDate(epochSec: number): string {
  const parts = KST_DATE.formatToParts(new Date(epochSec * 1000))
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  return `${get('month')}/${get('day')} (${get('weekday')})`
}
