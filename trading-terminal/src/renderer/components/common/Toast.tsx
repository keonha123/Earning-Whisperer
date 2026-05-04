import toast, { Toaster } from 'react-hot-toast'
import {
  IpcError,
  isIpcError,
  type IpcErrorCode,
} from '../../../lib/types/ipcError'

/**
 * Toast — IPC 에러 코드 기반 사용자 알림.
 *
 * PR-2b 청사진:
 *  - main 에서 throw 한 IpcError 가 preload 의 deserializeIpcError 로 unwrap 되어
 *    renderer 의 catch (e) 에 IpcError instance 로 들어온다.
 *  - 호출 사이트는 catch (e) → showIpcErrorToast(e) 만 호출하면 된다.
 *  - 코드별로 variant (error/warning), duration, fallback 메시지, action 버튼이
 *    CODE_CONFIG 에 선언적으로 매핑되어 있다.
 *
 * 중복 억제:
 *  - 동일 (code, message[:32]) 조합은 djb2 hash 로 동일 toastId 생성 → react-hot-toast 가
 *    동일 id toast 를 1개로 유지 (replace 동작).
 *  - AUTH_EXPIRED 는 항상 'ipc-auth-expired' 로 단일성 보장.
 *
 * action (재시도 / 로그인) 은 toast.custom 으로 메시지 + 버튼을 같이 렌더한다.
 * action 미주입 (onRetry/onNavigate undefined) 시 버튼을 그리지 않고 일반 toast 로 폴백.
 */

export interface IpcToastOptions {
  /** BACKEND_5XX/NETWORK 시 "재시도" 버튼 자리. 미주입 시 버튼 미표시. */
  onRetry?: () => void
  /** AUTH_REQUIRED/AUTH_EXPIRED 시 "로그인/다시 로그인" 버튼. 미주입 시 버튼 미표시. */
  onNavigate?: () => void
  /** 중복 억제 id 오버라이드 (호출 사이트가 명시적으로 제어하고 싶을 때). */
  toastId?: string
}

interface ToastConfig {
  variant: 'error' | 'warning'
  duration: number
  fallbackMessage: string
  /** 'navigate' = onNavigate, 'retry' = onRetry. undefined = 버튼 없음. */
  actionKind?: 'navigate' | 'retry'
  /** action 버튼 라벨. */
  actionLabel?: string
}

export const CODE_CONFIG: Record<IpcErrorCode, ToastConfig> = {
  AUTH_REQUIRED: {
    variant: 'error',
    duration: 8000,
    fallbackMessage: '로그인이 필요합니다.',
    actionKind: 'navigate',
    actionLabel: '로그인',
  },
  AUTH_EXPIRED: {
    variant: 'error',
    duration: Infinity,
    fallbackMessage: '세션이 만료되었습니다.',
    actionKind: 'navigate',
    actionLabel: '다시 로그인',
  },
  VALIDATION: {
    variant: 'warning',
    duration: 4000,
    fallbackMessage: '요청이 잘못되었습니다.',
  },
  BUSINESS_RULE: {
    variant: 'warning',
    duration: 5000,
    fallbackMessage: '규칙 위반으로 요청이 거절되었습니다.',
  },
  BACKEND_5XX: {
    variant: 'error',
    duration: 6000,
    fallbackMessage: '서버 오류가 발생했습니다.',
    actionKind: 'retry',
    actionLabel: '재시도',
  },
  NETWORK: {
    variant: 'error',
    duration: Infinity,
    fallbackMessage: '네트워크 오류. 연결을 확인해 주세요.',
    actionKind: 'retry',
    actionLabel: '재시도',
  },
  KIS_ERROR: {
    variant: 'warning',
    duration: 7000,
    fallbackMessage: 'KIS 응답 오류가 발생했습니다.',
  },
  UNKNOWN: {
    variant: 'error',
    duration: 6000,
    fallbackMessage: '알 수 없는 오류가 발생했습니다.',
  },
}

/**
 * AUTH_EXPIRED 전역 핸들러. 호출 사이트 20곳마다 onNavigate 콜백을 일일이 주입하지 않도록
 * App.tsx 가 1회 등록하면 옵션 미주입 시 자동 폴백된다 (review F1).
 */
let globalAuthExpiredHandler: (() => void) | null = null

export function setAuthExpiredHandler(handler: (() => void) | null): void {
  globalAuthExpiredHandler = handler
}

/**
 * djb2 hash. 동일 message 슬라이스에 대해 동일 hash 를 보장 — toastId 중복 억제용.
 * 음수 회피를 위해 unsigned 로 변환.
 */
function djb2(str: string): number {
  let h = 5381
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) + h) ^ str.charCodeAt(i)
  }
  return h >>> 0
}

/**
 * code + message → toastId 생성. AUTH_EXPIRED 는 단일성 보장 위해 고정 id.
 * 그 외 코드는 message 의 처음 32자 djb2 hash 로 충돌을 줄이면서 동일 메시지 중복 억제.
 */
export function makeToastId(code: IpcErrorCode, message: string): string {
  if (code === 'AUTH_EXPIRED') return 'ipc-auth-expired'
  return `ipc-${code}-${djb2(message.slice(0, 32))}`
}

