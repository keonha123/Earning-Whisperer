import { describe, it, expect } from 'vitest'
import { paginateSchedule } from '../homeSchedule'

const g = (kind: string, n: number) => ({ kind, label: kind, events: Array.from({ length: n }, (_, i) => `${kind}${i}`) })

describe('paginateSchedule', () => {
  it('행 수로 페이지를 나눈다', () => {
    const pages = paginateSchedule([g('today', 3), g('week', 4)], 5)
    expect(pages).toHaveLength(2)
    expect(pages[0].map((p) => [p.kind, p.events.length])).toEqual([['today', 3], ['week', 2]])
    expect(pages[1].map((p) => [p.kind, p.events.length])).toEqual([['week', 2]])
  })

  it('페이지를 넘어 이어지는 묶음은 이어짐으로 표시하고 전체 건수를 지킨다', () => {
    const pages = paginateSchedule([g('week', 7)], 5)
    expect(pages[1][0]).toMatchObject({ kind: 'week', continued: true, total: 7, events: ['week5', 'week6'] })
    expect(pages[0][0].continued).toBe(false)
  })

  it('빈 묶음은 건너뛰고, 일정이 없으면 페이지도 없다', () => {
    expect(paginateSchedule([g('today', 0), g('week', 2)], 5)[0].map((p) => p.kind)).toEqual(['week'])
    expect(paginateSchedule([g('today', 0)], 5)).toEqual([])
  })

  it('페이지가 딱 맞게 끝나면 빈 페이지를 만들지 않는다', () => {
    expect(paginateSchedule([g('today', 5)], 5)).toHaveLength(1)
  })
})
