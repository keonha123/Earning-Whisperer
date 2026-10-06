import { IPC_CHANNELS } from '../../lib/ipcChannels'
import { IpcError } from '../../lib/types/ipcError'
import type { AssistantAskRequest, AssistantAskStarted } from '../../lib/types/assistant'
import { assistantStreamService, type AssistantStreamService } from '../services/AssistantStreamService'
import { registerHandler } from './registerHandler'

const MAX_QUESTION_CHARS = 500
const MAX_HISTORY_MESSAGES = 6

/**
 * 어닝콜 질의응답 IPC handler (#112, Contract 7.10).
 *
 * - ASSISTANT_ASK (invoke): backend 스트림을 연 뒤 { requestId } 로 응답한다. 이후 이벤트는 요청한 창에만
 *   ASSISTANT_EVENT 로 민다. 스트림 전 거절은 IpcError(details: AssistantRejection) 로 reject 한다.
 * - ASSISTANT_CANCEL (invoke): 진행 중인 질문을 끊는다.
 * 형식 검증은 backend 도 하지만, 잘못된 요청으로 하루 횟수를 쓰지 않도록 여기서 먼저 거른다.
 */
export function registerAssistantHandlers(
  service: Pick<AssistantStreamService, 'ask' | 'cancel'> = assistantStreamService,
) {
  registerHandler<AssistantAskRequest, AssistantAskStarted>(IPC_CHANNELS.ASSISTANT_ASK, async (event, payload) => {
    if (!isValidRequest(payload)) throw new IpcError('VALIDATION', '질문 형식이 올바르지 않습니다.')
    const sender = event.sender
    return service.ask(payload, (streamEvent) => {
      if (!sender.isDestroyed()) sender.send(IPC_CHANNELS.ASSISTANT_EVENT, streamEvent)
    })
  })

  registerHandler<{ requestId?: string } | undefined, boolean>(IPC_CHANNELS.ASSISTANT_CANCEL, async (_event, payload) =>
    service.cancel(typeof payload?.requestId === 'string' ? payload.requestId : undefined),
  )
}

function isValidRequest(value: unknown): value is AssistantAskRequest {
  if (value === null || typeof value !== 'object') return false
  const r = value as Record<string, unknown>
  const question = typeof r.question === 'string' ? r.question.trim() : ''
  return (
    typeof r.requestId === 'string' && r.requestId.length > 0 &&
    typeof r.ticker === 'string' && r.ticker.length > 0 &&
    typeof r.callId === 'string' && r.callId.length > 0 &&
    Number.isInteger(r.asOfSequence) && (r.asOfSequence as number) >= 0 &&
    (r.anchorSequence === null || (Number.isInteger(r.anchorSequence) && (r.anchorSequence as number) >= 0)) &&
    question.length > 0 && question.length <= MAX_QUESTION_CHARS &&
    (r.suggestedQuestionId === null || typeof r.suggestedQuestionId === 'string') &&
    Array.isArray(r.history) && r.history.length <= MAX_HISTORY_MESSAGES &&
    r.history.every(
      (turn) =>
        turn !== null && typeof turn === 'object' &&
        ((turn as Record<string, unknown>).role === 'user' || (turn as Record<string, unknown>).role === 'assistant') &&
        typeof (turn as Record<string, unknown>).text === 'string',
    )
  )
}
