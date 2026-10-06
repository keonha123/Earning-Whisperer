/**
 * 질의응답(#112) 답 본문 다루기 — 렌더링과 떼어 테스트하는 순수 함수.
 *
 * 답 본문에는 `[S12]` `[N3]` `[P2]` `[E1]` 같은 근거 표시가 들어 있다. 화면은 이 표시를 본문에서 떼어
 * 근거 번호 칩으로 바꾸고, 같은 번호의 근거 목록과 짝짓는다.
 */

export type AnswerPart = { kind: 'text'; text: string } | { kind: 'cite'; marker: string }

/** 근거 표시: 대괄호 안의 영문 대문자 하나 + 숫자. 스트리밍 중 아직 닫히지 않은 `[S1` 은 글자로 둔다. */
const MARKER = /\[([A-Z]\d+)\]/g

export function splitAnswer(text: string): AnswerPart[] {
  const parts: AnswerPart[] = []
  let cursor = 0
  for (const m of text.matchAll(MARKER)) {
    const at = m.index ?? 0
    if (at > cursor) parts.push({ kind: 'text', text: text.slice(cursor, at) })
    parts.push({ kind: 'cite', marker: m[1] })
    cursor = at + m[0].length
  }
  if (cursor < text.length) parts.push({ kind: 'text', text: text.slice(cursor) })
  return parts
}

/**
 * 근거 표시 → 화면 번호(1부터). 근거 목록의 순서(본문에 처음 나온 순서)를 따른다.
 * 목록이 오기 전(스트리밍 중)에는 본문에 나온 순서로 매겨 두어 번호가 비지 않게 한다.
 */
export function numberCitations(text: string, markersInList: readonly string[]): ReadonlyMap<string, number> {
  const order = markersInList.length > 0 ? [...markersInList] : []
  for (const part of splitAnswer(text)) {
    if (part.kind === 'cite' && !order.includes(part.marker)) order.push(part.marker)
  }
  return new Map(order.map((marker, i) => [marker, i + 1]))
}

/** 근거 종류 이름. 표시 첫 글자가 종류다(S 발언 · N 뉴스 · P 지난 분기 콜 · E 실적 추정치). */
export function citationKindLabel(type: string | null): string {
  switch (type) {
    case 'segment':
      return '이번 콜 발언'
    case 'news':
      return '뉴스'
    case 'prior_statement':
      return '지난 분기 콜'
    case 'estimate':
      return '실적 추정치'
    default:
      return '확인되지 않은 근거'
  }
}
