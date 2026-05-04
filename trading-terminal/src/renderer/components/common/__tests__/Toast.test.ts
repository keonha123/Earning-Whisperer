import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * showIpcErrorToast / makeToastId / CODE_CONFIG 단위 테스트.
 *
 * react-hot-toast 의 toast.error / toast / toast.custom 을 mock 으로 잡아
 *  - 8개 IpcErrorCode 별 적절한 호출 분기 (custom vs error vs warning toast)
 *  - duration / id / className 옵션 전달 정확도
 *  - AUTH_EXPIRED 의 단일성 toastId
 *  - djb2 hash 의 결정성 (동일 message → 동일 id)
 *  - non-IpcError (Error / string / null) → UNKNOWN fallback
 *  - action 콜백 주입 여부에 따른 toast.custom 분기
 * 를 검증한다.
 *
 * 본 테스트는 node 환경 (jsdom 없음). DOM 렌더는 검증하지 않고 mock 의 호출 인자만 본다.
 */

const { mockToast, mockToastError, mockToastCustom, mockToastDismiss } = vi.hoisted(() => {
  const error = vi.fn()
  const custom = vi.fn()
  const dismiss = vi.fn()
  const fn = vi.fn()
  return {
    mockToast: fn,
    mockToastError: error,
    mockToastCustom: custom,
    mockToastDismiss: dismiss,
  }
})

vi.mock('react-hot-toast', () => {
  // react-hot-toast 의 default export 는 함수이면서 .error / .custom / .dismiss 등을
  // 메서드로 가진 callable namespace. Object.assign 으로 동일 형태 재현.
  const defaultExport = Object.assign(mockToast, {
    error: mockToastError,
    custom: mockToastCustom,
    dismiss: mockToastDismiss,
  })
  return {
    default: defaultExport,
    Toaster: () => null,
  }
})

// import 는 mock 정의 이후. ESM 정적 import 가 동일하게 동작.
const { showIpcErrorToast, makeToastId, CODE_CONFIG, IpcError, setAuthExpiredHandler } = await import(
  '../Toast'
)

beforeEach(() => {
  mockToast.mockReset()
  mockToastError.mockReset()
  mockToastCustom.mockReset()
  mockToastDismiss.mockReset()
  setAuthExpiredHandler(null)
})

describe('makeToastId', () => {
  it('AUTH_EXPIRED 는 항상 단일 고정 id 반환', () => {
    expect(makeToastId('AUTH_EXPIRED', '메시지 A')).toBe('ipc-auth-expired')
    expect(makeToastId('AUTH_EXPIRED', '메시지 B')).toBe('ipc-auth-expired')
    expect(makeToastId('AUTH_EXPIRED', '')).toBe('ipc-auth-expired')
  })

  it('동일 (code, message) → 동일 id (djb2 결정성)', () => {
    const a = makeToastId('VALIDATION', '필드 누락')
    const b = makeToastId('VALIDATION', '필드 누락')
    expect(a).toBe(b)
    expect(a).toMatch(/^ipc-VALIDATION-\d+$/)
  })

  it('다른 message → 다른 id (충돌 회피)', () => {
    const a = makeToastId('VALIDATION', 'message-one')
    const b = makeToastId('VALIDATION', 'message-two')
    expect(a).not.toBe(b)
  })

  it('message 33자 이상은 처음 32자만으로 hash', () => {
    const prefix = 'a'.repeat(32)
    const a = makeToastId('BACKEND_5XX', prefix + 'X')
    const b = makeToastId('BACKEND_5XX', prefix + 'Y')
    expect(a).toBe(b)
  })
})

