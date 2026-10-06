import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

// setup.ts 의 axios/electron mock 가 자동 적용됨.
import { BackendClient } from '../../services/BackendClient'
import { registerGlossaryHandlers } from '../glossaryHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { IpcError } from '../../../lib/types/ipcError'
import { expectIpcError } from '../../../test/ipcErrorTestUtils'

type IpcInvokeHandler = (event: unknown, ...args: unknown[]) => unknown | Promise<unknown>

function getRegisteredHandler(channel: string): IpcInvokeHandler {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find((c) => c[0] === channel)
  if (!call) throw new Error(`channel ${channel} 미등록`)
  return call[1] as IpcInvokeHandler
}

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
})

describe('glossaryHandlers', () => {
  it('정상 응답은 그대로 넘긴다 (검증은 renderer store 가 한다)', async () => {
    const fixture = { version: 2, terms: [{ term: 'comp sales', aliases: [], ko: '기존점 매출', category: 'retail' }] }
    const spy = vi.spyOn(BackendClient, 'getGlossary').mockResolvedValue(fixture)

    registerGlossaryHandlers()
    const result = await getRegisteredHandler(IPC_CHANNELS.GLOSSARY_GET)({} as never)

    expect(result).toEqual(fixture)
    spy.mockRestore()
  })

  it('일반 실패는 null 로 돌려준다 — 사전 없이도 자막 · 번역은 보여야 한다', async () => {
    const spy = vi.spyOn(BackendClient, 'getGlossary').mockRejectedValue(new Error('network'))
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    registerGlossaryHandlers()
    const result = await getRegisteredHandler(IPC_CHANNELS.GLOSSARY_GET)({} as never)

    expect(result).toBeNull()
    spy.mockRestore()
    errSpy.mockRestore()
  })

  it('AUTH_EXPIRED 는 다른 IPC 와 같은 규약으로 rethrow 한다', async () => {
    const spy = vi
      .spyOn(BackendClient, 'getGlossary')
      .mockRejectedValue(new IpcError('AUTH_EXPIRED', '인증 만료'))

    registerGlossaryHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.GLOSSARY_GET)

    await expectIpcError(handler({} as never) as Promise<unknown>, 'AUTH_EXPIRED')
    spy.mockRestore()
  })
})
