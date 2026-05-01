import { describe, it, expect } from 'vitest'
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
} from '../companyDetailFormatters'

describe('formatMarketCap', () => {
  it('3.12T (NVIDIA 시총 ~3조달러)', () => {
    expect(formatMarketCap(3.12e12)).toBe('$3.12T')
  })

  it('782B (Tesla)', () => {
    expect(formatMarketCap(782e9)).toBe('$782.00B')
  })

  it('100M', () => {
    expect(formatMarketCap(100e6)).toBe('$100.00M')
  })

  it('백만 미만은 천 단위 콤마 (en-US)', () => {
    expect(formatMarketCap(999_999)).toBe('$999,999')
    expect(formatMarketCap(1234)).toBe('$1,234')
  })

  it('null/NaN/Infinity → "—"', () => {
    expect(formatMarketCap(null)).toBe('—')
    expect(formatMarketCap(Number.NaN)).toBe('—')
    expect(formatMarketCap(Number.POSITIVE_INFINITY)).toBe('—')
  })

  it('음수는 의미 없는 데이터라 "—" (silent 잘못된 출력 회피)', () => {
    expect(formatMarketCap(-1)).toBe('—')
    expect(formatMarketCap(-5e8)).toBe('—')
  })
})

describe('formatPrice', () => {
  it('소수점 2자리 + $', () => {
    expect(formatPrice(125.5)).toBe('$125.50')
    expect(formatPrice(0)).toBe('$0.00')
  })

  it('null → "—"', () => {
    expect(formatPrice(null)).toBe('—')
  })
})

describe('formatRevenue', () => {
  it('formatMarketCap alias 동작', () => {
    expect(formatRevenue(3.12e12)).toBe('$3.12T')
    expect(formatRevenue(null)).toBe('—')
  })
})

describe('formatEps / formatEpsEstimate', () => {
  it('정상 값 + null 처리', () => {
    expect(formatEps(0.68)).toBe('$0.68')
    expect(formatEps(null)).toBe('—')
    expect(formatEpsEstimate(1.5)).toBe('$1.50')
    expect(formatEpsEstimate(null)).toBe('—')
  })
})

describe('formatDividendYield', () => {
  it('소수 비율을 %로 변환', () => {
    // 0.0049 = 0.49%
    expect(formatDividendYield(0.0049)).toBe('0.49%')
    expect(formatDividendYield(0.0072)).toBe('0.72%')
  })

  it('0 도 정상 표기', () => {
    expect(formatDividendYield(0)).toBe('0.00%')
  })

  it('null → "—"', () => {
    expect(formatDividendYield(null)).toBe('—')
  })
})

describe('formatDirectPercent', () => {
  it('이미 % 단위인 값은 *100 안 함', () => {
    expect(formatDirectPercent(17.2)).toBe('17.20%')
    expect(formatDirectPercent(-1.7)).toBe('-1.70%')
  })

  it('sign=true 면 양수에 "+" prefix', () => {
    expect(formatDirectPercent(17.2, true)).toBe('+17.20%')
    expect(formatDirectPercent(0, true)).toBe('+0.00%')
    expect(formatDirectPercent(-1.7, true)).toBe('-1.70%')
  })

  it('null → "—"', () => {
    expect(formatDirectPercent(null)).toBe('—')
    expect(formatDirectPercent(null, true)).toBe('—')
  })
})

describe('dDayLabel', () => {
  // nowSec 인자로 시간 모킹 — 2026-05-01 00:00:00 UTC
  const NOW_SEC = Date.UTC(2026, 4, 1, 0, 0, 0) / 1000

  it('동일 날짜 → "D-Day"', () => {
    expect(dDayLabel(NOW_SEC, NOW_SEC)).toBe('D-Day')
  })

  it('1일 후 → "D-1"', () => {
    expect(dDayLabel(NOW_SEC + 86400, NOW_SEC)).toBe('D-1')
  })

  it('7일 후 → "D-7"', () => {
    expect(dDayLabel(NOW_SEC + 7 * 86400, NOW_SEC)).toBe('D-7')
  })

  it('1일 전 → "D+1"', () => {
    expect(dDayLabel(NOW_SEC - 86400, NOW_SEC)).toBe('D+1')
  })

  it('미세하게 미래 (3시간 후) → "D-1" (Math.ceil)', () => {
    expect(dDayLabel(NOW_SEC + 3 * 3600, NOW_SEC)).toBe('D-1')
  })
})