describe('CODE_CONFIG', () => {
  it('8개 IpcErrorCode 모두 정의돼 있어야 함', () => {
    const codes = [
      'AUTH_REQUIRED',
      'AUTH_EXPIRED',
      'VALIDATION',
      'BUSINESS_RULE',
      'BACKEND_5XX',
      'NETWORK',
      'KIS_ERROR',
      'UNKNOWN',
    ] as const
    for (const c of codes) {
      expect(CODE_CONFIG[c]).toBeDefined()
      expect(['error', 'warning']).toContain(CODE_CONFIG[c].variant)
      expect(CODE_CONFIG[c].fallbackMessage.length).toBeGreaterThan(0)
    }
  })

  it('AUTH_EXPIRED 와 NETWORK 은 duration Infinity (사용자가 직접 닫아야 함)', () => {
    expect(CODE_CONFIG.AUTH_EXPIRED.duration).toBe(Infinity)
    expect(CODE_CONFIG.NETWORK.duration).toBe(Infinity)
  })

  it('AUTH_REQUIRED / AUTH_EXPIRED 는 navigate action 보유', () => {
    expect(CODE_CONFIG.AUTH_REQUIRED.actionKind).toBe('navigate')
    expect(CODE_CONFIG.AUTH_EXPIRED.actionKind).toBe('navigate')
  })

  it('BACKEND_5XX / NETWORK 은 retry action 보유', () => {
    expect(CODE_CONFIG.BACKEND_5XX.actionKind).toBe('retry')
    expect(CODE_CONFIG.NETWORK.actionKind).toBe('retry')
  })

  it('VALIDATION / BUSINESS_RULE / KIS_ERROR / UNKNOWN 은 action 미보유', () => {
    expect(CODE_CONFIG.VALIDATION.actionKind).toBeUndefined()
    expect(CODE_CONFIG.BUSINESS_RULE.actionKind).toBeUndefined()
    expect(CODE_CONFIG.KIS_ERROR.actionKind).toBeUndefined()
    expect(CODE_CONFIG.UNKNOWN.actionKind).toBeUndefined()
  })
})