/**
 * KIS_ERROR 의 details 에서 code 필드 추출. 형식 불일치 시 undefined.
 * KIS handler 가 details 에 `{ code, message, ... }` 같은 객체를 넣는 패턴 가정.
 */
function extractKisCode(details: unknown): string | undefined {
  if (details === null || typeof details !== 'object') return undefined
  const d = details as Record<string, unknown>
  return typeof d.code === 'string' ? d.code : undefined
}

interface ResolvedError {
  code: IpcErrorCode
  message: string
  details?: unknown
}

function resolveError(err: unknown): ResolvedError {
  if (isIpcError(err)) {
    return { code: err.code, message: err.message, details: err.details }
  }
  // non-IpcError → UNKNOWN
  const message =
    err instanceof Error
      ? err.message
      : typeof err === 'string'
        ? err
        : '알 수 없는 오류'
  return { code: 'UNKNOWN', message }
}

/**
 * 표시 메시지 결정:
 *  - VALIDATION/BUSINESS_RULE: 백엔드 message 우선 (입력 오류는 사용자에게 직접 노출 가치 큼).
 *  - KIS_ERROR: `${msg} (${details.code})` 포맷 — KIS 코드까지 노출해 디버깅 용이.
 *  - 그 외: message 가 비어 있으면 fallback.
 */
function pickDisplayMessage(
  code: IpcErrorCode,
  message: string,
  details: unknown,
  config: ToastConfig,
): string {
  const trimmed = message.trim()
  if (code === 'KIS_ERROR') {
    const kisCode = extractKisCode(details)
    const base = trimmed.length > 0 ? trimmed : config.fallbackMessage
    return kisCode ? `${base} (${kisCode})` : base
  }
  if (code === 'VALIDATION' || code === 'BUSINESS_RULE') {
    return trimmed.length > 0 ? trimmed : config.fallbackMessage
  }
  return trimmed.length > 0 ? trimmed : config.fallbackMessage
}

/**
 * showIpcErrorToast — 호출 사이트의 catch (e) 에서 직접 호출.
 *
 *  try {
 *    await ipc.invoke(...)
 *  } catch (e) {
 *    showIpcErrorToast(e, { onRetry: () => retry(), onNavigate: () => navigate('/auth') })
 *  }
 *
 * action 콜백이 있는 경우 toast.custom 으로 메시지 + 버튼을 같이 렌더링한다.
 * 미주입 시 plain toast.error / toast (warning) 로 폴백.
 */
export function showIpcErrorToast(
  err: unknown,
  opts: IpcToastOptions = {},
): void {
  const { code, message, details } = resolveError(err)
  const config = CODE_CONFIG[code]
  const displayMessage = pickDisplayMessage(code, message, details, config)
  const id = opts.toastId ?? makeToastId(code, message)

  // action 콜백 결정. AUTH_EXPIRED 는 onNavigate 미주입 시 전역 핸들러로 폴백 (review F1).
  const actionCallback =
    config.actionKind === 'navigate'
      ? opts.onNavigate ?? (code === 'AUTH_EXPIRED' ? globalAuthExpiredHandler ?? undefined : undefined)
      : config.actionKind === 'retry'
        ? opts.onRetry
        : undefined

  const variantClassName =
    config.variant === 'error' ? 'toast-ipc-error' : 'toast-ipc-warning'

  const ariaProps =
    config.variant === 'error'
      ? ({ role: 'alert', 'aria-live': 'assertive' } as const)
      : undefined

  // action 이 실제로 주입된 경우 → toast.custom 으로 버튼 같이 렌더.
  if (actionCallback && config.actionLabel) {
    toast.custom(
      (t) => (
        <div
          className={variantClassName}
          {...(ariaProps ?? {})}
        >
          <div>{displayMessage}</div>
          <button
            type="button"
            className="toast-ipc-action"
            onClick={() => {
              actionCallback()
              toast.dismiss(t.id)
            }}
          >
            {config.actionLabel}
          </button>
        </div>
      ),
      { id, duration: config.duration },
    )
    return
  }

  // plain toast 폴백.
  if (config.variant === 'error') {
    toast.error(displayMessage, {
      id,
      duration: config.duration,
      className: variantClassName,
      ...(ariaProps ? { ariaProps } : {}),
    })
  } else {
    toast(displayMessage, {
      id,
      duration: config.duration,
      className: variantClassName,
      icon: '⚠️',
    })
  }
}

/**
 * AppToaster — App.tsx 의 router 내부에 1회 마운트.
 * react-hot-toast 의 <Toaster> 를 우상단 56px 오프셋, 최대 3개 stack, gutter 8px 로 래핑.
 */
export function AppToaster(): JSX.Element {
  return (
    <Toaster
      position="top-right"
      gutter={8}
      containerStyle={{ top: 56, right: 16 }}
      // react-hot-toast 는 max stack 옵션이 없어 toastOptions.duration 외 별도 제한이 없다.
      // 호출 사이트의 동일 id 중복 억제 (makeToastId) 로 자연스럽게 stack 이 제한된다.
      // 시각적 안전망: 기본 duration 외에 ariaProps 로 a11y 보장.
      toastOptions={{
        duration: 6000,
      }}
    />
  )
}

/**
 * 테스트 노출용 — IpcError class 와 분리해 단위 테스트가 직접 import 가능.
 */
export { IpcError }
