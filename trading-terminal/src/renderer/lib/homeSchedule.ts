/**
 * 홈 전체 일정(#156)의 페이지 나누기 — 렌더링과 떼어 테스트하는 순수 함수.
 *
 * 일정은 오늘 · 내일 · 이번 주 … 묶음으로 오고, 시즌에는 수백 건이라 한 판에 다 그리면 화면이 끝없이
 * 길어진다. 행 수로 페이지를 나누되, 묶음이 페이지 사이에서 끊기면 다음 페이지 맨 위에 그 묶음 제목을
 * 다시 붙여 어느 날의 일정인지 늘 보이게 한다.
 */

export interface ScheduleGroup<E> {
  kind: string
  label: string
  events: readonly E[]
}

export interface SchedulePageGroup<E> {
  kind: string
  label: string
  /** 이 묶음의 전체 건수. 페이지에 일부만 보여도 묶음 전체 수를 쓴다. */
  total: number
  events: readonly E[]
  /** 앞 페이지에서 이어지는 묶음. */
  continued: boolean
}

export function paginateSchedule<E>(
  groups: readonly ScheduleGroup<E>[],
  pageSize: number,
): SchedulePageGroup<E>[][] {
  const pages: SchedulePageGroup<E>[][] = []
  let page: SchedulePageGroup<E>[] = []
  let room = pageSize
  for (const g of groups) {
    let offset = 0
    while (offset < g.events.length) {
      const take = Math.min(room, g.events.length - offset)
      page.push({ kind: g.kind, label: g.label, total: g.events.length, events: g.events.slice(offset, offset + take), continued: offset > 0 })
      offset += take
      room -= take
      if (room === 0) {
        pages.push(page)
        page = []
        room = pageSize
      }
    }
  }
  if (page.length > 0) pages.push(page)
  return pages
}
