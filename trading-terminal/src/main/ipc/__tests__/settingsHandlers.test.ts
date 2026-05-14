import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'
import keytar from 'keytar'

// setup.ts axios/electron/keytar/KisRateLimiter mock 자동 적용.
import { registerSettingsHandlers } from '../settingsHandlers'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { mainState } from '../../store/mainState'
import { kisLimiter } from '../../services/KisRateLimiter'
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
  vi.mocked(kisLimiter.setRate).mockClear()
  mainState.clear()
  mainState.setPaperTrading(true)
  // 디폴트: 로그인 상태로 시드 — H8 미로그인 케이스에서만 명시적으로 null 로 덮음.
  mainState.setBackendToken('test-jwt')
})

describe('settingsHandlers — paper-trading 토글', () => {
  it('GET 핸들러는 mainState.isPaperTrading 그대로 반환', async () => {
    mainState.setPaperTrading(false)
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING)
    const result = await handler({} as never)

    expect(result).toBe(false)
  })

  it('SET value=false → mainState 변경 + kisLimiter.setRate(18) + invalidateRuntime + keytar 저장', async () => {
    const invalidateSpy = vi.spyOn(KisService, 'invalidateRuntime').mockImplementation(() => undefined)
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)
    const result = await handler({} as never, { value: false })

    expect(result).toEqual({ ok: true })
    expect(mainState.isPaperTrading).toBe(false)
    expect(vi.mocked(kisLimiter.setRate)).toHaveBeenCalledWith(18)
    expect(invalidateSpy).toHaveBeenCalledTimes(1)

    // keytar 영속화 — '0' 저장
    const saved = await keytar.getPassword(KEYTAR_SERVICE, 'kis-isPaperTrading')
    expect(saved).toBe('0')

    invalidateSpy.mockRestore()
  })

  it('SET value=true → kisLimiter.setRate(1.0) + keytar에 \'1\' 저장', async () => {
    mainState.setPaperTrading(false)
    const invalidateSpy = vi.spyOn(KisService, 'invalidateRuntime').mockImplementation(() => undefined)
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)
    await handler({} as never, { value: true })

    expect(mainState.isPaperTrading).toBe(true)
    expect(vi.mocked(kisLimiter.setRate)).toHaveBeenCalledWith(1.0)
    expect(invalidateSpy).toHaveBeenCalledTimes(1)

    const saved = await keytar.getPassword(KEYTAR_SERVICE, 'kis-isPaperTrading')
    expect(saved).toBe('1')

    invalidateSpy.mockRestore()
  })
})

describe('settingsHandlers — paper-trading 토글 H5 가드', () => {
  it('isOrderInProgress=true 상태에서 SET 호출 → throw', async () => {
    mainState.setOrderInProgress(true)
    const invalidateSpy = vi.spyOn(KisService, 'invalidateRuntime').mockImplementation(() => undefined)
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)
    await expect(handler({} as never, { value: false })).rejects.toThrow(/주문 진행 중/)

    // 거부됐으므로 mainState/keytar/setRate/invalidateRuntime 모두 미변경
    expect(mainState.isPaperTrading).toBe(true)
    expect(vi.mocked(kisLimiter.setRate)).not.toHaveBeenCalled()
    expect(invalidateSpy).not.toHaveBeenCalled()

    mainState.setOrderInProgress(false)
    invalidateSpy.mockRestore()
  })

  it('payload.value 가 boolean 이 아니면 throw (string "true")', async () => {
    const invalidateSpy = vi.spyOn(KisService, 'invalidateRuntime').mockImplementation(() => undefined)
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)
    await expect(
      handler({} as never, { value: 'true' as unknown as boolean }),
    ).rejects.toThrow(/boolean/)

    expect(vi.mocked(kisLimiter.setRate)).not.toHaveBeenCalled()
    expect(invalidateSpy).not.toHaveBeenCalled()

    invalidateSpy.mockRestore()
  })

  it('payload.value 가 undefined 이면 throw', async () => {
    const invalidateSpy = vi.spyOn(KisService, 'invalidateRuntime').mockImplementation(() => undefined)
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)
    await expect(handler({} as never, undefined)).rejects.toThrow(/boolean/)

    expect(vi.mocked(kisLimiter.setRate)).not.toHaveBeenCalled()
    expect(invalidateSpy).not.toHaveBeenCalled()

    invalidateSpy.mockRestore()
  })

  it('H8 — 미로그인(backendToken=null) 상태에서 SET 호출 시 throw + state 미변경', async () => {
    // 디폴트로 시드된 토큰 제거 → 미로그인 상태 재현
    mainState.setBackendToken(null)
    const invalidateSpy = vi
      .spyOn(KisService, 'invalidateRuntime')
      .mockImplementation(() => undefined)
    const setPasswordMock = vi.mocked(keytar.setPassword)
    setPasswordMock.mockClear()
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)
    await expect(handler({} as never, { value: false })).rejects.toThrow(/로그인/)

    // 미로그인 거부 — mainState 변경 없음, side effect 전무
    expect(mainState.isPaperTrading).toBe(true)
    expect(vi.mocked(kisLimiter.setRate)).not.toHaveBeenCalled()
    expect(invalidateSpy).not.toHaveBeenCalled()
    const paperTradingCalls = setPasswordMock.mock.calls.filter(
      (c) => c[1] === 'kis-isPaperTrading',
    )
    expect(paperTradingCalls).toHaveLength(0)

    invalidateSpy.mockRestore()
  })

  it('IpcError code 분류 — AUTH_REQUIRED / VALIDATION / BUSINESS_RULE', async () => {
    registerSettingsHandlers()
    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)

    // AUTH_REQUIRED — 미로그인
    mainState.setBackendToken(null)
    await expectIpcError(
      handler({} as never, { value: false }) as Promise<unknown>,
      'AUTH_REQUIRED',
      /로그인/,
    )
    mainState.setBackendToken('test-jwt')

    // VALIDATION — boolean 아님
    await expectIpcError(
      handler({} as never, { value: 'true' as unknown as boolean }) as Promise<unknown>,
      'VALIDATION',
      /boolean/,
    )

    // BUSINESS_RULE — 주문 진행 중
    mainState.setOrderInProgress(true)
    await expectIpcError(
      handler({} as never, { value: false }) as Promise<unknown>,
      'BUSINESS_RULE',
      /주문 진행 중/,
    )
    mainState.setOrderInProgress(false)
  })

  it('이미 같은 값으로 set 시 no-op — setRate / invalidateRuntime / keytar.setPassword 미호출', async () => {
    // 디폴트 paper=true 상태에서 다시 true 로 set
    const invalidateSpy = vi.spyOn(KisService, 'invalidateRuntime').mockImplementation(() => undefined)
    const setPasswordMock = vi.mocked(keytar.setPassword)
    setPasswordMock.mockClear()
    registerSettingsHandlers()

    const handler = getRegisteredHandler(IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)
    const result = await handler({} as never, { value: true })

    expect(result).toEqual({ ok: true, noop: true })
    expect(vi.mocked(kisLimiter.setRate)).not.toHaveBeenCalled()
    expect(invalidateSpy).not.toHaveBeenCalled()
    // keytar.setPassword 도 호출되지 않아야 한다 (paper-trading 키 저장 skip)
    const paperTradingCalls = setPasswordMock.mock.calls.filter(
      (c) => c[1] === 'kis-isPaperTrading',
    )
    expect(paperTradingCalls).toHaveLength(0)

    invalidateSpy.mockRestore()
  })
})
