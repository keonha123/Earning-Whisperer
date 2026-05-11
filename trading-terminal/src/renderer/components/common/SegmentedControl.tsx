export interface SegmentItem<V extends string = string> {
  id: V
  label: string
  count?: number | string
}

interface SegmentedControlProps<V extends string = string> {
  items: SegmentItem<V>[]
  activeId: V
  onChange: (id: V) => void
  className?: string
}

/**
 * SegmentedControl — 가로 세그먼트 버튼 그룹.
 *
 * 디자인 매칭: HistoryPage.html `.segs` / `.seg.active`.
 *  - 컨테이너: surface-2 배경 + border-subtle, padding 2px.
 *  - 활성: rgba(255,255,255,.08) 배경 + inset 1px 보더 + text-primary.
 *
 * 키보드: Tab 으로 그룹 진입, ←/→ 로 항목 이동.
 */
export default function SegmentedControl<V extends string = string>({
  items,
  activeId,
  onChange,
  className = '',
}: SegmentedControlProps<V>) {
  const handleKey = (e: React.KeyboardEvent<HTMLButtonElement>, idx: number) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      onChange(items[(idx + 1) % items.length].id)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      onChange(items[(idx - 1 + items.length) % items.length].id)
    }
  }

  return (
    <div
      role="tablist"
      className={`inline-flex gap-0.5 p-0.5 rounded-md bg-surface-2 border border-border-subtle ${className}`}
    >
      {items.map((it, idx) => {
        const isActive = it.id === activeId
        return (
          <button
            key={it.id}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(it.id)}
            onKeyDown={(e) => handleKey(e, idx)}
            className={
              'px-3 py-1 rounded text-[11px] font-semibold tracking-[0.04em] transition-colors duration-100 ' +
              (isActive
                ? 'bg-white/[0.08] text-text-primary shadow-[inset_0_0_0_1px_rgba(255,255,255,0.22)]'
                : 'text-text-tertiary hover:text-text-primary')
            }
          >
            {it.label}
            {it.count != null && (
              <span className="ml-1 num text-[10px] text-text-disabled">{it.count}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}
