/**
 * 파급효과 그래프 모델 (`RippleEffectModal`).
 *
 * 아직 백엔드 발행 경로가 없다. AI Engine 의 `/v1/engine/impact-chain/{ticker}` 를
 * 연결할 때 이 형태로 매핑한다.
 * 화면 예시는 `docs/demo/fixtures/rippleEffect.dev-mock.ts` 참조.
 */

export interface RippleNode {
  id: string
  ticker: string
  name: string
  /** SVG 캔버스 기준 중심 좌표 (0–100 퍼센트 단위). */
  cx: number
  cy: number
  /** 파급 강도 (−1 ~ +1). 양수=긍정, 음수=부정. */
  impact: number
  /** 종목 간 관계. */
  relation: string
  /** 파급 코멘트 (툴팁 / 리스트). */
  comment: string
}

export interface RippleEdge {
  from: string
  to: string
}
