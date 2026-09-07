import { describe, it, expect, vi, beforeEach } from 'vitest'

// electron mock — setup.ts 의 기본 mock 에 shell 을 추가한 파일 로컬 버전.
vi.mock('electron', () => ({
  shell: { openExternal: vi.fn(async () => undefined) },
  BrowserWindow: { getAllWindows: vi.fn(() => []) },
  ipcMain: { handle: vi.fn(), on: vi.fn() },
  app: { getPath: vi.fn(() => '/tmp'), on: vi.fn(), quit: vi.fn() },
}))
vi.mock('../../ipc/authHandlers', () => ({
  registerAuthHandlers: vi.fn(),
  completeLogin: vi.fn(),
}))

import { OAuthService } from '../OAuthService'
import { BackendClient } from '../BackendClient'
import { completeLogin } from '../../ipc/authHandlers'

const FAKE_RESULT = {
  user: { id: 1, email: 'a@b.c', nickname: 'tester', role: 'USER' },
  settings: null,
  accountType: 'SELF_PAPER',
}

/** 실제 HTTP 서버를 띄우지 않고 콜백 처리 경로만 구동하기 위한 pending flow 주입. */
function seedPendingFlow(resolve: (v: unknown) => void, reject: (e: Error) => void): void {
  const svc = OAuthService as unknown as { pending: unknown }
  svc.pending = {
    provider: 'google',
    state: 'STATE-123',
    codeVerifier: 'VERIFIER',
    startedAt: Date.now(),
    server: { close: vi.fn() },
    timeoutHandle: setTimeout(() => undefined, 0),
    resolve,
    reject,
    processing: false,
  }
}

beforeEach(() => {
  vi.mocked(completeLogin).mockReset()
  ;(OAuthService as unknown as { pending: unknown }).pending = null
})

describe('OAuthService — 콜백 성공 경로', () => {
  it('백엔드 교환 후 completeLogin(token) 을 호출하고 그 결과로 흐름을 resolve 한다', async () => {
    vi.spyOn(BackendClient, 'oauthCallback').mockResolvedValue({ token: 'oauth-jwt', user: null })
    vi.mocked(completeLogin).mockResolvedValue(FAKE_RESULT as never)

    const resolve = vi.fn()
    const reject = vi.fn()
    seedPendingFlow(resolve, reject)

    const req = { method: 'GET', url: '/auth/callback?code=CODE-1&state=STATE-123' }
    const res = { writeHead: vi.fn(), end: vi.fn() }

    await (
      OAuthService as unknown as {
        handleRequest: (r: unknown, s: unknown) => Promise<void>
      }
    ).handleRequest(req, res)

    expect(vi.mocked(completeLogin)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(completeLogin)).toHaveBeenCalledWith('oauth-jwt')
    expect(reject).not.toHaveBeenCalled()
    expect(resolve).toHaveBeenCalledWith(FAKE_RESULT)
  })
})
