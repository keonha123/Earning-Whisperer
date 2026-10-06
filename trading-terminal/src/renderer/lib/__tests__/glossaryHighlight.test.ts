import { describe, it, expect } from 'vitest'
import { locateTerms } from '../glossaryHighlight'
import type { GlossaryTerm } from '../../store/useGlossaryStore'

function term(termName: string, ko: string, defined = true, aliases: string[] = []): GlossaryTerm {
  return {
    term: termName,
    aliases,
    ko,
    definitionKo: defined ? `${ko} 뜻` : null,
    whyKo: defined ? `${ko} 이유` : null,
    category: 'test',
  }
}

const TERMS = [
  term('comp sales', '기존점 매출', true, ['comps']),
  term('transactions', '거래 건수'),
  term('EPS', '주당순이익(EPS)'),
  term('adjusted EPS', '조정 주당순이익(EPS)'),
  term('top line', '매출'),
  term('eCommerce', '이커머스', false),
  term('basis points', 'bp', true, ['bps']),
]
const BY_SPELLING = new Map<string, GlossaryTerm>()
for (const t of TERMS) for (const s of [t.term, ...t.aliases]) BY_SPELLING.set(s.toLowerCase(), t)

function marked(text: string, used: string[], max?: number) {
  return locateTerms(text, used, BY_SPELLING, max).map((s) => text.slice(s.start, s.end))
}

describe('locateTerms', () => {
  it('terms_used 의 번역어 위치를 원문 순서로 돌려준다', () => {
    const text = 'Walmart U.S.의 기존점 매출은 2.6%였으며 거래 건수가 이를 견인했습니다.'

    expect(marked(text, ['transactions', 'Comp sales'])).toEqual(['기존점 매출', '거래 건수'])
  })

  it('원문 표기(별칭 · 대소문자)로도 용어를 찾는다', () => {
    expect(marked('기존점 매출은 4.4%였습니다.', ['COMPS'])).toEqual(['기존점 매출'])
  })

  it('정의가 없는 용어는 표시하지 않는다', () => {
    expect(marked('이커머스가 23% 성장했습니다.', ['eCommerce'])).toEqual([])
  })

  it('겹치면 긴 번역어를 먼저 잡는다', () => {
    const text = '조정 주당순이익(EPS)은 19% 늘었고, 연간 주당순이익(EPS) 가이던스를 올렸습니다.'

    const spans = locateTerms(text, ['EPS', 'adjusted EPS'], BY_SPELLING)
    expect(spans.map((s) => [text.slice(s.start, s.end), s.term.term])).toEqual([
      ['조정 주당순이익(EPS)', 'adjusted EPS'],
      ['주당순이익(EPS)', 'EPS'],
    ])
  })

  it('번역어 앞이 한글이면 단어 중간으로 보고 건너뛴다', () => {
    const text = '순매출이 늘었고 매출도 늘었습니다.'

    const spans = locateTerms(text, ['top line'], BY_SPELLING)
    expect(spans).toHaveLength(1)
    expect(spans[0].start).toBe(text.indexOf('매출도'))
  })

  it('숫자 바로 뒤에 붙은 영문 번역어는 잡는다 ("25bp")', () => {
    expect(marked('영업이익률이 25bp 개선됐습니다.', ['basis points'])).toEqual(['bp'])
  })

  it('영문 번역어가 다른 영문 단어 안에 있으면 잡지 않는다', () => {
    expect(marked('bps 와 abp 표기', ['bps'])).toEqual([])
  })

  it('같은 용어는 처음 나온 곳 한 번만 표시한다', () => {
    expect(marked('기존점 매출과 기존점 매출', ['comp sales', 'comps'])).toEqual(['기존점 매출'])
  })

  it('번역문에 번역어가 없으면 표시하지 않는다', () => {
    expect(marked('비교 매출이 늘었습니다.', ['comp sales'])).toEqual([])
  })

  it('표시 개수 상한을 지킨다', () => {
    const text = '기존점 매출, 거래 건수, 주당순이익(EPS)'

    expect(marked(text, ['comp sales', 'transactions', 'EPS'], 2)).toEqual(['기존점 매출', '거래 건수'])
  })

  it('입력이 비면 빈 배열', () => {
    expect(locateTerms('', ['comp sales'], BY_SPELLING)).toEqual([])
    expect(locateTerms('기존점 매출', [], BY_SPELLING)).toEqual([])
    expect(locateTerms('기존점 매출', ['comp sales'], new Map())).toEqual([])
  })
})
