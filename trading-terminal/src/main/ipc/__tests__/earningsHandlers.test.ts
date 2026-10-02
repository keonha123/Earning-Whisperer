import { describe, it, expect } from 'vitest'

// setup.ts 의 axios/electron mock 자동 적용.
import { groupEarnings } from '../earningsHandlers'
import type { EarningsTimelineItem } from '../../services/BackendClient'

describe('earningsHandlers — groupEarnings live 이벤트', () => {
  it('live 이벤트에 소스의 scheduledAt 이 그대로 담긴다', () => {
    // LIVE 윈도우(now-3h ~ now+30m) 안 — 10분 전 시작.
    const scheduledAt = Math.floor(Date.now() / 1000) - 600
    const items: EarningsTimelineItem[] = [
      {
        ticker: 'NVDA',
        companyName: 'NVIDIA Corp',
        scheduledAt,
        confirmed: true,
        marketSession: 'amc',
      },
    ]

    const { live } = groupEarnings(items)

    expect(live).not.toBeNull()
    expect(live?.ticker).toBe('NVDA')
    expect(live?.scheduledAt).toBe(scheduledAt)
  })
})
