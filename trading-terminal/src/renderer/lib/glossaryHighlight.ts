import type { GlossaryTerm } from '../store/useGlossaryStore'

/**
 * 번역문에서 용어 밑줄 위치를 찾는다 (#111).
 *
 * 번역문을 사전과 직접 대조하지 않고, 백엔드가 알려 준 `terms_used`(번역어가 실제로 들어간 용어)만
 * 쓴다. 그 용어의 `ko` 를 번역문에서 찾아 위치를 돌려준다.
 *
 * 규칙
 *  - 정의가 있는 용어만 표시한다. 정의가 없는 용어는 번역 고정에만 쓰인 것이다.
 *  - 같은 용어는 처음 나온 곳 한 번만 표시한다.
 *  - 번역어가 겹치면 긴 쪽을 먼저 잡는다. "조정 주당순이익(EPS)" 안의 "주당순이익(EPS)" 를 따로 잡지 않는다.
 *  - 번역어 바로 앞 글자가 번역어 첫 글자와 같은 문자군(한글 / 영문)이면 단어 중간으로 보고 건너뛴다.
 *    "순매출" 안의 "매출" 은 잡지 않고, 숫자 뒤에 붙은 "25bp" 의 "bp" 는 잡는다.
 *  - 뒤쪽은 번역어가 영문으로 끝날 때만 본다("bps" 안의 "bp" 를 잡지 않게). 한글 번역어 뒤에는
 *    조사가 붙으므로 보지 않는다("기존점 매출은").
 *  - 한 문단에 maxSpans 개까지만 표시한다. 밑줄이 너무 많으면 읽기 어렵다.
 */

export interface TermSpan {
  /** 번역문 안의 시작 위치 (UTF-16 index, String.prototype.slice 와 같은 기준). */
  start: number
  /** 끝 위치 (exclusive). */
  end: number
  term: GlossaryTerm
}

export const DEFAULT_MAX_SPANS = 5

const HANGUL = /[가-힣]/
const LATIN = /[A-Za-z]/

/** 같은 문자군이면 한 단어로 이어진 것으로 본다. 숫자는 어느 쪽과도 이어지지 않는다. */
function sameScript(a: string, b: string): boolean {
  return (HANGUL.test(a) && HANGUL.test(b)) || (LATIN.test(a) && LATIN.test(b))
}

export function locateTerms(
  textKo: string,
  termsUsed: readonly string[],
  bySpelling: ReadonlyMap<string, GlossaryTerm>,
  maxSpans: number = DEFAULT_MAX_SPANS,
): TermSpan[] {
  if (!textKo || termsUsed.length === 0 || bySpelling.size === 0 || maxSpans <= 0) return []

  const terms: GlossaryTerm[] = []
  for (const spelling of termsUsed) {
    const term = bySpelling.get(spelling.toLowerCase())
    if (term && term.definitionKo && !terms.includes(term)) terms.push(term)
  }
  terms.sort((a, b) => b.ko.length - a.ko.length)

  const taken: Array<[number, number]> = []
  const spans: TermSpan[] = []
  for (const term of terms) {
    const start = findFree(textKo, term.ko, taken)
    if (start < 0) continue
    const end = start + term.ko.length
    taken.push([start, end])
    spans.push({ start, end, term })
  }
  return spans.sort((a, b) => a.start - b.start).slice(0, maxSpans)
}

function findFree(text: string, needle: string, taken: ReadonlyArray<[number, number]>): number {
  let from = 0
  while (from <= text.length - needle.length) {
    const index = text.indexOf(needle, from)
    if (index < 0) return -1
    const end = index + needle.length
    const startsWord = index === 0 || !sameScript(text[index - 1], needle[0])
    const last = needle[needle.length - 1]
    const endsWord = end >= text.length || !LATIN.test(last) || !LATIN.test(text[end])
    const overlaps = taken.some(([s, e]) => index < e && s < end)
    if (startsWord && endsWord && !overlaps) return index
    from = index + 1
  }
  return -1
}
