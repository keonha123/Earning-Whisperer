import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// setup.ts에서 KisRateLimiter 전체를 mock하지만, 본 파일은 실제 구현을 검증하므로 unmock.
vi.unmock('../KisRateLimiter')

import { KisRateLimiter } from '../KisRateLimiter'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('KisRateLimiter — 우선순위 큐', () => {
  it('HIGH가 LOW를 추월 — 토큰 소진 후 LOW 먼저 acquire해도 HIGH가 먼저 resolve', async () => {
    const limiter = new KisRateLimiter(1)
    try {
      // capacity=1 → tokens=1: 첫 acquire는 즉시 통과하여 토큰 소진.
      await limiter.acquire('HIGH')

      const order: string[] = []
      const lowP = limiter.acquire('LOW').then(() => order.push('LOW'))
      const hiP = limiter.acquire('HIGH').then(() => order.push('HIGH'))

      // 다음 100ms refill 1회로는 0.1 토큰만 보충 → 아직 부족.
      await vi.advanceTimersByTimeAsync(100)
      expect(order).toEqual([])

      // 1초 경과 시 약 1 토큰 누적 → HIGH가 먼저 빠진다.
      await vi.advanceTimersByTimeAsync(1000)
      await hiP

      expect(order[0]).toBe('HIGH')

      // LOW 마저 처리되도록 충분히 진행
      await vi.advanceTimersByTimeAsync(1000)
      await lowP
      expect(order).toEqual(['HIGH', 'LOW'])
    } finally {
      limiter.dispose()
    }
  })
})

describe('KisRateLimiter — refill 정확도', () => {
  it('ratePerSec=1, 토큰 소진 후 1초 진행 → 정확히 1 토큰 보충되어 1건 통과', async () => {
    const limiter = new KisRateLimiter(1)
    try {
      // 초기 1토큰 소진
      await limiter.acquire('HIGH')

      let resolved = false
      const p = limiter.acquire('HIGH').then(() => {
        resolved = true
      })

      // 0.5초 → 0.5 토큰만 보충, 아직 1 미만
      await vi.advanceTimersByTimeAsync(500)
      expect(resolved).toBe(false)

      // 추가 0.5초 → 누적 1.0 토큰 도달 → 통과
      await vi.advanceTimersByTimeAsync(500)
      await p
      expect(resolved).toBe(true)
    } finally {
      limiter.dispose()
    }
  })
})

describe('KisRateLimiter — setRate', () => {
  it('대기 큐 5개가 있는 상태에서 setRate(10) 호출 시 큐는 유지되고 capacity만 변경', async () => {
    const limiter = new KisRateLimiter(1)
    try {
      // 초기 1토큰 소진
      await limiter.acquire('HIGH')

      // 5개 대기열 적재
      const promises = [
        limiter.acquire('LOW'),
        limiter.acquire('LOW'),
        limiter.acquire('LOW'),
        limiter.acquire('LOW'),
        limiter.acquire('LOW'),
      ]
      expect(limiter.pendingCount).toBe(5)

      limiter.setRate(10)
      // 큐 그대로 유지 (capacity만 변경)
      expect(limiter.pendingCount).toBe(5)

      // 새 capacity=10 기준 100ms refill = 1.0 토큰 → 매 100ms마다 1건씩 처리.
      // 1초 진행이면 5건 모두 처리되고도 남는다.
      await vi.advanceTimersByTimeAsync(1000)
      await Promise.all(promises)

      expect(limiter.pendingCount).toBe(0)
    } finally {
      limiter.dispose()
    }
  })
})

describe('KisRateLimiter — 동순위 FIFO', () => {
  it('같은 priority(MEDIUM) 3개 acquire → 들어온 순서대로 resolve', async () => {
    const limiter = new KisRateLimiter(1)
    try {
      // 초기 1토큰 소진
      await limiter.acquire('MEDIUM')

      const order: number[] = []
      const p1 = limiter.acquire('MEDIUM').then(() => order.push(1))
      const p2 = limiter.acquire('MEDIUM').then(() => order.push(2))
      const p3 = limiter.acquire('MEDIUM').then(() => order.push(3))

      // 3초 진행 → 3 토큰 보충되어 모두 통과
      await vi.advanceTimersByTimeAsync(3000)
      await Promise.all([p1, p2, p3])

      expect(order).toEqual([1, 2, 3])
    } finally {
      limiter.dispose()
    }
  })
})

describe('KisRateLimiter — dispose / 0 rate 가드 (H9)', () => {
  it('dispose 후 pending acquire 들이 모두 reject ("KisRateLimiter disposed")', async () => {
    const limiter = new KisRateLimiter(1)
    // 초기 1토큰 소진
    await limiter.acquire('HIGH')

    // 3개 대기
    const p1 = limiter.acquire('HIGH')
    const p2 = limiter.acquire('MEDIUM')
    const p3 = limiter.acquire('LOW')

    expect(limiter.pendingCount).toBe(3)

    // dispose → 모두 reject
    limiter.dispose()

    await expect(p1).rejects.toThrow(/KisRateLimiter disposed/)
    await expect(p2).rejects.toThrow(/KisRateLimiter disposed/)
    await expect(p3).rejects.toThrow(/KisRateLimiter disposed/)

    expect(limiter.pendingCount).toBe(0)
  })

  it('생성자에 0 또는 음수 ratePerSec 전달 시 throw', () => {
    expect(() => new KisRateLimiter(0)).toThrow(/ratePerSec must be > 0/)
    expect(() => new KisRateLimiter(-1)).toThrow(/ratePerSec must be > 0/)
  })

  it('setRate(0) 또는 setRate(-1) → throw + 큐 데드락 회피', async () => {
    const limiter = new KisRateLimiter(1)
    try {
      expect(() => limiter.setRate(0)).toThrow(/ratePerSec must be > 0/)
      expect(() => limiter.setRate(-2)).toThrow(/ratePerSec must be > 0/)

      // 정상 호출은 그대로 동작 (회귀 보호)
      limiter.setRate(5)
    } finally {
      limiter.dispose()
    }
  })
})
