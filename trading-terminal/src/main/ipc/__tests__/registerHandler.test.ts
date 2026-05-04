import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

import { registerHandler } from '../registerHandler'
import { IpcError, deserializeIpcError } from '../../../lib/types/ipcError'

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

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
})

describe('registerHandler — 정상 경로', () => {
  it('return value 가 그대로 호출자에게 전달됨', async () => {
    registerHandler('test:return', async () => ({ ok: true, items: [1, 2] }))
    const handler = getRegisteredHandler('test:return')

    const result = await handler({} as never)
    expect(result).toEqual({ ok: true, items: [1, 2] })
  })

  it('sync 함수의 return value 도 그대로 전달', async () => {
    registerHandler('test:sync-return', () => 42)
    const handler = getRegisteredHandler('test:sync-return')

    const result = await handler({} as never)
    expect(result).toBe(42)
  })

  it('payload 가 fn 의 두 번째 인자로 전달', async () => {
    const fn = vi.fn(async (_e: unknown, p: { ticker: string }) => p.ticker.toUpperCase())
    registerHandler<{ ticker: string }, string>('test:payload', fn)
    const handler = getRegisteredHandler('test:payload')

    const result = await handler({} as never, { ticker: 'aapl' })
    expect(result).toBe('AAPL')
    expect(fn).toHaveBeenCalledWith(expect.anything(), { ticker: 'aapl' })
  })
})

describe('registerHandler — IpcError pass-through', () => {
  it('IpcError throw → code/message/details 보존된 채로 인코딩', async () => {
    registerHandler('test:ipc-error', async () => {
      throw new IpcError('VALIDATION', 'invalid ticker', { field: 'ticker' })
    })
    const handler = getRegisteredHandler('test:ipc-error')

    let caught: unknown
    try {
      await handler({} as never)
    } catch (e) {
      caught = e
    }

    const ipcErr = deserializeIpcError(caught)
    expect(ipcErr).not.toBeNull()
    expect(ipcErr!.code).toBe('VALIDATION')
    expect(ipcErr!.message).toBe('invalid ticker')
    expect(ipcErr!.details).toEqual({ field: 'ticker' })
  })

  it('sync 함수의 IpcError throw 도 동일하게 인코딩', async () => {
    registerHandler('test:ipc-error-sync', () => {
      throw new IpcError('AUTH_REQUIRED', '로그인 필요')
    })
    const handler = getRegisteredHandler('test:ipc-error-sync')

    let caught: unknown
    try {
      await handler({} as never)
    } catch (e) {
      caught = e
    }

    const ipcErr = deserializeIpcError(caught)
    expect(ipcErr).not.toBeNull()
    expect(ipcErr!.code).toBe('AUTH_REQUIRED')
  })
})

describe('registerHandler — generic Error → UNKNOWN wrap', () => {
  it('일반 Error throw → UNKNOWN code 로 wrap, message 보존', async () => {
    registerHandler('test:generic-error', async () => {
      throw new Error('something exploded')
    })
    const handler = getRegisteredHandler('test:generic-error')

    let caught: unknown
    try {
      await handler({} as never)
    } catch (e) {
      caught = e
    }

    const ipcErr = deserializeIpcError(caught)
    expect(ipcErr).not.toBeNull()
    expect(ipcErr!.code).toBe('UNKNOWN')
    expect(ipcErr!.message).toBe('something exploded')
  })

  it('비 Error 값 throw (string) → UNKNOWN + 디폴트 메시지', async () => {
    registerHandler('test:string-throw', async () => {
      throw 'string error'
    })
    const handler = getRegisteredHandler('test:string-throw')

    let caught: unknown
    try {
      await handler({} as never)
    } catch (e) {
      caught = e
    }

    const ipcErr = deserializeIpcError(caught)
    expect(ipcErr).not.toBeNull()
    expect(ipcErr!.code).toBe('UNKNOWN')
    expect(ipcErr!.message).toBe('unknown error')
  })

  it('null throw → UNKNOWN + 디폴트 메시지', async () => {
    registerHandler('test:null-throw', async () => {
      throw null
    })
    const handler = getRegisteredHandler('test:null-throw')

    let caught: unknown
    try {
      await handler({} as never)
    } catch (e) {
      caught = e
    }

    const ipcErr = deserializeIpcError(caught)
    expect(ipcErr).not.toBeNull()
    expect(ipcErr!.code).toBe('UNKNOWN')
  })
})
