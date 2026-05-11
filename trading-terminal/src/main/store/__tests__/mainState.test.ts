import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mainState } from '../mainState'

beforeEach(() => {
  mainState.clear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('mainState.isKisTokenValid — monotonic 시계 기반 만료 판정', () => {
  it('토큰 미발급 상태는 false', () => {
    expect(mainState.isKisTokenValid()).toBe(false)
  })

  it('발급 직후엔 true (margin 60s 보다 lifetime 이 길면)', () => {
    mainState.setKisAccessToken('tok', 86400)
    expect(mainState.isKisTokenValid()).toBe(true)
  })

  it('lifetime 보다 짧은 elapsed 는 valid, margin 미만 남으면 invalid', () => {
    const now = 1000
    vi.spyOn(performance, 'now').mockReturnValue(now)
    mainState.setKisAccessToken('tok', 100) // 100s lifetime, margin 60s

    // elapsed 0 → 남은 100s, margin 60s → valid
    expect(mainState.isKisTokenValid()).toBe(true)

    // elapsed 39s → 남은 61s → valid
    vi.spyOn(performance, 'now').mockReturnValue(now + 39_000)
    expect(mainState.isKisTokenValid()).toBe(true)

    // elapsed 41s → 남은 59s, margin 미만 → invalid
    vi.spyOn(performance, 'now').mockReturnValue(now + 41_000)
    expect(mainState.isKisTokenValid()).toBe(false)
  })

  it('Date.now() 가 미래로 점프해도 isKisTokenValid 는 영향받지 않는다', () => {
    const monoStart = 5_000
    vi.spyOn(performance, 'now').mockReturnValue(monoStart)
    mainState.setKisAccessToken('tok', 86400)

    // wall-clock 만 1년 점프, monotonic 은 변동 없음 → 여전히 valid
    const realDateNow = Date.now
    try {
      Date.now = () => realDateNow() + 365 * 24 * 60 * 60 * 1000
      vi.spyOn(performance, 'now').mockReturnValue(monoStart + 1_000) // monotonic 1초만 경과
      expect(mainState.isKisTokenValid()).toBe(true)
    } finally {
      Date.now = realDateNow
    }
  })

  it('clear() 후엔 false', () => {
    mainState.setKisAccessToken('tok', 86400)
    expect(mainState.isKisTokenValid()).toBe(true)
    mainState.clear()
    expect(mainState.isKisTokenValid()).toBe(false)
  })

  it('setKisAccessToken(null) 호출 시 monotonic baseline 도 함께 초기화', () => {
    mainState.setKisAccessToken('tok', 86400)
    mainState.setKisAccessToken(null)
    expect(mainState.kisAccessToken).toBeNull()
    expect(mainState.kisTokenExpiresAt).toBeNull()
    expect(mainState.isKisTokenValid()).toBe(false)
  })
})
