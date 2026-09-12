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

  it('정규화 후 8/10자리가 아니면 VALIDATION 에러', async () => {
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
      /계좌번호는 숫자 8자리/,
    )

    // 검증 실패 시 keytar 에 아무것도 남지 않아야 한다
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBeNull()
  })

  it('8자리 계좌번호도 허용한다 (상품코드는 parseAccountNo 가 01 로 기본 적용)', async () => {
    // 10자리만 허용하던 검증은 실제 동작보다 엄격했다. 8자리로 저장된 계좌로 주문이
    // 계속 체결돼 왔는데도 저장 단계에서 거부되어, 멀쩡한 계좌를 다시 입력하게 만들었다.
    registerVaultHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.VAULT_SAVE)

    const result = await handler({} as never, {
      appKey: 'app-key',
      appSecret: 'app-secret',
      accountNo: '50201234',
      isPaperTrading: true,
    })

    expect(result).toEqual({ success: true })
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('50201234')
  })

  it('기존 등록이 있으면 빈 칸은 기존 값을 유지한다', async () => {
    // 수정 폼은 appSecret 을 되보여줄 수 없다(보안). 빈 칸을 재입력 강제로 해석하면
    // HTS ID 하나 바꾸려고 비밀값을 전부 다시 쳐야 한다.
    registerVaultHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.VAULT_SAVE)

    await handler({} as never, {
      appKey: 'orig-key',
      appSecret: 'orig-secret',
      accountNo: '1234567801',
      isPaperTrading: true,
    })

    // HTS ID 만 바꾼다 — 나머지는 빈 칸
    await handler({} as never, {
      appKey: '',
      appSecret: '',
      accountNo: '',
      isPaperTrading: true,
      htsId: 'myhtsid',
    })

    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('orig-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBe('orig-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('1234567801')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-htsId-paper')).toBe('myhtsid')
  })

  it('입력한 필드만 덮어쓴다', async () => {
    registerVaultHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.VAULT_SAVE)

    await handler({} as never, {
      appKey: 'orig-key',
      appSecret: 'orig-secret',
      accountNo: '1234567801',
      isPaperTrading: true,
    })
    await handler({} as never, {
      appKey: '',
      appSecret: 'new-secret',
      accountNo: '',
      isPaperTrading: true,
    })

    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('orig-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBe('new-secret')
  })

  it('신규 등록에서 빈 칸은 여전히 VALIDATION 에러', async () => {
    registerVaultHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.VAULT_SAVE)

    await expectIpcError(
      Promise.resolve(
        handler({} as never, {
          appKey: '',
          appSecret: '',
          accountNo: '',
          isPaperTrading: true,
        }),
      ) as Promise<unknown>,
      'VALIDATION',
      /appKey/,
    )
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
