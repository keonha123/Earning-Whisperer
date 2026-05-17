import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

export interface DropdownOption<V extends string = string> {
  value: V
  label: string
}

interface DropdownProps<V extends string = string> {
  value: V
  options: DropdownOption<V>[]
  onChange: (value: V) => void
  placeholder?: string
  className?: string
  /** 라벨 prefix (예: "기간:") — 트리거 좌측에 회색 텍스트로 표시 */
  prefix?: string
  /** "전체" 같은 빈 옵션 표시 라벨. value 가 매치 없을 때 사용 */
  fallbackLabel?: string
  ariaLabel?: string
}

/**
 * Dropdown — 가벼운 커스텀 셀렉트.
 *
 * - 트리거: surface-3 배경 + border-strong (디자인 캔버스 `.dd`).
 * - 키보드: Enter/Space 로 열기, ↑/↓ 로 이동, Enter 선택, Esc 닫기.
 * - 외부 클릭 시 닫힘.
 *
 * native <select> 대비 장점: surface-3 배경/스타일을 일관되게 토큰화.
 * 사용처: HistoryPage 필터 (기간/종목/모드/페이지당 행 수).
 */
export default function Dropdown<V extends string = string>({
  value,
  options,
  onChange,
  placeholder,
  className = '',
  prefix,
  fallbackLabel,
  ariaLabel,
}: DropdownProps<V>) {
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const selectedIdx = options.findIndex((o) => o.value === value)
  const selectedLabel =
    selectedIdx >= 0 ? options[selectedIdx].label : fallbackLabel ?? placeholder ?? ''

  useEffect(() => {
    if (!open) return
    setHighlight(Math.max(0, selectedIdx))
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open, selectedIdx])

  const handleKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const handleListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((h) => (h + 1) % options.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((h) => (h - 1 + options.length) % options.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const opt = options[highlight]
      if (opt) {
        onChange(opt.value)
        setOpen(false)
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
    }
  }

  return (
    <div ref={rootRef} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={handleKey}
        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 h-[30px] rounded-md
                   bg-surface-3 border border-border-strong text-text-secondary text-[11px]
                   hover:bg-surface-2 hover:text-text-primary transition-colors duration-100
                   whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/40"
      >
        {prefix && <span className="text-text-tertiary">{prefix}</span>}
        <span className="text-text-primary font-medium">{selectedLabel}</span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="opacity-70"
        >
          <path d="M2 4l3 3 3-3" />
        </svg>
      </button>

      {open && (
        <ul
          role="listbox"
          tabIndex={-1}
          onKeyDown={handleListKey}
          ref={(el) => {
            listRef.current = el
            // 열릴 때 자동 포커스 (키보드 접근성)
            if (el) el.focus()
          }}
          className="absolute top-full left-0 mt-1 min-w-full z-50
                     rounded-md bg-surface-2 border border-border-strong shadow-lg
                     py-1 max-h-64 overflow-y-auto focus:outline-none"
        >
          {options.map((opt, idx) => {
            const isSelected = opt.value === value
            const isHighlighted = idx === highlight
            return (
              <li
                key={opt.value}
                role="option"
                aria-selected={isSelected}
                onMouseEnter={() => setHighlight(idx)}
                onMouseDown={(e) => {
                  // mousedown to fire before onClick blur logic
                  e.preventDefault()
                  onChange(opt.value)
                  setOpen(false)
                }}
                className={`px-3 py-1.5 text-[11px] whitespace-nowrap cursor-pointer
                            ${isHighlighted ? 'bg-surface-3 text-text-primary' : 'text-text-secondary'}
                            ${isSelected ? 'font-semibold text-text-primary' : ''}`}
              >
                {opt.label}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
