import { describe, it, expect } from 'vitest'
import { computeSpeakerStats, findProfileByLabel } from '../speakerStats'
import type { SpeakerProfile } from '../../types/speakerProfile'
import type { TranscriptSegment } from '../../store/useTranscriptStore'
import type { FactCheckClaim } from '../../store/useFactCheckStore'

const FURNER: SpeakerProfile = {
  matchKey: 'ceo · john furner',
  name: 'John Furner',
  title: 'CEO',
  affiliation: 'Walmart Inc.',
  kind: 'MANAGEMENT',
}
const RAINEY: SpeakerProfile = {
  matchKey: 'cfo · john david rainey',
  name: 'John David Rainey',
  title: 'CFO',
  affiliation: 'Walmart Inc.',
  kind: 'MANAGEMENT',
}
const MCSHANE: SpeakerProfile = {
  matchKey: 'kate mcshane',
  name: 'Kate McShane',
  title: 'Analyst',
  affiliation: 'Goldman Sachs',
  kind: 'ANALYST',
}
const PROFILES = [FURNER, RAINEY, MCSHANE]

function segment(
  overrides: Partial<TranscriptSegment> & Pick<TranscriptSegment, 'sequence' | 'speaker' | 'text'>,
): TranscriptSegment {
  return {
    ticker: 'WMT',
    callId: 'call-1',
    startMs: overrides.sequence * 15000,
    endMs: (overrides.sequence + 1) * 15000,
    timestamp: 1787227200 + overrides.sequence * 15,
    ...overrides,
  }
}

function claim(
  verdict: FactCheckClaim['verdict'],
  start: number,
  end: number,
): FactCheckClaim {
  return {
    claimId: `${verdict}-${start}-${end}`,
    claim: 'claim',
    verdict,
    confidence: 0.8,
    explanationKo: '설명',
    reasonCode: 'OK',
    evidence: [],
    batchStartSequence: start,
    batchEndSequence: end,
  }
}

describe('computeSpeakerStats', () => {
  it('발언량은 화자별로 나뉘고 구간 라벨은 첫/마지막 발언을 가리킨다', () => {
    const segments = [
      segment({ sequence: 0, speaker: 'CEO · John Furner', text: 'one two three' }),
      segment({ sequence: 1, speaker: 'CEO · John Furner', text: 'four five' }),
      segment({ sequence: 2, speaker: 'CFO · John David Rainey', text: 'six' }),
    ]

    const stats = computeSpeakerStats(PROFILES, segments, [], 'call-1')

    expect(stats.get(FURNER.matchKey)).toMatchObject({
      segmentCount: 2,
      wordCount: 5,
      firstTimestamp: '00:00',
      lastTimestamp: '00:15',
    })
    expect(stats.get(RAINEY.matchKey)).toMatchObject({ segmentCount: 1, wordCount: 1 })
    // 발췌에 발언이 없는 애널리스트도 명부에는 남는다 — 0건으로.
    expect(stats.get(MCSHANE.matchKey)).toMatchObject({ segmentCount: 0, wordCount: 0 })
  })

  it('다른 회차(callId)의 세그먼트는 합산하지 않는다', () => {
    // store 는 같은 종목의 여러 재생을 한 배열에 누적하고 sequence 는 회차마다 0 부터
    // 다시 시작한다. 회차를 구분하지 않으면 지난 재생이 이번 집계에 섞인다.
    const segments = [
      segment({ sequence: 0, speaker: 'CEO · John Furner', text: 'old one', callId: 'call-0' }),
      segment({ sequence: 0, speaker: 'CEO · John Furner', text: 'new one' }),
    ]

    const stats = computeSpeakerStats(PROFILES, segments, [], 'call-1')

    expect(stats.get(FURNER.matchKey)?.segmentCount).toBe(1)
  })

  it('팩트체크 판정은 그 구간에서 말한 사람 모두에게 계상된다', () => {
    const segments = [
      segment({ sequence: 0, speaker: 'CEO · John Furner', text: 'a' }),
      segment({ sequence: 1, speaker: 'CEO · John Furner', text: 'b' }),
      segment({ sequence: 2, speaker: 'CFO · John David Rainey', text: 'c' }),
    ]

    const stats = computeSpeakerStats(
      PROFILES,
      segments,
      [claim('SUPPORTED', 0, 2), claim('CONTRADICTED', 0, 1)],
      'call-1',
    )

    expect(stats.get(FURNER.matchKey)).toMatchObject({ supported: 1, contradicted: 1 })
    // 0~2 묶음에만 걸린 CFO 는 SUPPORTED 1건만.
    expect(stats.get(RAINEY.matchKey)).toMatchObject({ supported: 1, contradicted: 0 })
  })

  it('판정의 sequence 범위가 터무니없이 커도 세그먼트 수만큼만 순회한다', () => {
    const segments = [segment({ sequence: 0, speaker: 'CEO · John Furner', text: 'a' })]

    const started = Date.now()
    const stats = computeSpeakerStats(
      PROFILES,
      segments,
      [claim('INSUFFICIENT_EVIDENCE', 0, 1_000_000_000)],
      'call-1',
    )

    expect(stats.get(FURNER.matchKey)?.insufficient).toBe(1)
    expect(Date.now() - started).toBeLessThan(1000)
  })

  it('명부에 없는 화자 라벨은 무시한다 — 부분 일치로 남에게 붙이지 않는다', () => {
    const segments = [segment({ sequence: 0, speaker: 'John Furner Jr.', text: 'a b c' })]

    const stats = computeSpeakerStats(PROFILES, segments, [], 'call-1')

    expect(stats.get(FURNER.matchKey)?.segmentCount).toBe(0)
  })

  it('활성 callId 가 없으면 집계는 전부 0 이다', () => {
    const segments = [segment({ sequence: 0, speaker: 'CEO · John Furner', text: 'a' })]

    const stats = computeSpeakerStats(PROFILES, segments, [], null)

    expect(stats.get(FURNER.matchKey)?.segmentCount).toBe(0)
  })
})

describe('findProfileByLabel', () => {
  it('대소문자를 무시하고 정확히 일치하는 사람을 찾는다', () => {
    expect(findProfileByLabel(PROFILES, 'ceo · John Furner')).toBe(FURNER)
  })

  it('부분만 겹치는 라벨은 매칭하지 않는다', () => {
    expect(findProfileByLabel(PROFILES, 'John Furner')).toBeNull()
    expect(findProfileByLabel(PROFILES, undefined)).toBeNull()
    expect(findProfileByLabel(PROFILES, '   ')).toBeNull()
  })
})
