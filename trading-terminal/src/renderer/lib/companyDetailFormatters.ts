import type { StockDetailResponsePayload } from '../../lib/types/stockDetail'

/**
 * CompanyDrawer 표시용 포맷팅 / 시계열 파생 헬퍼.
 *
 * 분리 사유:
 *  - vitest 가 node 환경에서 JSX 변환 plugin 없이 실행되므로, 컴포넌트(.tsx) 안에 함께
 *    두면 helper 단위 테스트가 컴포넌트 import 를 강요받아 transform 실패한다.
 *  - 순수 함수만 모아두어 jsdom 의존 없이 단위 테스트 가능.
 */

/**
 * 시가총액 포맷팅. 단위는 T(조)/B(십억)/M(백만) 자동 분기.
 *  - 1e12 이상 → "$X.XXT"
 *  - 1e9  이상 → "$X.XXB"
 *  - 1e6  이상 → "$X.XXM"
 *  - 그 외     → 천 단위 콤마 ("$999,999")
 *
 * 음수 입력은 의미 없는 데이터라 "—" 로 처리 (시총/매출 추정치 모두 음수가 의미 없음).
 * 단위 분기가 양수만 가정한다는 사실을 코드 레벨에서 명시적으로 가드.
 */
export function formatMarketCap(usd: number | null): string {
  if (usd == null || !Number.isFinite(usd) || usd < 0) return '—'
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(2)}M`
  return `$${usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

/** 단순 가격 포맷 (소수점 2자리 + $ prefix). */
export function formatPrice(p: number | null): string {
  if (p == null || !Number.isFinite(p)) return '—'
  return `$${p.toFixed(2)}`
}

/** 매출 추정치 포맷 — formatMarketCap 와 동일 단위 분기 (큰 단위가 흔하므로). */
export function formatRevenue(usd: number | null): string {
  return formatMarketCap(usd)
}

/** EPS 표시 (2자리 + $). null → "—". */
export function formatEps(eps: number | null): string {
  if (eps == null || !Number.isFinite(eps)) return '—'
  return `$${eps.toFixed(2)}`
}

/** EPS 컨센서스 표시 (다음 어닝 — formatEps 와 동일하나 의미 구분용 alias). */
export function formatEpsEstimate(eps: number | null): string {
  return formatEps(eps)
}

/**
 * dividendYield 표시.
 * 백엔드는 소수 (0.0049 = 0.49%) → *100 후 표기.
 * null → "—".
 */
export function formatDividendYield(ratio: number | null): string {
  if (ratio == null || !Number.isFinite(ratio)) return '—'
  return `${(ratio * 100).toFixed(2)}%`
}

/**
 * 백엔드가 이미 % 단위로 보낸 값 (surprisePercent / priceReactionPercent) 표시.
 * sign=true 면 양수일 때 "+" 부호 prefix.
 */
export function formatDirectPercent(p: number | null, sign = false): string {
  if (p == null || !Number.isFinite(p)) return '—'
  return `${sign && p >= 0 ? '+' : ''}${p.toFixed(2)}%`
}

/**
 * 다음 어닝까지 D-day 라벨.
 *  - 동일 날짜  → "D-Day"
 *  - 미래       → "D-N"
 *  - 과거       → "D+N" (음수의 절대값)
 *
 * Date.now() 의존이라 테스트에서 모킹 어렵지 않게 nowSec 인자로 주입 가능.
 */
export function dDayLabel(scheduledAtSec: number, nowSec?: number): string {
  const now = nowSec ?? Date.now() / 1000
  const diffDays = Math.ceil((scheduledAtSec - now) / 86400)
  if (diffDays === 0) return 'D-Day'
  if (diffDays > 0) return `D-${diffDays}`
  return `D+${-diffDays}`
}

/** 어닝 일시 절대 라벨 (YYYY-MM-DD HH:mm). */
export function formatScheduledAt(scheduledAtSec: number): string {
  const d = new Date(scheduledAtSec * 1000)
  if (Number.isNaN(d.getTime())) return '—'
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

/**
 * chart30d 첫/끝 가격으로 30일 누적 등락 라벨 ("+2.34%" 형식).
 * 데이터 부족 시 빈 문자열.
 */
export function formatPeriodChangeLabel(
  chart30d: StockDetailResponsePayload['chart30d'],
): string {
  if (chart30d.length < 2) return ''
  const first = chart30d[0]?.close
  const last = chart30d[chart30d.length - 1]?.close
  if (
    typeof first !== 'number' ||
    typeof last !== 'number' ||
    !Number.isFinite(first) ||
    !Number.isFinite(last) ||
    first === 0
  ) {
    return ''
  }
  const pct = ((last - first) / first) * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

/**
 * chart30d 의 마지막 두 거래일 비교한 일간 등락 라벨.
 *  - "+1.32% · +$1.63" 형식.
 *  - 데이터 부족 시 빈 문자열.
 */
export function formatDayChangeLabel(
  chart30d: StockDetailResponsePayload['chart30d'],
): string {
  if (chart30d.length < 2) return ''
  const last = chart30d[chart30d.length - 1]?.close
  const prev = chart30d[chart30d.length - 2]?.close
  if (
    typeof last !== 'number' ||
    typeof prev !== 'number' ||
    !Number.isFinite(last) ||
    !Number.isFinite(prev) ||
    prev === 0
  ) {
    return ''
  }
  const diff = last - prev
  const pct = (diff / prev) * 100
  const pctStr = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
  const sign = diff >= 0 ? '+' : '-'
  const diffStr = `${sign}$${Math.abs(diff).toFixed(2)}`
  return `${pctStr} · ${diffStr}`
}

/**
 * 30일 차트의 색 결정 — 첫/끝 비교.
 *  - last > first → up
 *  - last < first → down
 *  - 같음/데이터 부족 → neutral
 */
export function pickChartDirection(
  chart30d: StockDetailResponsePayload['chart30d'],
): 'up' | 'down' | 'neutral' {
  if (chart30d.length < 2) return 'neutral'
  const first = chart30d[0]?.close
  const last = chart30d[chart30d.length - 1]?.close
  if (
    typeof first !== 'number' ||
    typeof last !== 'number' ||
    !Number.isFinite(first) ||
    !Number.isFinite(last)
  ) {
    return 'neutral'
  }
  if (last > first) return 'up'
  if (last < first) return 'down'
  return 'neutral'
}

/**
 * 백엔드가 "YYYY-MM-DD" 로 보내는 date 라벨을 차트 X축용 "MM-DD" 로 축약.
 * 형식이 다른 입력은 그대로 반환 (방어).
 */
export function trimDateLabel(d: string): string {
  if (typeof d !== 'string') return ''
  const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(d)
  if (m) return `${m[1]}-${m[2]}`
  return d
}
