export type Priority = 'HIGH' | 'MEDIUM' | 'LOW'

type Waiter = {
  resolve: () => void
  reject: (err: Error) => void
}

/**
 * KIS Open API rate limit (모의 ~2 req/s, 실전 ~20 req/s)을 위한
 * 토큰 버킷 + 우선순위(HIGH > MEDIUM > LOW) FIFO 큐.
 *
 * 100ms 마다 ratePerSec/10 만큼 토큰을 보충(소수 허용)하고,
 * drain 루프는 토큰이 1 이상인 동안 hi → mid → lo 순서로 dequeue한다.
 */
export class KisRateLimiter {
  private capacity: number
  private tokens: number
  private readonly hi: Waiter[] = []
  private readonly mid: Waiter[] = []
  private readonly lo: Waiter[] = []
  private timer: NodeJS.Timeout | null = null

  constructor(ratePerSec: number) {
    if (!(ratePerSec > 0)) {
      throw new Error('KisRateLimiter: ratePerSec must be > 0')
    }
    this.capacity = ratePerSec
    this.tokens = ratePerSec
    this.timer = setInterval(() => {
      this.tokens = Math.min(this.capacity, this.tokens + this.capacity / 10)
      this.drain()
    }, 100)
  }

  acquire(priority: Priority): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const queue = this.queueFor(priority)
      queue.push({ resolve, reject })
      this.drain()
    })
  }

  setRate(newRatePerSec: number): void {
    if (!(newRatePerSec > 0)) {
      throw new Error('KisRateLimiter.setRate: ratePerSec must be > 0')
    }
    this.capacity = newRatePerSec
    // 큐는 그대로 유지 — 진행 중인 대기자는 새 capacity 기준으로 계속 처리된다.
    this.tokens = Math.min(this.tokens, this.capacity)
    console.log(`[KisRateLimiter] setRate → ${newRatePerSec} req/s (pending=${this.pendingCount})`)
  }

  dispose(): void {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
    // 남아있는 모든 pending acquire는 reject — 메모리 누수 + 데드락 방지
    const err = new Error('KisRateLimiter disposed')
    const drainAndReject = (q: Waiter[]): void => {
      while (q.length > 0) {
        const w = q.shift()
        w?.reject(err)
      }
    }
    drainAndReject(this.hi)
    drainAndReject(this.mid)
    drainAndReject(this.lo)
  }

  get pendingCount(): number {
    return this.hi.length + this.mid.length + this.lo.length
  }

  private queueFor(priority: Priority): Waiter[] {
    if (priority === 'HIGH') return this.hi
    if (priority === 'MEDIUM') return this.mid
    return this.lo
  }

  private drain(): void {
    // 부동소수점 누적 오차(예: 0.1*10 = 0.9999...) 보정용 epsilon.
    while (this.tokens >= 1 - 1e-9) {
      const next = this.hi.shift() ?? this.mid.shift() ?? this.lo.shift()
      if (!next) return
      this.tokens -= 1
      next.resolve()
    }
  }
}

// 싱글톤 — 모의투자 디폴트 1.5 req/s. Step 2에서 KisService가 구간별로 setRate 호출.
export const kisLimiter = new KisRateLimiter(1.5)
