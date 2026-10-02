import type { TranscriptSegment } from '../store/useTranscriptStore'
import type { FactCheckClaim } from '../store/useFactCheckStore'
import type { SpeakerProfile, SpeakerCallStats } from '../types/speakerProfile'
import { EMPTY_SPEAKER_STATS } from '../types/speakerProfile'

/** "mm:ss" — 어닝콜 시작 기준 경과 시간. TradingRoomPage 의 어댑터와 같은 규칙. */
function elapsedLabel(startMs: number): string {
  const total = Math.max(0, Math.floor(startMs / 1000))
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

/**
 * 세그먼트 라벨을 명부의 matchKey 로 정규화한다.
 *
 * 백엔드가 `match_key` 로 세그먼트 `speaker` 와 같은 문자열을 내려주므로 정확 비교면 된다.
 * 부분 문자열 매칭은 쓰지 않는다 — "John Furner" 가 "John Furner Jr." 에도 걸려서 한 발언이
 * 두 사람에게 계상되거나, 반대로 "John D. Furner" 를 놓치고도 화면에는 "발언 없음" 으로만
 * 보이기 때문이다.
 */
function normalize(label: string | undefined): string | null {
  if (!label) return null
  const trimmed = label.trim().toLowerCase()
  return trimmed === '' ? null : trimmed
}

/**
 * 이번 회차에 실제로 도착한 세그먼트/판정만으로 발화자별 집계를 만든다.
 *
 * `callId` 를 반드시 받는다. 트랜스크립트 store 는 같은 종목의 여러 회차를 한 배열에
 * 누적하고 sequence 는 회차마다 0 부터 다시 시작하므로, 회차를 구분하지 않으면 지난
 * 재생의 발언량이 합산되고 팩트체크가 엉뚱한 세그먼트에 귀속된다.
 *
 * 팩트체크 판정은 `batchStartSequence`~`batchEndSequence` 구간에 걸려 있다. 구간에 두
 * 사람이 섞여 있으면 양쪽 모두에 계상한다 — 어느 한쪽에만 몰아 주면 실제보다 확실해 보인다.
 */
export function computeSpeakerStats(
  profiles: readonly SpeakerProfile[],
  segments: readonly TranscriptSegment[],
  claims: readonly FactCheckClaim[],
  callId: string | null,
): Map<string, SpeakerCallStats> {
  const result = new Map<string, SpeakerCallStats>()
  if (profiles.length === 0) return result

  const known = new Set(profiles.map((p) => p.matchKey))
  for (const profile of profiles) {
    result.set(profile.matchKey, { ...EMPTY_SPEAKER_STATS })
  }
  if (callId === null) return result

  // 세그먼트 1회 순회 — 발언량 집계와 sequence→화자 색인을 같이 만든다.
  const keyBySequence = new Map<number, string>()
  for (const segment of segments) {
    if (segment.callId !== callId) continue
    const key = normalize(segment.speaker)
    if (key === null || !known.has(key)) continue

    keyBySequence.set(segment.sequence, key)
    const stats = result.get(key)
    if (!stats) continue
    stats.segmentCount += 1
    stats.wordCount += segment.text.trim().split(/\s+/).filter(Boolean).length
    const label = elapsedLabel(segment.startMs)
    // 도착 순서가 곧 발언 순서지만 startMs 기준으로 다시 비교해 둔다 — 재연결 backfill 로
    // 순서가 흐트러져도 구간 표시가 뒤집히지 않는다.
    if (stats.firstTimestamp === null || label < stats.firstTimestamp) stats.firstTimestamp = label
    if (stats.lastTimestamp === null || label > stats.lastTimestamp) stats.lastTimestamp = label
  }

  // 색인을 순회한다. 판정의 sequence 범위를 그대로 돌면 백엔드가 보낸 값이 커질 때
  // (검증은 타입만 본다) 렌더러가 멈춘다. 색인 크기는 세그먼트 수로 유계다.
  for (const claim of claims) {
    const lo = Math.min(claim.batchStartSequence, claim.batchEndSequence)
    const hi = Math.max(claim.batchStartSequence, claim.batchEndSequence)
    const speakersInBatch = new Set<string>()
    for (const [sequence, key] of keyBySequence) {
      if (sequence >= lo && sequence <= hi) speakersInBatch.add(key)
    }
    for (const key of speakersInBatch) {
      const stats = result.get(key)
      if (!stats) continue
      if (claim.verdict === 'SUPPORTED') stats.supported += 1
      else if (claim.verdict === 'CONTRADICTED') stats.contradicted += 1
      else stats.insufficient += 1
    }
  }

  return result
}

/** 세그먼트 speaker 라벨로 명부에서 사람을 찾는다. 못 찾으면 null. */
export function findProfileByLabel(
  profiles: readonly SpeakerProfile[],
  speakerLabel: string | undefined,
): SpeakerProfile | null {
  const key = normalize(speakerLabel)
  if (key === null) return null
  return profiles.find((p) => p.matchKey === key) ?? null
}
