import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'
import keytar from 'keytar'

// setup.ts axios/electron/keytar/KisRateLimiter mock 자동 적용.
import { registerVaultHandlers } from '../vaultHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { mainState } from '../../store/mainState'
import { KisService } from '../../services/KisService'
import { expectIpcError } from '../../../test/ipcErrorTestUtils'

const KEYTAR_SERVICE = 'EarningWhisperer'

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
  mainState.clear()
  mainState.setPaperTrading(true)
  // 저장 후 토큰 발급 시도는 본 테스트 관심사가 아니므로 no-op 로 대체
  vi.spyOn(KisService, 'issueToken').mockResolvedValue(undefined)
})

describe('vaultHandlers — 계좌번호 정규화/검증', () => {
  it("'12345678-01' 저장 시 keytar 에는 숫자만 남는다", async () => {
    registerVaultHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.VAULT_SAVE)

    const result = await handler({} as never, {
      appKey: 'app-key',
      appSecret: 'app-secret',
      accountNo: '12345678-01',
      isPaperTrading: true,
    })

    expect(result).toEqual({ success: true })
    const stored = await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')
    expect(stored).toBe('1234567801')
  })

  it('정규화 후 10자리가 아니면 VALIDATION 에러', async () => {
    registerVaultHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.VAULT_SAVE)

    await expectIpcError(
      Promise.resolve(
        handler({} as never, {
          appKey: 'app-key',
          appSecret: 'app-secret',
          accountNo: '1234',
          isPaperTrading: true,
        }),
      ) as Promise<unknown>,
      'VALIDATION',
      /계좌번호는 숫자 10자리/,
    )

    // 검증 실패 시 keytar 에 아무것도 남지 않아야 한다
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBeNull()
  })

  it('공백만 있는 accountNo 는 기존과 동일하게 VALIDATION 에러', async () => {
    registerVaultHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.VAULT_SAVE)

    await expectIpcError(
      Promise.resolve(
        handler({} as never, {
          appKey: 'app-key',
          appSecret: 'app-secret',
          accountNo: '   ',
          isPaperTrading: true,
        }),
      ) as Promise<unknown>,
      'VALIDATION',
      /accountNo/,
    )
  })
})
