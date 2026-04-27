import type { ReactNode } from 'react'

export interface TabItem {
  id: string
  label: string
  /** 우측에 작게 표시되는 보조 카운트 (옵션) */
  count?: number | string
  icon?: ReactNode
}

interface TabsProps {
  items: TabItem[]
  activeId: string
  onChange: (id: string) => void
  className?: string
  /**
   * underline: 활성 탭 하단 emerald 보더 (Holdings 등)
   * pill: 활성 탭 배경 (보조 용도)
   */
  variant?: 'underline' | 'pill'
}

/**
 * Tabs — 일반 탭 컨트롤.
 *
 * - 키보드: 좌우 화살표로 탭 이동, Tab 으로 다음 포커스 영역 이동.
 * - 토큰만 사용: surface-1/2/3, accent-500, border-subtle, text-tier.
 *
 * 디자인 매칭: DashboardPage.html `.tab` / `.tab.active` (underline 변형).
 */
export default function Tabs({
  items,
  activeId,
  onChange,
  className = '',
  variant = 'underline',
}: TabsProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>, idx: number) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      const next = items[(idx + 1) % items.length]
      onChange(next.id)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      const prev = items[(idx - 1 + items.length) % items.length]
      onChange(prev.id)
    }
  }

  return (
    <div
      role="tablist"
      className={`inline-flex items-stretch ${className}`}
    >
      {items.map((it, idx) => {
        const isActive = it.id === activeId
        const baseCls =
          'inline-flex items-center gap-1.5 px-2.5 h-[38px] text-[11px] font-semibold uppercase tracking-[0.14em] transition-colors duration-100 cursor-pointer'

        if (variant === 'pill') {
          const pillCls = isActive
            ? 'bg-surface-2 text-text-primary rounded-md'
            : 'text-text-tertiary hover:text-text-primary'
          return (
            <button
              key={it.id}
              role="tab"
              aria-selected={isActive}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onChange(it.id)}
              onKeyDown={(e) => handleKeyDown(e, idx)}
              className={`${baseCls} ${pillCls}`}
            >
              {it.icon && <span className="opacity-80">{it.icon}</span>}
              <span>{it.label}</span>
              {it.count != null && (
                <span className="num text-[10px] tracking-normal text-text-disabled">
                  {it.count}
                </span>
              )}
            </button>
          )
        }

        // underline (default)
        const underlineCls = isActive
          ? 'text-text-primary border-b-2 border-accent-500 -mb-px'
          : 'text-text-tertiary hover:text-text-primary border-b-2 border-transparent -mb-px'
        return (
          <button
            key={it.id}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(it.id)}
            onKeyDown={(e) => handleKeyDown(e, idx)}
            className={`${baseCls} ${underlineCls}`}
          >
            {it.icon && <span className="opacity-80">{it.icon}</span>}
            <span>{it.label}</span>
            {it.count != null && (
              <span className="num text-[10px] tracking-normal text-text-disabled">
                {it.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
