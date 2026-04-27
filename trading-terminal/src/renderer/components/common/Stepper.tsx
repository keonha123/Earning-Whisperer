import { useEffect, useState, type ChangeEvent } from 'react'

interface StepperProps {
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
  /** 값 표시 시 우측에 붙이는 단위 (예: "분") — 시각용, aria-valuetext 에는 사용 안함 */
  suffix?: string
  ariaLabel?: string
}

/**
 * Stepper — − / 값 / + 버튼 레이아웃.
 *
 * 가운데 값 표시는 <input type="number"> 로 직접 편집 가능.
 * input 자체가 role="spinbutton" 을 갖기 때문에 컨테이너 div 는 role/tabIndex
 * 를 갖지 않는다 (한 stepper 에 Tab stop 3개가 생기는 중복 방지).
 *
 * 키보드:
 *   - input 포커스 상태에서 ↑/↓ 화살표는 브라우저 기본 step 동작
 *   - − / + 버튼은 클릭 또는 Enter/Space 로 동작
 */
export default function Stepper({
  value,
  min,
  max,
  step = 1,
  onChange,
  suffix,
  ariaLabel,
}: StepperProps) {
  const clamp = (v: number) => Math.min(max, Math.max(min, v))

  // input 의 임시 표시값 (사용자 편집 중에는 숫자가 아닐 수 있음)
  const [inputText, setInputText] = useState<string>(value.toString())

  // 외부 value prop 이 변경되면 input 표시도 동기화
  useEffect(() => {
    setInputText(value.toString())
  }, [value])

  const decrement = () => onChange(clamp(value - step))
  const increment = () => onChange(clamp(value + step))

  const handleInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    setInputText(raw)
    // 빈값/임시 입력 중에는 onChange 미발화
    if (raw === '' || raw === '-') return
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) {
      onChange(clamp(parsed))
    }
  }

  const handleInputBlur = () => {
    // blur 시 항상 유효한 값으로 정규화
    const parsed = Number(inputText)
    if (!Number.isFinite(parsed)) {
      setInputText(value.toString())
    } else {
      const next = clamp(parsed)
      onChange(next)
      setInputText(next.toString())
    }
  }

  return (
    <div className="flex items-center bg-surface-3 border border-border-strong rounded-md overflow-hidden h-8 focus-within:ring-2 focus-within:ring-accent-500/40">
      <button
        type="button"
        onClick={decrement}
        disabled={value <= min}
        aria-label="감소"
        className="w-8 h-full grid place-items-center text-text-tertiary hover:bg-surface-2 hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed text-base"
      >
        −
      </button>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={inputText}
        onChange={handleInputChange}
        onBlur={handleInputBlur}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            ;(e.target as HTMLInputElement).blur()
          }
        }}
        aria-label={ariaLabel}
        className="flex-1 min-w-0 h-full bg-transparent text-center font-mono text-sm text-text-primary tabular-nums font-medium outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
      {suffix && (
        <span className="font-mono text-sm text-text-tertiary tabular-nums pr-1.5 select-none">
          {suffix}
        </span>
      )}
      <button
        type="button"
        onClick={increment}
        disabled={value >= max}
        aria-label="증가"
        className="w-8 h-full grid place-items-center text-text-tertiary hover:bg-surface-2 hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed text-base"
      >
        +
      </button>
    </div>
  )
}
