import { describe, it, expect, vi } from 'vitest'

/**
 * KisKeyForm 의 순수 helper 테스트.
 *   - validateKisKeyInput: 신규 등록은 세 칸 필수, 수정은 빈 칸 허용(기존 값 유지)
 *   - toVaultSavePayload: 공백 정리 · 모드 변환 · HTS ID 빈 칸 전달(삭제 반영)
 *
 * 모듈 import 시 react-hot-toast 사이드 이펙트가 따라오므로 mock 으로 차단한다.
 */
vi.mock('react-hot-toast', () => {
  const fn = vi.fn()
  const defaultExport = Object.assign(fn, { error: vi.fn(), custom: vi.fn(), dismiss: vi.fn() })
  return { default: defaultExport, Toaster: () => null }
})

const { validateKisKeyInput, toVaultSavePayload } = await import('../KisKeyForm')

const FULL = { appKey: 'PSabc', appSecret: 'secret', accountNo: '5012345601', htsId: '' }

describe('validateKisKeyInput', () => {
  it('신규 등록: 세 칸이 모두 있으면 통과 (HTS ID 는 선택)', () => {
    expect(validateKisKeyInput(FULL, true)).toBeNull()
  })

  it('신규 등록: 한 칸이라도 비거나 공백뿐이면 오류', () => {
    expect(validateKisKeyInput({ ...FULL, appKey: '' }, true)).not.toBeNull()
    expect(validateKisKeyInput({ ...FULL, appSecret: '   ' }, true)).not.toBeNull()
    expect(validateKisKeyInput({ ...FULL, accountNo: '' }, true)).not.toBeNull()
  })

  it('수정: 모든 칸이 비어 있어도 통과 — 빈 칸은 기존 값 유지', () => {
    expect(validateKisKeyInput({ appKey: '', appSecret: '', accountNo: '', htsId: '' }, false)).toBeNull()
  })
})

describe('toVaultSavePayload', () => {
  it('앞뒤 공백을 지우고 모드를 isPaperTrading 으로 바꾼다', () => {
    const payload = toVaultSavePayload(
      { appKey: ' PSabc ', appSecret: ' s ', accountNo: ' 50123456-01 ', htsId: ' myid ' },
      'paper',
    )
    expect(payload).toEqual({
      appKey: 'PSabc',
      appSecret: 's',
      accountNo: '50123456-01',
      isPaperTrading: true,
      htsId: 'myid',
    })
  })

  it('실전 모드는 isPaperTrading false', () => {
    expect(toVaultSavePayload(FULL, 'real').isPaperTrading).toBe(false)
  })

  it('HTS ID 빈 칸은 빈 문자열로 보낸다 — VAULT_SAVE 가 삭제로 처리한다', () => {
    expect(toVaultSavePayload(FULL, 'paper').htsId).toBe('')
  })
})
