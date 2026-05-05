import { describe, it, expect, vi } from 'vitest'

/**
 * AuthPage 의 KisVaultDualForm 핵심 helper 시나리오 테스트.
 *
 * 검증 대상 (review hotfix #2 + #5):
 *   - resolveSaveOrder: 한쪽만 입력 / 양쪽 입력 + 활성 모드별 저장 순서
 *   - composePartialFailureMessage: 부분 저장 실패 시 어느 카드 실패인지 메시지에 명시
 *
 * AuthPage 모듈 import 시 react-hot-toast / react-router-dom 사이드 이펙트가 따라오므로
 * 테스트 친화적 mock 으로 차단 (Toast.test.ts 패턴 재사용).
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
}))

const {
  resolveSaveOrder,
  composePartialFailureMessage,
  isCardEmpty,
  isCardComplete,
  EMPTY_CARD,
} = await import('../AuthPage')

describe('resolveSaveOrder — 저장 순서 결정 (활성 모드 우선)', () => {
  it('paper 만 입력 → [paper] (활성 모드 무관)', () => {
    expect(resolveSaveOrder(true, false, 'paper')).toEqual(['paper'])
    expect(resolveSaveOrder(true, false, 'real')).toEqual(['paper'])
  })

  it('real 만 입력 → [real]', () => {
    expect(resolveSaveOrder(false, true, 'paper')).toEqual(['real'])
    expect(resolveSaveOrder(false, true, 'real')).toEqual(['real'])
  })

  it('양쪽 입력 + paper 활성 → [paper, real] (활성 먼저)', () => {
    expect(resolveSaveOrder(true, true, 'paper')).toEqual(['paper', 'real'])
  })

  it('양쪽 입력 + real 활성 → [real, paper]', () => {
    expect(resolveSaveOrder(true, true, 'real')).toEqual(['real', 'paper'])
  })

  it('양쪽 미입력 → []', () => {
    expect(resolveSaveOrder(false, false, 'paper')).toEqual([])
  })
})

describe('composePartialFailureMessage — 부분 실패 메시지 (review hotfix #2)', () => {
  it('실패 없음 → null (호출 측이 onSuccess 트리거)', () => {
    expect(composePartialFailureMessage(['paper', 'real'], [])).toBeNull()
    expect(composePartialFailureMessage(['paper'], [])).toBeNull()
    expect(composePartialFailureMessage([], [])).toBeNull()
  })

  it('첫 카드(paper) 성공 + 둘째 카드(real) 실패 → 어느 카드 실패인지 메시지에 명시', () => {
    const msg = composePartialFailureMessage(
      ['paper'],
      [{ mode: 'real', message: 'KIS 거부' }],
    )
    expect(msg).not.toBeNull()
    expect(msg).toContain('모의')
    expect(msg).toContain('실전 키 저장 실패')
    expect(msg).toContain('KIS 거부')
    expect(msg).toContain('설정 페이지에서 추가 등록 가능합니다')
  })

  it('첫 카드(real) 성공 + 둘째 카드(paper) 실패 → real 라벨 표기', () => {
    const msg = composePartialFailureMessage(
      ['real'],
      [{ mode: 'paper', message: 'invalid key' }],
    )
    expect(msg).toContain('실전 키는 저장됐지만')
    expect(msg).toContain('모의 키 저장 실패: invalid key')
  })

  it('양쪽 다 실패 → 양쪽 모두 명시 (성공 라인 없음)', () => {
    const msg = composePartialFailureMessage(
      [],
      [
        { mode: 'paper', message: 'A' },
        { mode: 'real', message: 'B' },
      ],
    )
    expect(msg).not.toBeNull()
    expect(msg).toContain('모의 키 저장 실패: A')
    expect(msg).toContain('실전 키 저장 실패: B')
    // 성공 라인은 포함되지 않아야 함
    expect(msg).not.toContain('저장됐지만')
    expect(msg).not.toContain('추가 등록')
  })
})

describe('isCardEmpty / isCardComplete — 입력 검증', () => {
  it('빈 카드 → empty true / complete false', () => {
    expect(isCardEmpty(EMPTY_CARD)).toBe(true)
    expect(isCardComplete(EMPTY_CARD)).toBe(false)
  })

  it('한 필드만 채움 → empty false (입력 시작) / complete false (부분 입력)', () => {
    const partial = { appKey: 'k', appSecret: '', accountNo: '' }
    expect(isCardEmpty(partial)).toBe(false)
    expect(isCardComplete(partial)).toBe(false)
  })

  it('세 필드 모두 채움 → complete true', () => {
    const full = { appKey: 'k', appSecret: 's', accountNo: 'a' }
    expect(isCardComplete(full)).toBe(true)
  })

  it('공백만 들어간 필드 → complete false (trim 후 빈 문자열)', () => {
    const blanks = { appKey: '   ', appSecret: 's', accountNo: 'a' }
    expect(isCardComplete(blanks)).toBe(false)
  })
})
