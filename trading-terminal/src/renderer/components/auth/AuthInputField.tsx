import { useId, useState, type InputHTMLAttributes, type ReactNode } from 'react'
import PasswordToggle from './PasswordToggle'

interface AuthInputFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  /** 라벨 우측에 표시되는 보조 슬롯 (예: "비밀번호 찾기" 링크) */
  labelTrailing?: ReactNode
  /** 입력칸 좌측 아이콘 슬롯 */
  leadingIcon?: ReactNode
  /**
   * 비밀번호 모드. true 일 때 PasswordToggle 자동 결합 + type 강제 password.
   * isPassword 가 true 면 prop 으로 받은 type 은 무시된다.
   */
  isPassword?: boolean
}

/**
 * AuthInputField — 라벨 + (좌측 아이콘) + input + (비밀번호 toggle) 래퍼.
 *
 * 디자인 토큰 기반 input-wrap 스타일을 직접 구현 (input-base 스타일 미사용).
 * focus 상태는 wrapper 가 직접 추적하여 border + box-shadow 적용.
 *
 * a11y / 보안:
 *   - useId() 로 고유 id 생성 + <label htmlFor> 결합 → 스크린리더 라벨 연결
 *   - spellCheck/autoCapitalize/autoCorrect 모두 끔 → IME/사전 학습으로 비밀번호·
 *     AppSecret 평문이 외부 사전에 학습되는 것을 방지
 *   - autoComplete: 비밀번호 모드 default 'current-password', 일반 모드 default 'off'
 *     (호출자가 명시적으로 'username' 등 override 가능)
 */
export default function AuthInputField({
  label,
  labelTrailing,
  leadingIcon,
  isPassword = false,
  type,
  className,
  id: idProp,
  autoComplete,
  ...inputProps
}: AuthInputFieldProps) {
  const reactId = useId()
  const inputId = idProp ?? `auth-input-${reactId}`

  const [focused, setFocused] = useState(false)
  const [visible, setVisible] = useState(false)

  const inputType = isPassword ? (visible ? 'text' : 'password') : (type ?? 'text')

  // autoComplete default — caller override 우선
  const resolvedAutoComplete =
    autoComplete ?? (isPassword ? 'current-password' : 'off')

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <label
          htmlFor={inputId}
          className="text-text-secondary text-xs font-medium tracking-wide"
        >
          {label}
        </label>
        {labelTrailing}
      </div>
      <div
        className={`flex items-center gap-2 h-9 px-2.5 rounded-md bg-surface-3 border transition-colors ${
          focused
            ? 'border-accent-500'
            : 'border-border-strong'
        }`}
        style={
          focused
            ? { boxShadow: '0 0 0 3px rgba(16,185,129,0.14)' }
            : undefined
        }
      >
        {leadingIcon && (
          <span className="text-text-tertiary flex-none flex items-center" aria-hidden>
            {leadingIcon}
          </span>
        )}
        <input
          {...inputProps}
          id={inputId}
          type={inputType}
          autoComplete={resolvedAutoComplete}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          onFocus={(e) => {
            setFocused(true)
            inputProps.onFocus?.(e)
          }}
          onBlur={(e) => {
            setFocused(false)
            inputProps.onBlur?.(e)
          }}
          className={`flex-1 bg-transparent text-text-primary text-sm outline-none placeholder:text-text-disabled tracking-wide ${
            className ?? ''
          }`}
        />
        {isPassword && (
          <PasswordToggle visible={visible} onToggle={() => setVisible((v) => !v)} />
        )}
      </div>
    </div>
  )
}
