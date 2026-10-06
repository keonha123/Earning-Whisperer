import { describe, it, expect } from 'vitest'
import { citationKindLabel, numberCitations, splitAnswer } from '../assistantAnswer'

describe('splitAnswer', () => {
  it('근거 표시를 본문에서 떼어 낸다', () => {
    expect(splitAnswer('영업이익이 늘었습니다.[S8][S20] 다만')).toEqual([
      { kind: 'text', text: '영업이익이 늘었습니다.' },
      { kind: 'cite', marker: 'S8' },
      { kind: 'cite', marker: 'S20' },
      { kind: 'text', text: ' 다만' },
    ])
  })

  it('스트리밍 중 닫히지 않은 표시는 글자로 둔다', () => {
    expect(splitAnswer('늘었습니다.[S1')).toEqual([{ kind: 'text', text: '늘었습니다.[S1' }])
  })

  it('표시가 없으면 본문 하나다', () => {
    expect(splitAnswer('찾지 못했습니다.')).toEqual([{ kind: 'text', text: '찾지 못했습니다.' }])
    expect(splitAnswer('')).toEqual([])
  })
})

describe('numberCitations', () => {
  it('근거 목록 순서로 번호를 매긴다', () => {
    const map = numberCitations('a[S20] b[S8]', ['S8', 'S20'])
    expect(map.get('S8')).toBe(1)
    expect(map.get('S20')).toBe(2)
  })

  it('목록이 오기 전에는 본문에 나온 순서다', () => {
    const map = numberCitations('a[N3] b[S1] c[N3]', [])
    expect(map.get('N3')).toBe(1)
    expect(map.get('S1')).toBe(2)
  })

  it('목록에 없는 표시는 목록 뒤에 붙는다', () => {
    expect(numberCitations('a[S1] b[X9]', ['S1']).get('X9')).toBe(2)
  })
})

describe('citationKindLabel', () => {
  it('모르는 종류는 확인되지 않은 근거다', () => {
    expect(citationKindLabel('segment')).toBe('이번 콜 발언')
    expect(citationKindLabel(null)).toBe('확인되지 않은 근거')
  })
})
