/**
 * 발화자 프로필 모델 (`SpeakerProfileModal`).
 *
 * 여기 담기는 건 **트랜스크립트에서 확인되는 사실뿐**이다 — 이름, 직책, 소속,
 * 경영진/애널리스트 구분. 화법 성향이나 가이던스 달성률처럼 원문에서 나오지 않는
 * 항목은 만들어 내지 않는다.
 *
 * 대신 이번 콜에서 **실제로 수신한** 세그먼트와 팩트체크 판정을 집계해 붙인다
 * (`SpeakerCallStats`). 그쪽이 시연에서 보여줄 값이 있는 정보다.
 */

/** 콜 참가자 구분. */
export type SpeakerKind = 'MANAGEMENT' | 'ANALYST'

export interface SpeakerProfile {
  /**
   * 세그먼트 `speaker` 문자열과 **정확히** 맞춰 볼 키 (소문자).
   * 백엔드의 `match_key` 를 그대로 받는다 — 클라이언트가 매칭 규칙을 추측하지 않는다.
   */
  matchKey: string
  name: string
  /** 직책. 애널리스트는 'Analyst'. */
  title: string
  /** 소속. 경영진은 발표 기업, 애널리스트는 소속 하우스. */
  affiliation: string
  kind: SpeakerKind
}

/** 이번 콜에서 수신한 데이터로 계산한 발화자별 집계. 사전 조사 값이 아니다. */
export interface SpeakerCallStats {
  /** 이 발화자로 도착한 세그먼트 수. */
  segmentCount: number
  /** 발언 총 단어 수 (공백 분리 기준 — 원문이 영문이라는 전제). */
  wordCount: number
  /** 첫/마지막 발언 시각 라벨. 발언이 없으면 null. */
  firstTimestamp: string | null
  lastTimestamp: string | null
  /** 이 발화자의 발언 구간에 내려진 팩트체크 판정 집계. */
  supported: number
  contradicted: number
  insufficient: number
}

/**
 * 발언이 아직 하나도 없는 발화자의 기본 집계.
 * 공유 상수라서 얼려 둔다 — 실수로 여기에 누적하면 모든 발화자 값이 오염된다.
 */
export const EMPTY_SPEAKER_STATS: Readonly<SpeakerCallStats> = Object.freeze({
  segmentCount: 0,
  wordCount: 0,
  firstTimestamp: null,
  lastTimestamp: null,
  supported: 0,
  contradicted: 0,
  insufficient: 0,
})
