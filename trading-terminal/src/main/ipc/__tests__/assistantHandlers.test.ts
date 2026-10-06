import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'
import { registerAssistantHandlers } from '../assistantHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import type { AssistantAskRequest, AssistantStreamEvent } from '../../../lib/types/assistant'
import { expectIpcError } from '../../../test/ipcErrorTestUtils'

type IpcInvokeHandler = (event: unknown, ...args: unknown[]) => unknown | Promise<unknown>

function handler(channel: string): IpcInvokeHandler {
  const call = (ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mock.calls.find((c) => c[0] === channel)
  if (!call) throw new Error(`channel ${channel} 미등록`)
  return call[1] as IpcInvokeHandler
}

const valid: AssistantAskRequest = {
  requestId: 'r1', ticker: 'WMT', callId: 'call-1', asOfSequence: 3, anchorSequence: null,
  question: '요약해 줘', suggestedQuestionId: null, history: [],
}

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
})

describe('assistantHandlers', () => {
  it('ASK 는 서비스로 넘기고 이벤트를 요청한 창에 민다', async () => {
    const send = vi.fn()
    const sender = { send, isDestroyed: () => false }
    const service = {
      ask: vi.fn(async (_req: AssistantAskRequest, sink: (e: AssistantStreamEvent) => void) => {
        sink({ requestId: 'r1', type: 'delta', data: { text: 'a' } })
        return { requestId: 'r1' }
      }),
      cancel: vi.fn(() => true),
    }
    registerAssistantHandlers(service)

    const result = await handler(IPC_CHANNELS.ASSISTANT_ASK)({ sender }, valid)

    expect(result).toEqual({ requestId: 'r1' })
    expect(service.ask).toHaveBeenCalledWith(valid, expect.any(Function))
    expect(send).toHaveBeenCalledWith(IPC_CHANNELS.ASSISTANT_EVENT, { requestId: 'r1', type: 'delta', data: { text: 'a' } })
  })

  it('창이 닫혔으면 이벤트를 보내지 않는다', async () => {
    const send = vi.fn()
    const service = {
      ask: vi.fn(async (_req: AssistantAskRequest, sink: (e: AssistantStreamEvent) => void) => {
        sink({ requestId: 'r1', type: 'done', data: {} })
        return { requestId: 'r1' }
      }),
      cancel: vi.fn(() => true),
    }
    registerAssistantHandlers(service)

    await handler(IPC_CHANNELS.ASSISTANT_ASK)({ sender: { send, isDestroyed: () => true } }, valid)

    expect(send).not.toHaveBeenCalled()
  })

  it.each([
    ['requestId 없음', { ...valid, requestId: '' }],
    ['질문 501자', { ...valid, question: '가'.repeat(501) }],
    ['빈 질문', { ...valid, question: '   ' }],
    ['as_of 음수', { ...valid, asOfSequence: -1 }],
    ['대화 7개', { ...valid, history: Array.from({ length: 7 }, () => ({ role: 'user', text: 'q' })) }],
  ])('형식이 틀리면(%s) VALIDATION 으로 거절하고 서비스를 부르지 않는다', async (_name, payload) => {
    const service = { ask: vi.fn(), cancel: vi.fn() }
    registerAssistantHandlers(service)

    await expectIpcError(
      handler(IPC_CHANNELS.ASSISTANT_ASK)({ sender: { send: vi.fn(), isDestroyed: () => false } }, payload) as Promise<unknown>,
      'VALIDATION',
    )
    expect(service.ask).not.toHaveBeenCalled()
  })

  it('CANCEL 은 requestId 로 서비스의 cancel 을 부른다', async () => {
    const service = { ask: vi.fn(), cancel: vi.fn(() => true) }
    registerAssistantHandlers(service)

    await expect(handler(IPC_CHANNELS.ASSISTANT_CANCEL)({}, { requestId: 'r1' })).resolves.toBe(true)
    expect(service.cancel).toHaveBeenCalledWith('r1')
  })
})
