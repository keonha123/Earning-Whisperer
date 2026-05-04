/**
 * IPC error 정규화.
 *
 * Electron `ipcMain.handle` 이 throw 시 Renderer 의 promise 가 reject 되면서
 * 사용자 정의 enumerable property 는 손실되고 message 만 통과한다 (prefix 추가됨).
 * 이를 우회하기 위해 main 측에서는 message 안에 `IPC_ERROR::<JSON>::` 접두사로
 * payload 를 인코딩하여 throw 하고, preload 가 이를 추출해 IpcError instance 로
 * 재 throw 한다. Renderer 는 `isIpcError(e)` 로 분기 가능.
 *
 * 영역 분담:
 *  - main:    `throw new IpcError(...)` → preload 에서 자동 인코딩 (serializeIpcError)
 *  - preload: invoke 결과의 reject 를 catch → deserializeIpcError → IpcError 재 throw
 *  - renderer: `catch (e)` 후 `isIpcError(e)` 로 code 별 분기 (PR-2b 에서 toast 로 노출)
 */

export type IpcErrorCode =
  | 'AUTH_REQUIRED'
  | 'AUTH_EXPIRED'
  | 'VALIDATION'
  | 'BUSINESS_RULE'
  | 'BACKEND_5XX'
  | 'NETWORK'
  | 'KIS_ERROR'
  | 'UNKNOWN'

export interface IpcErrorPayload {
  __ipcError: true
  code: IpcErrorCode
  message: string
  details?: unknown
}

const ENCODE_PREFIX = 'IPC_ERROR::'
const ENCODE_SUFFIX = '::IPC_ERROR_END'

export class IpcError extends Error {
  readonly code: IpcErrorCode
  readonly details?: unknown

  constructor(code: IpcErrorCode, message: string, details?: unknown) {
    super(message)
    this.name = 'IpcError'
    this.code = code
    this.details = details
  }

  toPayload(): IpcErrorPayload {
    return {
      __ipcError: true,
      code: this.code,
      message: this.message,
      ...(this.details !== undefined ? { details: this.details } : {}),
    }
  }

  static fromPayload(payload: IpcErrorPayload): IpcError {
    return new IpcError(payload.code, payload.message, payload.details)
  }
}

export function isIpcError(e: unknown): e is IpcError {
  return e instanceof IpcError
}

/**
 * main 측: IpcError → Electron 직렬화 가능한 Error 로 변환.
 * message 에 JSON 인코딩된 payload 를 박아서 preload 가 추출 가능하게 한다.
 *
 * Electron prefix (`Error invoking remote method 'X': Error: ...`) 가
 * message 앞에 붙어도 정규식으로 안전하게 추출되도록 양 끝 sentinel 사용.
 */
export function serializeIpcError(err: IpcError): Error {
  const json = JSON.stringify(err.toPayload())
  return new Error(`${ENCODE_PREFIX}${json}${ENCODE_SUFFIX}`)
}

const ENCODED_PATTERN = new RegExp(
  `${ENCODE_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(.+?)${ENCODE_SUFFIX.replace(
    /[.*+?^${}()|[\]\\]/g,
    '\\$&',
  )}`,
)

/**
 * preload/renderer 측: Electron 이 throw 한 값에서 IpcError 추출.
 * 추출 실패 시 null — 호출 측이 generic Error 또는 UNKNOWN 으로 fallback.
 *
 * 입력 형태 예:
 *  - `Error: IPC_ERROR::{...}::IPC_ERROR_END` (message 만)
 *  - `Error invoking remote method 'X': Error: IPC_ERROR::{...}::IPC_ERROR_END` (Electron prefix)
 *  - 일반 `Error('foo')` — null 반환
 */
export function deserializeIpcError(e: unknown): IpcError | null {
  const message = extractMessage(e)
  if (message === null) return null

  const match = ENCODED_PATTERN.exec(message)
  if (match === null) return null

  try {
    const parsed = JSON.parse(match[1]) as unknown
    if (!isValidPayload(parsed)) return null
    return IpcError.fromPayload(parsed)
  } catch {
    return null
  }
}

function extractMessage(e: unknown): string | null {
  if (typeof e === 'string') return e
  if (e instanceof Error) return e.message
  if (e !== null && typeof e === 'object' && 'message' in e) {
    const m = (e as { message: unknown }).message
    return typeof m === 'string' ? m : null
  }
  return null
}

function isValidPayload(p: unknown): p is IpcErrorPayload {
  if (p === null || typeof p !== 'object') return false
  const o = p as Record<string, unknown>
  return (
    o.__ipcError === true &&
    typeof o.code === 'string' &&
    typeof o.message === 'string' &&
    isValidCode(o.code)
  )
}

