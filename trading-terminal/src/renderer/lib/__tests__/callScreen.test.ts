import { describe, it, expect } from 'vitest'
import {
  countDiffsByType,
  countdownParts,
  currentCallSegments,
  deriveCallPhase,
  formatCallClock,
  groupDiffsBySequence,
  isProminentDiff,
  maxOrderQty,
  translationsByLastSequence,
} from '../callScreen'
import type { TranscriptSegment } from '../../store/useTranscriptStore'
import type { TranscriptDiffItem } from '../../store/useTranscriptDiffStore'

function seg(sequence: number, callId = 'WMT-Q2'): TranscriptSegment {
  return { ticker: 'WMT', callId, sequence, startMs: sequence * 15000, endMs: sequence * 15000 + 14000, text: `s${sequence}`, timestamp: 1 }
}

function diff(overrides: Partial<TranscriptDiffItem> = {}): TranscriptDiffItem {
  return {
    topic: 'demand',
    changeType: 'improved',
    summaryKo: '요약',
    currentClaim: 'now',
    priorClaim: 'before',
    confidence: 0.8,
    riskScore: 0.2,
    evidence: [],
    sequence: 1,
    ...overrides,
  }
}

describe('deriveCallPhase', () => {
  it('자막이 없으면 시작 전이다', () => {
    expect(deriveCallPhase([], new Set(), undefined)).toBe('BEFORE')
  })

  it('마지막 콜이 종료 표시를 받지 않았으면 진행 중이다', () => {
    expect(deriveCallPhase([seg(0), seg(1)], new Set(), undefined)).toBe('LIVE')
  })

  it('마지막 콜이 종료 표시를 받았으면 종료 후다', () => {
    expect(deriveCallPhase([seg(0)], new Set(['WMT-Q2']), undefined)).toBe('ENDED')
  })

  it('지난 회차만 종료됐고 새 회차가 진행 중이면 진행 중이다', () => {
    expect(deriveCallPhase([seg(0, 'old'), seg(0, 'new')], new Set(['old']), undefined)).toBe('LIVE')
  })

  it('이번 콜의 종합 판단이 도착했으면 종료 표시를 놓쳤어도 종료 후다', () => {
    expect(deriveCallPhase([seg(0)], new Set(), 'WMT-Q2')).toBe('ENDED')
    expect(deriveCallPhase([], new Set(), 'WMT-Q2')).toBe('ENDED')
  })

  it('callId 가 없는 판단은 지금 콜의 것으로 본다', () => {
    expect(deriveCallPhase([seg(0)], new Set(), null)).toBe('ENDED')
  })

  it('지난 회차 판단은 진행 중인 새 콜을 종료 후로 바꾸지 않는다', () => {
    expect(deriveCallPhase([seg(0, 'new')], new Set(), 'old')).toBe('LIVE')
  })
})

describe('currentCallSegments', () => {
  it('가장 최근 콜의 자막만 남긴다', () => {
    const out = currentCallSegments([seg(0, 'old'), seg(1, 'old'), seg(0, 'new')])
    expect(out.map((s) => s.callId)).toEqual(['new'])
  })

  it('한 콜뿐이면 같은 배열을 돌려준다', () => {
    const input = [seg(0), seg(1)]
    expect(currentCallSegments(input)).toBe(input)
  })
})

describe('isProminentDiff', () => {
  it('후퇴는 위험 점수와 관계없이 펼친다', () => {
    expect(isProminentDiff(diff({ changeType: 'weakened', riskScore: 0 }))).toBe(true)
  })

  it('위험 점수가 기준(0.7) 이상이면 펼친다', () => {
    expect(isProminentDiff(diff({ riskScore: 0.7 }))).toBe(true)
    expect(isProminentDiff(diff({ riskScore: 0.69 }))).toBe(false)
  })
})

describe('groupDiffsBySequence', () => {
  it('같은 발언의 항목을 도착 순서대로 묶는다', () => {
    const a = diff({ sequence: 3, topic: 'a' })
    const b = diff({ sequence: 5, topic: 'b' })
    const c = diff({ sequence: 3, topic: 'c' })
    const map = groupDiffsBySequence([a, b, c])
    expect(map.get(3)).toEqual([a, c])
    expect(map.get(5)).toEqual([b])
    expect(map.get(4)).toBeUndefined()
  })
})

describe('countDiffsByType', () => {
  it('변화 유형마다 센다', () => {
    const counts = countDiffsByType([diff(), diff({ changeType: 'weakened' }), diff()])
    expect(counts).toEqual({ improved: 2, weakened: 1, unchanged: 0, mixed: 0, new_claim: 0 })
  })
})

describe('maxOrderQty', () => {
  it('매수는 예수금을 주문 단가로 나눈 몫이다', () => {
    expect(maxOrderQty({ side: 'BUY', unitPrice: 98.37, orderableCash: 1000, heldQty: 0 })).toBe(10)
  })

  it('매도는 보유 수량이다', () => {
    expect(maxOrderQty({ side: 'SELL', unitPrice: 98, orderableCash: 0, heldQty: 7 })).toBe(7)
  })

  it('가격이나 잔고를 모르면 null 이다', () => {
    expect(maxOrderQty({ side: 'BUY', unitPrice: null, orderableCash: 1000, heldQty: 0 })).toBeNull()
    expect(maxOrderQty({ side: 'SELL', unitPrice: 98, orderableCash: 0, heldQty: null })).toBeNull()
  })

  it('예수금이 없으면 0 이다', () => {
    expect(maxOrderQty({ side: 'BUY', unitPrice: 98, orderableCash: 0, heldQty: 0 })).toBe(0)
  })
})

describe('formatCallClock', () => {
  it('한 시간 미만은 mm:ss, 넘으면 h:mm:ss 다', () => {
    expect(formatCallClock(125_000)).toBe('02:05')
    expect(formatCallClock(3_725_000)).toBe('1:02:05')
  })

  it('음수와 NaN 은 00:00 이다', () => {
    expect(formatCallClock(-1)).toBe('00:00')
    expect(formatCallClock(Number.NaN)).toBe('00:00')
  })
})

describe('countdownParts', () => {
  it('남은 시간을 일 · 시 · 분 · 초로 나눈다', () => {
    const now = 1_000_000
    const at = (now + (1 * 86400 + 2 * 3600 + 3 * 60 + 4) * 1000) / 1000
    expect(countdownParts(at, now)).toEqual({ days: 1, hours: 2, minutes: 3, seconds: 4 })
  })

  it('예정 시각이 지났으면 null 이다', () => {
    expect(countdownParts(1000, 1000 * 1000)).toBeNull()
  })
})

describe('translationsByLastSequence', () => {
  const tr = (callId: string, sequences: number[]) => ({ callId, sequences, textKo: 't' })

  it('문단을 마지막 발언 번호에 붙인다', () => {
    const a = tr('WMT-Q2', [0, 1, 2])
    const b = tr('WMT-Q2', [3, 4, 5])
    const map = translationsByLastSequence([a, b], 'WMT-Q2')
    expect(map.get(2)).toBe(a)
    expect(map.get(5)).toBe(b)
    expect(map.get(0)).toBeUndefined()
  })

  it('지난 회차 번역은 버린다', () => {
    const map = translationsByLastSequence([tr('old', [0, 1, 2]), tr('new', [0])], 'new')
    expect(map.get(2)).toBeUndefined()
    expect(map.get(0)?.callId).toBe('new')
  })

  it('지금 콜을 모르면 비어 있다', () => {
    expect(translationsByLastSequence([tr('a', [0])], null).size).toBe(0)
  })
})
