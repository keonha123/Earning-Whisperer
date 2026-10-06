import { describe, it, expect } from 'vitest'
import { parseServerTime } from '../serverTime'

describe('parseServerTime', () => {
  it('시간대 표기 없는 백엔드 시각은 UTC 로 읽는다', () => {
    expect(parseServerTime('2026-10-06T19:10:33').toISOString()).toBe('2026-10-06T19:10:33.000Z')
  })

  it('소수 초가 붙어도 UTC 로 읽는다', () => {
    expect(parseServerTime('2026-10-06T19:10:33.123456').getTime()).toBe(
      Date.UTC(2026, 9, 6, 19, 10, 33, 123),
    )
  })

  it('시간대 표기가 있으면 그대로 따른다', () => {
    expect(parseServerTime('2026-10-07T04:10:33+09:00').toISOString()).toBe('2026-10-06T19:10:33.000Z')
    expect(parseServerTime('2026-10-06T19:10:33Z').toISOString()).toBe('2026-10-06T19:10:33.000Z')
  })

  it('숫자 timestamp 는 그대로 쓴다', () => {
    expect(parseServerTime(0).getTime()).toBe(0)
  })
})
