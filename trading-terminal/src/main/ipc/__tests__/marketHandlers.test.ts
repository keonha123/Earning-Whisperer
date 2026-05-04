import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

// setup.ts 의 axios/electron mock 가 자동 적용됨.
import { BackendClient } from '../../services/BackendClient'
import { registerMarketHandlers } from '../marketHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { IpcError } from '../../../lib/types/ipcError'
import { expectIpcError } from '../../../test/ipcErrorTestUtils'

type IpcInvokeHandler = (
  event: unknown,
  ...args: unknown[]
) => unknown | Promise<unknown>

/**
 * registerMarketHandlers() 가 ipcMain.handle 로 등록한 callback 을 추출한다.
 * setup.ts 의 ipcMain mock 은 vi.fn 이라 mock.calls 로 인자를 추적할 수 있다.
 */
function getRegisteredHandler(channel: string): IpcInvokeHandler {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find((c) => c[0] === channel)
  if (!call) throw new Error(`channel ${channel} 미등록`)
  return call[1] as IpcInvokeHandler
}

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
})

describe('marketHandlers', () => {
  it('정상 케이스: BackendClient.getMarketIndices 가 5종 반환 시 그대로 통과', async () => {
    const fixture = [
      { symbol: '10Y', price: 4.32, change_percent: -0.05, trend: 'down', format: 'percent', timestamp: 1714400000 },
      { symbol: 'DXY', price: 105.21, change_percent: 0.12, trend: 'up', format: 'index', timestamp: 1714400000 },
      { symbol: 'NDX', price: 17800.55, change_percent: 0.34, trend: 'up', format: 'index', timestamp: 1714400000 },
      { symbol: 'SPX', price: 5123.4, change_percent: 0.21, trend: 'up', format: 'index', timestamp: 1714400000 },
      { symbol: 'VIX', price: 13.6, change_percent: -1.1, trend: 'down', format: 'index', timestamp: 1714400000 },
    ]
    const spy = vi
      .spyOn(BackendClient, 'getMarketIndices')
      .mockResolvedValue(fixture as never)

    registerMarketHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.MARKET_INDICES_GET)
    const result = await handler({} as never)

    expect(result).toEqual(fixture)
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it('graceful fallback: BackendClient 가 에러를 throw 해도 IPC handler 는 [] 반환', async () => {
    const spy = vi
      .spyOn(BackendClient, 'getMarketIndices')
      .mockRejectedValue(new Error('network'))
    // 콘솔 노이즈 억제
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    registerMarketHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.MARKET_INDICES_GET)
    const result = await handler({} as never)

    expect(result).toEqual([])
    expect(spy).toHaveBeenCalledTimes(1)

    spy.mockRestore()
    errSpy.mockRestore()
  })

  it('AUTH_EXPIRED 는 swallow 하지 않고 rethrow — 다른 IPC 와 일관된 토큰 만료 신호', async () => {
    const spy = vi
      .spyOn(BackendClient, 'getMarketIndices')
      .mockRejectedValue(new IpcError('AUTH_EXPIRED', '인증 만료'))

    registerMarketHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.MARKET_INDICES_GET)

    await expectIpcError(handler({} as never) as Promise<unknown>, 'AUTH_EXPIRED')
    spy.mockRestore()
  })
})
