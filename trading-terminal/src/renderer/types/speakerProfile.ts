/**
 * 발화자 프로필 모델 (`SpeakerProfileModal`).
 *
 * 사전 조사한 정보를 담는 모델이다 — AI Engine 에 생성 로직은 없다.
 * 화면 예시는 `docs/demo/fixtures/speakerProfile.dev-mock.ts` 참조.
 */

export interface SpeakerProfile {
  id: string
  /** STT speaker 필드 매칭키 (소문자). */
  matchKey: string
  name: string
  title: string
  tenure: string
  /** 한 줄 성향 요약. */
  style: string
  /** 화법 특성 태그. */
  traits: string[]
  /** 최근 가이던스 달성률 (%). */
  guidanceAccuracy: number
  /** 주요 발언 이력 (날짜 · 내용). */
  history: { date: string; quote: string }[]
  /** 투자자 유의사항. */
  watchpoints: string[]
}
