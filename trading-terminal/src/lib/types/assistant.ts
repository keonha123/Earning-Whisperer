/**
 * 어닝콜 질의응답(#112) main ↔ renderer 공용 타입.
 * 필드는 backend 계약(api-spec 7.10, 10.6)을 camelCase 로 옮긴 것이다. snake_case 변환은 main 이 한다.
 */

export type SuggestedQuestionId = 'summary' | 'vs_last_quarter' | 'guidance' | 'vs_expectations' | 'risks'

export interface AssistantHistoryTurn {
  role: 'user' | 'assistant'
  text: string
}

export interface AssistantAskRequest {
  /** renderer 가 만든 요청 id. 스트림 이벤트가 invoke 응답보다 먼저 도착해도 짝지을 수 있게 한다. */
  requestId: string
  ticker: string
  callId: string
  asOfSequence: number
  anchorSequence: number | null
  question: string
  suggestedQuestionId: SuggestedQuestionId | null
  history: AssistantHistoryTurn[]
}

export interface AssistantAskStarted {
  requestId: string
}

export type AssistantEventType = 'meta' | 'delta' | 'citations' | 'done' | 'error'

/** main → renderer 로 미는 스트림 이벤트. data 는 backend SSE data(JSON)를 파싱한 값 그대로다(snake_case). */
export interface AssistantStreamEvent {
  requestId: string
  type: AssistantEventType
  data: unknown
}

/** 스트림을 열기 전에 거절됐을 때 IpcError.details 에 실리는 값. */
export interface AssistantRejection {
  /** HTTP 상태. 연결 실패·취소는 0. */
  status: number
  /** backend 의 code(예: daily_limit_exceeded). 없으면 null. */
  code: string | null
  message: string
  /** 429 일 때 다음 초기화 시각(UTC ISO-8601). */
  resetAt: string | null
}