const VALID_CODES: ReadonlySet<IpcErrorCode> = new Set<IpcErrorCode>([
  'AUTH_REQUIRED',
  'AUTH_EXPIRED',
  'VALIDATION',
  'BUSINESS_RULE',
  'BACKEND_5XX',
  'NETWORK',
  'KIS_ERROR',
  'UNKNOWN',
])

function isValidCode(c: string): c is IpcErrorCode {
  return VALID_CODES.has(c as IpcErrorCode)
}

/**
 * axios error 에서 안전한 디버깅 정보만 추출.
 *
 * **중요 (보안)**: AxiosError 는 `config.headers` 에 요청 시 사용한 헤더를 그대로 보관 →
 * Bearer token, KIS appkey/appsecret, baseURL 등 자격증명이 포함된다.
 * 또한 `toJSON()` 메서드가 정의돼 있어 raw error 를 JSON.stringify 하면 모든 필드가
 * 평문 직렬화된다. raw axios error 를 IpcError.details 에 박으면 renderer console
 * 또는 외부 로깅 시스템에 자격증명이 누출된다.
 *
 * 따라서 `axiosErrorToIpcError` 와 KIS handler 모두 본 헬퍼로 sanitize 한 후
 * details 에 사용해야 한다.
 */
export function sanitizeAxiosErrorDetails(e: unknown): { status?: number; data?: unknown; code?: string } | undefined {
  if (e === null || typeof e !== 'object') return undefined
  const err = e as {
    isAxiosError?: boolean
    response?: { status?: number; data?: unknown }
    code?: string
  }
  if (err.isAxiosError !== true) return undefined
  return {
    status: err.response?.status,
    data: err.response?.data,
    code: err.code,
  }
}

/**
 * axios error → IpcError 자동 분류. BackendClient 의 response interceptor 에서 사용.
 *
 * 분류 규칙:
 *  - 401 / 419 → AUTH_EXPIRED (토큰 만료/세션 무효)
 *  - 403       → AUTH_REQUIRED (권한 없음 — 사용자에겐 재로그인 유도)
 *  - 404       → VALIDATION (대부분 잘못된 식별자)
 *  - 4xx 그 외 → VALIDATION (기본). 백엔드 응답 메시지 보존.
 *  - 5xx       → BACKEND_5XX
 *  - request 만 있고 response 없음 → NETWORK (timeout, ECONNREFUSED)
 *  - 그 외     → UNKNOWN
 *
 * details 에는 sanitize 된 {status, data, code} 만 — 자격증명 누출 방지 위해
 * config.headers / request / stack 은 의도적으로 제외.
 */
export function axiosErrorToIpcError(e: unknown): IpcError {
  if (e === null || typeof e !== 'object') {
    return new IpcError('UNKNOWN', extractMessage(e) ?? 'unknown error')
  }

  const err = e as {
    isAxiosError?: boolean
    response?: { status?: number; data?: unknown }
    request?: unknown
    code?: string
    message?: string
  }

  if (err.isAxiosError !== true) {
    return new IpcError('UNKNOWN', err.message ?? 'unknown error')
  }

  const backendMessage = extractBackendMessage(err.response?.data)
  const details = sanitizeAxiosErrorDetails(err)

  if (err.response !== undefined) {
    const status = err.response.status ?? 0

    if (status === 401 || status === 419) {
      return new IpcError(
        'AUTH_EXPIRED',
        backendMessage ?? '인증이 만료되었습니다. 다시 로그인해 주세요.',
        details,
      )
    }
    if (status === 403) {
      return new IpcError('AUTH_REQUIRED', backendMessage ?? '접근 권한이 없습니다.', details)
    }
    if (status >= 500) {
      return new IpcError(
        'BACKEND_5XX',
        backendMessage ?? '서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요.',
        details,
      )
    }
    if (status >= 400) {
      return new IpcError('VALIDATION', backendMessage ?? '요청이 잘못되었습니다.', details)
    }
    return new IpcError('UNKNOWN', backendMessage ?? `HTTP ${status}`, details)
  }

  if (err.request !== undefined) {
    return new IpcError(
      'NETWORK',
      '네트워크 오류가 발생했습니다. 연결을 확인해 주세요.',
      { code: err.code },
    )
  }

  return new IpcError('UNKNOWN', err.message ?? 'unknown error')
}

function extractBackendMessage(data: unknown): string | null {
  if (data === null || typeof data !== 'object') return null
  const d = data as Record<string, unknown>
  if (typeof d.message === 'string') return d.message
  if (typeof d.error === 'string') return d.error
  return null
}
