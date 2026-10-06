import { describe, it, expect } from 'vitest'
import { SseParser } from '../sse'

describe('SseParser', () => {
  it('빈 줄 단위로 event 와 data 를 묶는다', () => {
    const parser = new SseParser()
    expect(parser.push('event:meta\ndata:{"scope": "call"}\n\nevent:delta\ndata:{"text": "매출"}\n\n')).toEqual([
      { event: 'meta', data: '{"scope": "call"}' },
      { event: 'delta', data: '{"text": "매출"}' },
    ])
  })

  it('조각 경계가 줄 중간에 걸려도 이어 붙인다', () => {
    const parser = new SseParser()
    expect(parser.push('event:del')).toEqual([])
    expect(parser.push('ta\ndata:{"text"')).toEqual([])
    expect(parser.push(': "a"}\n')).toEqual([])
    expect(parser.push('\n')).toEqual([{ event: 'delta', data: '{"text": "a"}' }])
  })

  it('주석(하트비트)은 건너뛴다', () => {
    const parser = new SseParser()
    expect(parser.push(':\n\n:\n\nevent:done\ndata:{}\n\n')).toEqual([{ event: 'done', data: '{}' }])
  })

  it('여러 data 줄은 줄바꿈으로 잇고 앞 공백 하나만 뗀다', () => {
    const parser = new SseParser()
    expect(parser.push('event: x\ndata: a\ndata:  b\n\n')).toEqual([{ event: 'x', data: 'a\n b' }])
  })

  it('CRLF 줄 끝과 event 없는 프레임(message)을 처리한다', () => {
    const parser = new SseParser()
    expect(parser.push('data: 1\r\n\r\n')).toEqual([{ event: 'message', data: '1' }])
  })

  it('빈 줄로 끝나지 않은 프레임은 내보내지 않는다', () => {
    const parser = new SseParser()
    expect(parser.push('event: delta\ndata: cut')).toEqual([])
  })
})
