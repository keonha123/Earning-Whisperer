import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

// setup.ts 의 axios/electron/keytar mock 자동 적용.
import { registerKisHandlers } from '../kisHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { mainState } from '../../store/mainState'
import {
  IpcError,
  deserializeIpcError,
  serializeIpcError,
} from '../../../lib/types/ipcError'

type IpcInvokeHandler = (
  event: unknown,
  ...args: unknown[]
) => unknown | Promise<unknown>

function getRegisteredHandler(channel: string): IpcInvokeHandler {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find((c) => c[0] === channel)
  if (!call) throw new Error(`channel ${channel} 미등록`)
  return call[1] as IpcInvokeHandler
}

/** registerHandler 가 serializeIpcError 로 감싼 throw 를 IpcError 로 복원. */
async function captureIpcError(
  handler: IpcInvokeHandler,
  payload: unknown,
): Promise<IpcError | null> {
  try {
    await handler({} as never, payload)
  } catch (e) {
    return deserializeIpcError(e)
  }
  throw new Error('handler 가 throw 하지 않았습니다.')
}

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  mainState.clear()
})

describe('kisHandlers — KIS_PLACE_MANUAL_ORDER 검증 에러 코드', () => {
  it('qty 0 → IpcErrorCode VALIDATION 으로 preload 왕복 복원 가능', async () => {
    registerKisHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER)

    const err = await captureIpcError(handler, {
      side: 'BUY',
      ticker: 'AAPL',
      qty: 0,
      price: null,
    })

    expect(err).not.toBeNull()
    expect(err?.code).toBe('VALIDATION')
  })

  it('잘못된 지정가 → IpcErrorCode VALIDATION', async () => {
    registerKisHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER)

    const err = await captureIpcError(handler, {
      side: 'BUY',
      ticker: 'AAPL',
      qty: 1,
      price: 0,
    })

    expect(err).not.toBeNull()
    expect(err?.code).toBe('VALIDATION')
  })

  it('주문 진행 중 → IpcErrorCode BUSINESS_RULE, message 는 "주문 진행 중" 유지', async () => {
    mainState.setOrderInProgress(true)
    registerKisHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER)

    const err = await captureIpcError(handler, {
      side: 'BUY',
      ticker: 'AAPL',
      qty: 1,
      price: null,
    })

    expect(err).not.toBeNull()
    expect(err?.code).toBe('BUSINESS_RULE')
    expect(err?.message).toContain('주문이 진행 중')
  })
})

describe('kisHandlers — 에러 코드 serialize/deserialize 왕복', () => {
  it('VALIDATION / BUSINESS_RULE 모두 왕복 복원된다', () => {
    for (const code of ['VALIDATION', 'BUSINESS_RULE'] as const) {
      const restored = deserializeIpcError(
        serializeIpcError(new IpcError(code, `${code} 메시지`)),
      )
      expect(restored).not.toBeNull()
      expect(restored?.code).toBe(code)
      expect(restored?.message).toBe(`${code} 메시지`)
    }
  })
})