describe('showIpcErrorToast — code 별 분기', () => {
  it('AUTH_REQUIRED + onNavigate → toast.custom 으로 호출', () => {
    const onNavigate = vi.fn()
    const err = new IpcError('AUTH_REQUIRED', '로그인이 필요합니다.')
    showIpcErrorToast(err, { onNavigate })
    expect(mockToastCustom).toHaveBeenCalledTimes(1)
    expect(mockToastError).not.toHaveBeenCalled()
    const [, opts] = mockToastCustom.mock.calls[0]
    expect(opts.id).toBe(makeToastId('AUTH_REQUIRED', '로그인이 필요합니다.'))
    expect(opts.duration).toBe(8000)
  })

  it('AUTH_REQUIRED 에 onNavigate 미주입 → toast.error 폴백', () => {
    const err = new IpcError('AUTH_REQUIRED', '로그인이 필요합니다.')
    showIpcErrorToast(err)
    expect(mockToastError).toHaveBeenCalledTimes(1)
    expect(mockToastCustom).not.toHaveBeenCalled()
    const [msg, opts] = mockToastError.mock.calls[0]
    expect(msg).toBe('로그인이 필요합니다.')
    expect(opts.duration).toBe(8000)
    expect(opts.id).toBe('ipc-AUTH_REQUIRED-' + opts.id.split('-').pop())
  })

  it('AUTH_EXPIRED + onNavigate → toast.custom + 단일 id + Infinity duration', () => {
    const onNavigate = vi.fn()
    const err = new IpcError('AUTH_EXPIRED', '세션 만료')
    showIpcErrorToast(err, { onNavigate })
    expect(mockToastCustom).toHaveBeenCalledTimes(1)
    const [, opts] = mockToastCustom.mock.calls[0]
    expect(opts.id).toBe('ipc-auth-expired')
    expect(opts.duration).toBe(Infinity)
  })

  it('VALIDATION → toast.warning (toast()) 호출, message 그대로', () => {
    const err = new IpcError('VALIDATION', '이메일 형식이 잘못되었습니다.')
    showIpcErrorToast(err)
    expect(mockToast).toHaveBeenCalledTimes(1)
    expect(mockToastError).not.toHaveBeenCalled()
    expect(mockToastCustom).not.toHaveBeenCalled()
    const [msg, opts] = mockToast.mock.calls[0]
    expect(msg).toBe('이메일 형식이 잘못되었습니다.')
    expect(opts.duration).toBe(4000)
    expect(opts.icon).toBeDefined()
    expect(opts.className).toBe('toast-ipc-warning')
  })

  it('BUSINESS_RULE → warning 5초, message 그대로', () => {
    const err = new IpcError('BUSINESS_RULE', '쿨다운 5분 이내 재진입 불가')
    showIpcErrorToast(err)
    expect(mockToast).toHaveBeenCalledTimes(1)
    const [msg, opts] = mockToast.mock.calls[0]
    expect(msg).toBe('쿨다운 5분 이내 재진입 불가')
    expect(opts.duration).toBe(5000)
  })

  it('BACKEND_5XX + onRetry → toast.custom + 6초', () => {
    const onRetry = vi.fn()
    const err = new IpcError('BACKEND_5XX', '서비스 일시 오류')
    showIpcErrorToast(err, { onRetry })
    expect(mockToastCustom).toHaveBeenCalledTimes(1)
    const [, opts] = mockToastCustom.mock.calls[0]
    expect(opts.duration).toBe(6000)
  })

  it('BACKEND_5XX 에 onRetry 미주입 → toast.error 폴백', () => {
    const err = new IpcError('BACKEND_5XX', '서비스 일시 오류')
    showIpcErrorToast(err)
    expect(mockToastError).toHaveBeenCalledTimes(1)
    expect(mockToastCustom).not.toHaveBeenCalled()
    const [, opts] = mockToastError.mock.calls[0]
    expect(opts.duration).toBe(6000)
    expect(opts.className).toBe('toast-ipc-error')
  })

  it('NETWORK + onRetry → toast.custom + Infinity duration', () => {
    const onRetry = vi.fn()
    const err = new IpcError('NETWORK', '네트워크 끊김')
    showIpcErrorToast(err, { onRetry })
    expect(mockToastCustom).toHaveBeenCalledTimes(1)
    const [, opts] = mockToastCustom.mock.calls[0]
    expect(opts.duration).toBe(Infinity)
  })

  it('KIS_ERROR + details.code 있을 때 message 뒤에 (code) 부착', () => {
    const err = new IpcError('KIS_ERROR', '주문 거부', {
      code: 'EGW00123',
    })
    showIpcErrorToast(err)
    expect(mockToast).toHaveBeenCalledTimes(1)
    const [msg, opts] = mockToast.mock.calls[0]
    expect(msg).toBe('주문 거부 (EGW00123)')
    expect(opts.duration).toBe(7000)
  })

  it('KIS_ERROR + details 없을 때 message 만 표시', () => {
    const err = new IpcError('KIS_ERROR', '주문 거부')
    showIpcErrorToast(err)
    const [msg] = mockToast.mock.calls[0]
    expect(msg).toBe('주문 거부')
  })

  it('UNKNOWN → toast.error 6초', () => {
    const err = new IpcError('UNKNOWN', '뭔가 잘못됐습니다')
    showIpcErrorToast(err)
    expect(mockToastError).toHaveBeenCalledTimes(1)
    const [, opts] = mockToastError.mock.calls[0]
    expect(opts.duration).toBe(6000)
  })
})

describe('showIpcErrorToast — non-IpcError fallback', () => {
  it('plain Error → UNKNOWN 처리 + Error.message 사용', () => {
    showIpcErrorToast(new Error('boom'))
    expect(mockToastError).toHaveBeenCalledTimes(1)
    const [msg, opts] = mockToastError.mock.calls[0]
    expect(msg).toBe('boom')
    expect(opts.duration).toBe(6000)
  })

  it('string → UNKNOWN 처리 + 문자열 자체를 message 로 사용', () => {
    showIpcErrorToast('something went wrong')
    expect(mockToastError).toHaveBeenCalledTimes(1)
    const [msg] = mockToastError.mock.calls[0]
    expect(msg).toBe('something went wrong')
  })

  it('null → UNKNOWN + 한국어 fallback 메시지', () => {
    showIpcErrorToast(null)
    expect(mockToastError).toHaveBeenCalledTimes(1)
    const [msg] = mockToastError.mock.calls[0]
    expect(msg).toBe('알 수 없는 오류')
  })

  it('undefined → UNKNOWN', () => {
    showIpcErrorToast(undefined)
    expect(mockToastError).toHaveBeenCalledTimes(1)
  })

  it('숫자 → UNKNOWN + 한국어 fallback (Error/string/null 외 분기)', () => {
    showIpcErrorToast(42)
    expect(mockToastError).toHaveBeenCalledTimes(1)
    const [msg] = mockToastError.mock.calls[0]
    expect(msg).toBe('알 수 없는 오류')
  })
})

