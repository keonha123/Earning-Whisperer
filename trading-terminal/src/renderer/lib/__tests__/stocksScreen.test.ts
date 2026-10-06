import { describe, it, expect } from 'vitest'
import {
  filterStocks,
  formatCallDate,
  formatChange,
  resolveQuote,
  weeklyCallTimes,
  type StockFilterSets,
} from '../stocksScreen'
import type { Sp500Stock } from '../../../lib/types/stockList'
import type { EarningsTimelineData } from '../../../lib/types/earningsTimeline'

function stock(ticker: string, companyName = `${ticker} Inc`): Sp500Stock {
  return { ticker, companyName, sector: null, marketCapUsd: null, currentPrice: 10, changePercent: 1 }
}

function ev(ticker: string, scheduledAt: number) {
  return { ticker, name: ticker, scheduledAt, timeLabel: '' }
}

const LIST = [stock('AAPL', 'Apple'), stock('MSFT', 'Microsoft'), stock('WMT', 'Walmart'), stock('AMZN', 'Amazon')]

const SETS: StockFilterSets = {
  watch: new Set(['AAPL', 'WMT']),
  held: new Set(['MSFT']),
  week: new Map([['WMT', 100]]),
}

describe('weeklyCallTimes', () => {
  it('오늘 · 내일 · 이번 주와 진행 중 콜만 넣고, 다음 주 이후는 뺀다', () => {
    const timeline: EarningsTimelineData = {
      live: { ...ev('LIVE', 50), elapsed: '01:00', callLabel: 'Earnings Call' },
      groups: [
        { kind: 'today', label: '오늘', events: [ev('A', 100)] },
        { kind: 'tomorrow', label: '내일', events: [ev('B', 200)] },
        { kind: 'week', label: '이번 주', events: [ev('C', 300)] },
        { kind: 'nextWeek', label: '다음 주', events: [ev('D', 400)] },
        { kind: 'later', label: '이후', events: [ev('E', 500)] },
      ],
    }
    expect([...weeklyCallTimes(timeline).keys()].sort()).toEqual(['A', 'B', 'C', 'LIVE'])
  })

  it('한 종목이 여러 번 나오면 가장 이른 시각을 쓴다', () => {
    const timeline: EarningsTimelineData = {
      live: null,
      groups: [
        { kind: 'week', label: '이번 주', events: [ev('A', 300)] },
        { kind: 'today', label: '오늘', events: [ev('A', 100)] },
      ],
    }
    expect(weeklyCallTimes(timeline).get('A')).toBe(100)
  })
})

describe('filterStocks', () => {
  it('필터별로 관심 · 보유 · 이번 주 콜 종목만 남기고 원래 순서를 지킨다', () => {
    expect(filterStocks(LIST, 'all', '', SETS).map((s) => s.ticker)).toEqual(['AAPL', 'MSFT', 'WMT', 'AMZN'])
    expect(filterStocks(LIST, 'watch', '', SETS).map((s) => s.ticker)).toEqual(['AAPL', 'WMT'])
    expect(filterStocks(LIST, 'held', '', SETS).map((s) => s.ticker)).toEqual(['MSFT'])
    expect(filterStocks(LIST, 'week', '', SETS).map((s) => s.ticker)).toEqual(['WMT'])
  })

  it('검색은 고른 필터 안에서 티커 · 회사명을 대소문자 없이 찾는다', () => {
    expect(filterStocks(LIST, 'all', '  am ', SETS).map((s) => s.ticker)).toEqual(['AMZN'])
    expect(filterStocks(LIST, 'all', 'wal', SETS).map((s) => s.ticker)).toEqual(['WMT'])
    expect(filterStocks(LIST, 'watch', 'micro', SETS)).toEqual([])
  })
})

describe('resolveQuote', () => {
  it('실시간 시세가 있으면 전일 종가 대비로 등락률을 계산한다', () => {
    expect(resolveQuote(stock('A'), { currentPrice: 110, previousClose: 100 })).toEqual({ price: 110, changePct: 10 })
  })

  it('전일 종가를 모르면 등락률을 비운다', () => {
    expect(resolveQuote(stock('A'), { currentPrice: 110, previousClose: 0 }).changePct).toBeNull()
  })

  it('실시간 시세가 없으면 목록 값을 쓴다', () => {
    expect(resolveQuote(stock('A'), undefined)).toEqual({ price: 10, changePct: 1 })
  })
})

describe('formatChange', () => {
  it('방향 기호를 붙이고 음수는 마이너스 기호를 쓴다', () => {
    expect(formatChange(1.234)).toEqual({ text: '▲ +1.23%', dir: 'up' })
    expect(formatChange(-0.5)).toEqual({ text: '▼ −0.50%', dir: 'down' })
    expect(formatChange(0.001)).toEqual({ text: '0.00%', dir: 'flat' })
    expect(formatChange(null)).toEqual({ text: '—', dir: null })
  })
})

describe('formatCallDate', () => {
  it('한국 시간 기준 월/일과 요일을 쓴다', () => {
    // 2026-10-08 23:30 UTC = 2026-10-09 08:30 KST (금)
    expect(formatCallDate(Date.UTC(2026, 9, 8, 23, 30) / 1000)).toBe('10/9 (금)')
  })
})