describe('formatScheduledAt', () => {
  it('epoch second → "YYYY-MM-DD HH:mm" (로컬 타임존)', () => {
    // Date 객체가 환경 타임존을 따르므로 결과를 직접 비교.
    const sec = 1735689600 // 2025-01-01 00:00:00 UTC
    const result = formatScheduledAt(sec)
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
  })

  it('NaN → "—"', () => {
    expect(formatScheduledAt(Number.NaN)).toBe('—')
  })
})

describe('formatPeriodChangeLabel', () => {
  it('첫/끝 비교, 양수', () => {
    const chart = [
      { date: '2026-04-01', close: 100, volume: null },
      { date: '2026-04-15', close: 110, volume: null },
    ]
    expect(formatPeriodChangeLabel(chart)).toBe('+10.00%')
  })

  it('음수', () => {
    const chart = [
      { date: '2026-04-01', close: 100, volume: null },
      { date: '2026-04-15', close: 95, volume: null },
    ]
    expect(formatPeriodChangeLabel(chart)).toBe('-5.00%')
  })

  it('데이터 1개 이하면 빈 문자열', () => {
    expect(formatPeriodChangeLabel([])).toBe('')
    expect(formatPeriodChangeLabel([{ date: '2026-04-01', close: 100, volume: null }])).toBe('')
  })

  it('첫 가격 0 (분모 0) 방어', () => {
    const chart = [
      { date: '2026-04-01', close: 0, volume: null },
      { date: '2026-04-15', close: 110, volume: null },
    ]
    expect(formatPeriodChangeLabel(chart)).toBe('')
  })
})

describe('formatDayChangeLabel', () => {
  it('마지막 두 거래일 비교 — 양수', () => {
    const chart = [
      { date: '2026-04-13', close: 100, volume: null },
      { date: '2026-04-14', close: 100, volume: null },
      { date: '2026-04-15', close: 101.63, volume: null },
    ]
    // diff = 1.63, pct = 1.63 / 100 * 100 = 1.63
    expect(formatDayChangeLabel(chart)).toBe('+1.63% · +$1.63')
  })

  it('음수', () => {
    const chart = [
      { date: '2026-04-14', close: 100, volume: null },
      { date: '2026-04-15', close: 99, volume: null },
    ]
    expect(formatDayChangeLabel(chart)).toBe('-1.00% · -$1.00')
  })

  it('데이터 1개 이하면 빈 문자열', () => {
    expect(formatDayChangeLabel([])).toBe('')
    expect(formatDayChangeLabel([{ date: '2026-04-15', close: 100, volume: null }])).toBe('')
  })
})

describe('pickChartDirection', () => {
  it('상승 추세', () => {
    expect(
      pickChartDirection([
        { date: '2026-04-01', close: 100, volume: null },
        { date: '2026-04-15', close: 110, volume: null },
      ]),
    ).toBe('up')
  })

  it('하락 추세', () => {
    expect(
      pickChartDirection([
        { date: '2026-04-01', close: 110, volume: null },
        { date: '2026-04-15', close: 100, volume: null },
      ]),
    ).toBe('down')
  })

  it('동일 가격 → neutral', () => {
    expect(
      pickChartDirection([
        { date: '2026-04-01', close: 100, volume: null },
        { date: '2026-04-15', close: 100, volume: null },
      ]),
    ).toBe('neutral')
  })

  it('데이터 부족 → neutral', () => {
    expect(pickChartDirection([])).toBe('neutral')
    expect(pickChartDirection([{ date: '2026-04-01', close: 100, volume: null }])).toBe(
      'neutral',
    )
  })
})

describe('trimDateLabel', () => {
  it('YYYY-MM-DD → MM-DD', () => {
    expect(trimDateLabel('2026-04-15')).toBe('04-15')
  })

  it('형식이 다르면 그대로 반환', () => {
    expect(trimDateLabel('04-15')).toBe('04-15')
    expect(trimDateLabel('2026/04/15')).toBe('2026/04/15')
  })

  it('비-string 입력 (런타임 방어) → ""', () => {
    // 의도적으로 type 우회.
    expect(trimDateLabel(null as unknown as string)).toBe('')
    expect(trimDateLabel(undefined as unknown as string)).toBe('')
  })
})
