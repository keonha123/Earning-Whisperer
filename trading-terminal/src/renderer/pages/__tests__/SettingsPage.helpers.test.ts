import { describe, it, expect, vi } from 'vitest'

/**
 * SettingsPage 의 카드 삭제 분기 helper (decideCardDelete) 시나리오 테스트.
 *
 * 검증 대상 (review hotfix #5):
 *   - 활성 모드 키 [삭제] + 다른 모드 등록됨 → 자동 전환 분기
 *   - 활성 모드 키 [삭제] + 양쪽 미등록 됨 → 설정에 머무는 분기
 *   - 비활성 모드 키 [삭제] → 활성 운영 영향 없음 (inactive-keep)
 *
 * 컴포넌트 import 시 사이드 이펙트 차단을 위해 react-hot-toast / react-router-dom mock.
 */

vi.mock('react-hot-toast', () => {
  const fn = vi.fn()
  const defaultExport = Object.assign(fn, {
    error: vi.fn(),
    custom: vi.fn(),
    dismiss: vi.fn(),
  })
  return { default: defaultExport, Toaster: () => null }
})

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))

const { decideCardDelete, parseKisParam } = await import('../SettingsPage')

describe('decideCardDelete — 카드 삭제 분기 결정', () => {
  it('활성(paper) 모드 [삭제] + real 등록됨 → active-switch (real 로 자동 전환)', () => {
    const result = decideCardDelete('paper', true, { paper: true, real: true })
    expect(result).toEqual({ kind: 'active-switch', switchTo: 'real' })
  })

  it('활성(real) 모드 [삭제] + paper 등록됨 → active-switch (paper 로 자동 전환)', () => {
    const result = decideCardDelete('real', false, { paper: true, real: true })
    expect(result).toEqual({ kind: 'active-switch', switchTo: 'paper' })
  })

  it('활성(paper) 모드 [삭제] + real 미등록 → active-none-left (설정에 머묾)', () => {
    // paper 만 등록된 상태에서 paper 삭제 → 양쪽 미등록 됨
    const result = decideCardDelete('paper', true, { paper: true, real: false })
    expect(result).toEqual({ kind: 'active-none-left' })
  })

  it('활성(real) 모드 [삭제] + paper 미등록 → active-none-left', () => {
    const result = decideCardDelete('real', false, { paper: false, real: true })
    expect(result).toEqual({ kind: 'active-none-left' })
  })

  it('비활성(real) 모드 [삭제] (활성 paper) → inactive-keep (활성 운영 영향 없음)', () => {
    const result = decideCardDelete('real', true, { paper: true, real: true })
    expect(result).toEqual({ kind: 'inactive-keep' })
  })

  it('비활성(paper) 모드 [삭제] (활성 real) → inactive-keep', () => {
    const result = decideCardDelete('paper', false, { paper: true, real: true })
    expect(result).toEqual({ kind: 'inactive-keep' })
  })
})

describe('parseKisParam — 주문 시트에서 넘어온 ?kis 값', () => {
  it('paper · real 만 받는다', () => {
    expect(parseKisParam('paper')).toBe('paper')
    expect(parseKisParam('real')).toBe('real')
  })

  it('없거나 모르는 값은 null — 폼을 펼치지 않는다', () => {
    expect(parseKisParam(null)).toBeNull()
    expect(parseKisParam('')).toBeNull()
    expect(parseKisParam('REAL')).toBeNull()
  })
})