describe('showIpcErrorToast — toastId 오버라이드', () => {
  it('opts.toastId 가 주어지면 makeToastId 보다 우선', () => {
    const err = new IpcError('VALIDATION', '필드 누락')
    showIpcErrorToast(err, { toastId: 'custom-id-xyz' })
    const [, opts] = mockToast.mock.calls[0]
    expect(opts.id).toBe('custom-id-xyz')
  })
})

describe('showIpcErrorToast — message 비어있을 때 fallback', () => {
  it('AUTH_REQUIRED 에 빈 message + 액션 미주입 → fallback 메시지 사용', () => {
    const err = new IpcError('AUTH_REQUIRED', '   ')
    showIpcErrorToast(err)
    const [msg] = mockToastError.mock.calls[0]
    expect(msg).toBe('로그인이 필요합니다.')
  })

  it('VALIDATION 에 공백 message → fallback 메시지 사용', () => {
    const err = new IpcError('VALIDATION', '')
    showIpcErrorToast(err)
    const [msg] = mockToast.mock.calls[0]
    expect(msg).toBe(CODE_CONFIG.VALIDATION.fallbackMessage)
  })
})

describe('AUTH_EXPIRED 전역 핸들러 (review F1)', () => {
  it('전역 핸들러 등록 + onNavigate 미주입 → toast.custom 분기로 자동 폴백', () => {
    const handler = vi.fn()
    setAuthExpiredHandler(handler)

    const err = new IpcError('AUTH_EXPIRED', '인증 만료')
    showIpcErrorToast(err)

    // toast.custom 으로 분기 (action 콜백이 폴백으로 결정됐으므로)
    expect(mockToastCustom).toHaveBeenCalledTimes(1)
    expect(mockToastError).not.toHaveBeenCalled()
  })

  it('전역 핸들러 미등록 + onNavigate 미주입 → plain toast.error 분기', () => {
    setAuthExpiredHandler(null)

    const err = new IpcError('AUTH_EXPIRED', '인증 만료')
    showIpcErrorToast(err)

    // 콜백 없으니 plain toast.error 로 폴백
    expect(mockToastError).toHaveBeenCalledTimes(1)
    expect(mockToastCustom).not.toHaveBeenCalled()
  })

  it('명시 onNavigate 가 주어지면 전역 핸들러 무시 (호출 사이트 우선)', () => {
    const globalHandler = vi.fn()
    const localHandler = vi.fn()
    setAuthExpiredHandler(globalHandler)

    const err = new IpcError('AUTH_EXPIRED', '인증 만료')
    showIpcErrorToast(err, { onNavigate: localHandler })

    // toast.custom 으로 분기
    expect(mockToastCustom).toHaveBeenCalledTimes(1)
    // 버튼 콜백을 시뮬레이션 — render 함수 첫 인자에서 onClick 추출
    // 이 테스트는 jsdom 미설정이라 render 호출은 생략하고 분기만 검증.
    // 실제 클릭 동작은 통합 테스트 영역. 여기서는 두 handler 가 모두 등록 가능하다는 것만.
    expect(globalHandler).not.toHaveBeenCalled()
    expect(localHandler).not.toHaveBeenCalled()
  })

  it('AUTH_REQUIRED 는 전역 핸들러 폴백 대상 아님 — 빈 toast 처리', () => {
    const handler = vi.fn()
    setAuthExpiredHandler(handler)

    const err = new IpcError('AUTH_REQUIRED', '로그인 필요')
    showIpcErrorToast(err)

    // AUTH_REQUIRED 는 전역 핸들러 폴백 안 됨 → plain toast.error
    expect(mockToastError).toHaveBeenCalledTimes(1)
    expect(mockToastCustom).not.toHaveBeenCalled()
  })
})
