import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ipcMain } from 'electron'

// setup.ts 의 axios/electron mock 가 자동 적용됨.
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import type { Sp500Stock } from '../../../lib/types/stockList'
import { expectIpcError } from '../../../test/ipcErrorTestUtils'

type IpcInvokeHandler = (event: unknown, ...args: unknown[]) => unknown | Promise<unknown>

function getRegisteredHandler(channel: string): IpcInvokeHandler {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find((c) => c[0] === channel)
  if (!call) throw new Error(`channel ${channel} 미등록`)
  return call[1] as IpcInvokeHandler
}

/** 목록 캐시가 모듈 상태라 매 테스트마다 모듈을 새로 불러 캐시를 비운다. */
async function registerFresh(): Promise<IpcInvokeHandler> {
  vi.resetModules()
  const { registerStockListHandlers } = await import('../stockListHandlers')
  registerStockListHandlers()
  return getRegisteredHandler(IPC_CHANNELS.STOCKS_SP500_GET)
}

const LIST: Sp500Stock[] = [
  { ticker: 'AAPL', companyName: 'Apple', sector: null, marketCapUsd: null, currentPrice: null, changePercent: null },
]

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  vi.spyOn(console, 'warn').mockImplementation(() => undefined)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('stockListHandlers STOCKS_SP500_GET', () => {
  it('캐시가 없는데 조회에 실패하면 오류를 던진다 — 화면이 실패를 표시할 수 있어야 한다', async () => {
    const handler = await registerFresh()
    const { BackendClient } = await import('../../services/BackendClient')
    // resetModules 뒤의 모듈과 같은 IpcError 클래스를 써야 registerHandler 가 코드를 그대로 넘긴다
    const { IpcError } = await import('../../../lib/types/ipcError')
    vi.spyOn(BackendClient, 'getSp500List').mockRejectedValue(new IpcError('NETWORK', 'network'))

    await expectIpcError(handler({} as never) as Promise<unknown>, 'NETWORK')
  })

  it('캐시가 있으면 조회에 실패해도 캐시를 돌려준다', async () => {
    vi.useFakeTimers()
    const handler = await registerFresh()
    const { BackendClient } = await import('../../services/BackendClient')
    const spy = vi.spyOn(BackendClient, 'getSp500List').mockResolvedValueOnce(LIST)

    expect(await handler({} as never)).toEqual(LIST)

    // 캐시 유효 시간(5분)이 지나 다시 조회하게 만든다
    vi.advanceTimersByTime(5 * 60 * 1000 + 1)
    spy.mockRejectedValueOnce(new Error('network'))

    expect(await handler({} as never)).toEqual(LIST)
    expect(spy).toHaveBeenCalledTimes(2)
  })
})
