import type { SuggestedQuestionId } from '../../lib/types/assistant'

/** 콜 공통 추천 질문(#112). 누르면 콜 전체 범위의 일반 질문으로 보낸다. */
export const SUGGESTED_QUESTIONS: ReadonlyArray<{ id: SuggestedQuestionId; label: string }> = [
  { id: 'summary', label: '지금까지 핵심을 요약해 줘' },
  { id: 'vs_last_quarter', label: '지난 분기와 달라진 점은?' },
  { id: 'guidance', label: '가이던스가 바뀌었어?' },
  { id: 'vs_expectations', label: '시장 예상과 비교하면 어때?' },
  { id: 'risks', label: '경영진이 강조한 리스크나 걱정거리는?' },
]

/** 답변 영역에 항상 보이는 고지. */
export const ASSISTANT_DISCLAIMER = 'AI 가 생성한 답변이며 틀릴 수 있습니다. 근거 원문을 확인해 주세요. 투자 권유가 아닙니다.'

/** 대화당 질문 수(첫 질문 + 후속 3회). */
export const MAX_QUESTIONS_PER_CONVERSATION = 4
export const MAX_QUESTION_CHARS = 500

/** backend·assistant·main 이 보내는 오류 code 별 화면 문구. 모르는 code 는 서버 메시지를 그대로 쓴다. */
export const ASSISTANT_ERROR_MESSAGES: Record<string, string> = {
  segments_not_found: '이 콜의 자막을 아직 찾지 못했습니다. 잠시 후 다시 질문해 주세요.',
  ticker_mismatch: '보고 있는 콜과 종목이 맞지 않습니다.',
  assistant_busy: '이전 질문의 답변이 끝난 뒤 다시 질문해 주세요.',
  daily_limit_exceeded: '오늘 질문 횟수를 모두 썼습니다.',
  assistant_overloaded: '질문이 몰려 있습니다. 잠시 후 다시 질문해 주세요.',
  assistant_unavailable: '질의응답을 잠시 사용할 수 없습니다.',
  assistant_stream_interrupted: '답변 전송이 중간에 끊겼습니다.',
  stream_interrupted: '답변 전송이 중간에 끊겼습니다.',
  timeout: '답변 시간이 제한을 넘어 중단했습니다.',
  llm_timeout: '답변 생성이 제한 시간을 넘었습니다. 잠시 후 다시 질문해 주세요.',
  llm_failed: '답변을 만들지 못했습니다. 잠시 후 다시 질문해 주세요.',
  llm_unparsable: '질문을 해석하지 못했습니다. 다시 질문해 주세요.',
  context_unavailable: '콜 자막을 불러오지 못했습니다. 잠시 후 다시 질문해 주세요.',
  internal: '알 수 없는 오류가 발생했습니다.',
  network: '서버에 연결하지 못했습니다.',
  auth_expired: '로그인이 만료됐습니다. 다시 로그인해 주세요.',
  validation: '질문 형식이 올바르지 않습니다.',
}

/** meta.missing_sources 의 화면 이름. */
export const MISSING_SOURCE_LABELS: Record<string, string> = {
  news: '관련 뉴스',
  prior_call: '지난 분기 콜',
  estimates: '실적 추정치',
  segments_incomplete: '일부 콜 자막',
}
