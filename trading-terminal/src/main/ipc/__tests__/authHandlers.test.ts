import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

// setup.ts axios/electron/keytar/KisRateLimiter mock 자동 적용.
vi.mock('../watchlistHandlers', () => ({ start: vi.fn(), stop: vi.fn() }))
vi.mock('../earningsHandlers', () => ({ start: vi.fn(), stop: vi.fn() }))
vi.mock('../stockDetailHandlers', () => ({ clearCache: vi.fn() }))
vi.mock('../../services/PricePoller', () => ({ start: vi.fn(), stop: vi.fn() }))
vi.mock('../../services/StompService', () => ({ StompService: { disconnect: vi.fn() } }))
vi.mock('../../services/SubscriptionManager', () => ({ SubscriptionManager: { reset: vi.fn() } }))
vi.mock('../../services/KisWebSocketService', () => ({
  KisWebSocketService: { connectWithStoredKey: vi.fn(), disconnect: vi.fn() },
}))
vi.mock('../../services/OAuthService', () => ({ OAuthService: { start: vi.fn() } }))

import { registerAuthHandlers, completeLogin } from '../authHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { mainState } from '../../store/mainState'
import { BackendClient } from '../../services/BackendClient'
import { KisService } from '../../services/KisService'

type IpcInvokeHandler = (event: unknown, ...args: unknown[]) => unknown | Promise<unknown>

function getRegisteredHandler(channel: string): IpcInvokeHandler {
  const handleMock = ipcMain.handle as unknown as ReturnType<typeof vi.fn>
  const call = handleMock.mock.calls.find((c) => c[0] === channel)
  if (!call) throw new Error(`channel ${channel} 미등록`)
  return call[1] as IpcInvokeHandler
}

const FAKE_USER = { id: 1, email: 'a@b.c', nickname: 'tester', role: 'USER' }

beforeEach(() => {
  ;(ipcMain.handle as unknown as ReturnType<typeof vi.fn>).mockClear()
  vi.restoreAllMocks()
  mainState.clear()
  vi.spyOn(KisService, 'loadSavedToken').mockResolvedValue(undefined as never)
})

describe('completeLogin — 로그인 후처리', () => {
  it('활성 계좌가 SELF_PAPER 면 accountType 을 SELF_PAPER 로 설정하고 잔고를 초기화한다', async () => {
    vi.spyOn(BackendClient, 'getMe').mockResolvedValue(FAKE_USER)
    vi.spyOn(BackendClient, 'getSettings').mockRejectedValue(new Error('no settings'))
    vi.spyOn(BackendClient, 'getActiveBrokerAccount').mockResolvedValue({
      id: 7,
      accountType: 'SELF_PAPER',
      alias: '모의',
      cashBalance: 1_000_000,
      active: true,
    })
    vi.spyOn(BackendClient, 'getPositions').mockResolvedValue([
      { ticker: 'AAPL', quantity: 3, avgPrice: 100 },
    ])
    const setAccountTypeSpy = vi.spyOn(mainState, 'setAccountType')

    const result = await completeLogin('jwt-token')

    expect(setAccountTypeSpy).toHaveBeenCalledWith('SELF_PAPER')
    expect(mainState.accountType).toBe('SELF_PAPER')
    expect(mainState.selfPaperCash).toBe(1_000_000)
    expect(result.user).toEqual(FAKE_USER)
    expect(result.accountType).toBe('SELF_PAPER')
  })

  it('getMe 실패 시 backendToken 을 남기지 않고 rethrow 한다', async () => {
    vi.spyOn(BackendClient, 'getMe').mockRejectedValue(new Error('401'))

    await expect(completeLogin('jwt-token')).rejects.toThrow('401')
    expect(mainState.backendToken).toBeNull()
  })
})

describe('AUTH_LOGIN', () => {
  it('getMe 가 실패하면 로그인은 실패하고 backendToken 이 남지 않는다', async () => {
    vi.spyOn(BackendClient, 'login').mockResolvedValue({ token: 'jwt-token', user: null })
    vi.spyOn(BackendClient, 'getMe').mockRejectedValue(new Error('401 Unauthorized'))

    registerAuthHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.AUTH_LOGIN)

    await expect(handler({} as never, { email: 'a@b.c', password: 'pw' })).rejects.toBeDefined()
    expect(mainState.backendToken).toBeNull()
  })
})

describe('AUTH_LOGOUT', () => {
  it('로그아웃 시 KisService.invalidateRuntime 을 호출해 refreshTimer 를 정리한다', () => {
    const invalidateRuntimeSpy = vi.spyOn(KisService, 'invalidateRuntime').mockImplementation(() => {})

    registerAuthHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.AUTH_LOGOUT)
    handler({} as never, undefined)

    expect(invalidateRuntimeSpy).toHaveBeenCalledTimes(1)
  })
})
