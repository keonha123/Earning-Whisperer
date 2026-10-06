import { describe, it, expect, vi } from 'vitest'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'
import { decideAfterLogin, saveOfferedKey } from '../kisOnboarding'

describe('decideAfterLogin — 로그인 뒤 이동', () => {
  it('KIS 계정 + 키 없음 → 키 등록 권유', () => {
    expect(decideAfterLogin({ paper: false, real: false }, 'KIS_PAPER')).toBe('offer')
    expect(decideAfterLogin({ paper: false, real: false }, undefined)).toBe('offer')
  })

  it('한쪽이라도 키 있음 → 홈', () => {
    expect(decideAfterLogin({ paper: true, real: false }, 'KIS_PAPER')).toBe('home')
    expect(decideAfterLogin({ paper: false, real: true }, 'KIS_REAL')).toBe('home')
  })

  it('키 조회 실패(null) → 홈 — 권유 화면이 기존 키를 덮어쓰지 않게', () => {
    expect(decideAfterLogin(null, 'KIS_PAPER')).toBe('home')
  })

  it('페이퍼 계정은 키가 없어도 홈', () => {
    expect(decideAfterLogin({ paper: false, real: false }, 'SELF_PAPER')).toBe('home')
    expect(decideAfterLogin(null, 'SELF_PAPER')).toBe('home')
  })
})

const PAYLOAD = { appKey: 'k', appSecret: 's', accountNo: '5012345601', isPaperTrading: false, htsId: '' }

/** 채널별 응답을 정해 둔 가짜 invoke. 호출 순서를 calls 에 남긴다. */
function makeInvoke(opts: { prev: unknown; saveError?: Error; rollbackError?: Error }) {
  const calls: [string, unknown][] = []
  const invoke = vi.fn(async (channel: string, payload?: unknown) => {
    calls.push([channel, payload])
    if (channel === IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING) return opts.prev
    if (channel === IPC_CHANNELS.VAULT_SAVE && opts.saveError) throw opts.saveError
    if (
      channel === IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING &&
      opts.rollbackError &&
      calls.filter(([c]) => c === IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING).length > 1
    ) {
      throw opts.rollbackError
    }
    return undefined
  })
  return { invoke: invoke as never, calls }
}

describe('saveOfferedKey — 권유 화면 저장 순서', () => {
  it('성공: GET → SET(고른 모드) → VAULT_SAVE 순서', async () => {
    const { invoke, calls } = makeInvoke({ prev: true })
    await saveOfferedKey(invoke, PAYLOAD)
    expect(calls).toEqual([
      [IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING, undefined],
      [IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: false }],
      [IPC_CHANNELS.VAULT_SAVE, PAYLOAD],
    ])
  })

  it('VAULT_SAVE 실패: 이전 모드로 되돌리고 원래 오류를 던진다', async () => {
    const saveError = new Error('계좌번호 오류')
    const { invoke, calls } = makeInvoke({ prev: true, saveError })
    await expect(saveOfferedKey(invoke, PAYLOAD)).rejects.toBe(saveError)
    expect(calls.at(-1)).toEqual([IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING, { value: true }])
  })

  it('VAULT_SAVE 실패 + 이전 모드가 같으면 되돌리지 않는다', async () => {
    const { invoke, calls } = makeInvoke({ prev: false, saveError: new Error('x') })
    await expect(saveOfferedKey(invoke, PAYLOAD)).rejects.toThrow('x')
    expect(calls.filter(([c]) => c === IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)).toHaveLength(1)
  })

  it('되돌리기까지 실패해도 원래 저장 오류를 던진다', async () => {
    const saveError = new Error('save')
    const { invoke } = makeInvoke({ prev: true, saveError, rollbackError: new Error('rollback') })
    await expect(saveOfferedKey(invoke, PAYLOAD)).rejects.toBe(saveError)
  })

  it('이전 모드가 boolean 이 아니면(조회 이상) 되돌리지 않는다', async () => {
    const { invoke, calls } = makeInvoke({ prev: null, saveError: new Error('x') })
    await expect(saveOfferedKey(invoke, PAYLOAD)).rejects.toThrow('x')
    expect(calls.filter(([c]) => c === IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING)).toHaveLength(1)
  })

  it('SET 이 실패하면 VAULT_SAVE 를 부르지 않는다', async () => {
    const calls: string[] = []
    const invoke = (async (channel: string) => {
      calls.push(channel)
      if (channel === IPC_CHANNELS.SETTINGS_GET_PAPER_TRADING) return true
      if (channel === IPC_CHANNELS.SETTINGS_SET_PAPER_TRADING) throw new Error('set')
      return undefined
    }) as never
    await expect(saveOfferedKey(invoke, PAYLOAD)).rejects.toThrow('set')
    expect(calls).not.toContain(IPC_CHANNELS.VAULT_SAVE)
  })
})
