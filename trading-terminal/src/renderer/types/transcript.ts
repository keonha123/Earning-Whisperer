/**
 * STTScriptPanel 이 렌더링하는 어닝콜 스크립트 한 줄의 UI 모델.
 *
 * 실데이터는 Backend Contract 4.5 (`/topic/transcript/{ticker}`) 로 도착하며,
 * `TradingRoomPage` 의 `toTranscriptLine` 어댑터가 `TranscriptSegment` 를 이 형태로 바꾼다.
 */
export interface TranscriptLine {
  /** 안정적 React key. `${callId}-${sequence}`. */
  id: string
  /** "mm:ss" — 어닝콜 시작 기준 경과 시간. */
  timestamp: string
  /** 화자 라벨 (예: "CFO · Safra Catz"). 없으면 빈 문자열. */
  speaker: string
  /** 한 줄 텍스트. plain string 으로만 렌더한다 (XSS 방지 — innerHTML 금지). */
  text: string
  /** AI 점수 (선택). −1 ~ +1. 별도 시그널 채널에서 매핑된다. */
  ai_score?: number
}
