import { useLayoutEffect, useRef, useState } from 'react'

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
 * 맑은 유리 트랙(금테 1px) 안에서 맑은 유리 썸(금테 1.4px)이 고른 칸으로 스프링처럼 미끄러진다
 * (docs/design/design-system.md 세그먼트). 색상 유리는 버튼에만 쓰므로 썸에는 쓰지 않는다.
 *
 * 키보드: Tab 으로 그룹 진입, ←/→ 로 항목 이동.
 */
export default function SegmentedControl<V extends string = string>({
  items,
  activeId,
  onChange,
  className = '',
}: SegmentedControlProps<V>) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [thumb, setThumb] = useState<{ left: number; width: number } | null>(null)

  // 고른 칸의 위치 · 폭을 재서 썸을 옮긴다. 라벨 · 개수가 바뀌어 폭이 달라져도 다시 잰다.
  useLayoutEffect(() => {
    const track = trackRef.current
    if (!track) return
    const measure = () => {
      const el = track.querySelector<HTMLElement>('[aria-selected="true"]')
      const next = el ? { left: el.offsetLeft, width: el.offsetWidth } : null
      // 같은 값이면 상태를 바꾸지 않는다 — 호출부가 items 를 매번 새 배열로 넘겨도 렌더가 늘지 않게
      setThumb((prev) =>
        prev && next && prev.left === next.left && prev.width === next.width ? prev : next,
      )
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(track)
    return () => observer.disconnect()
  }, [activeId, items])

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
      ref={trackRef}
      role="tablist"
      className={`glass rim relative inline-flex p-1 rounded-full ${className}`}
    >
      {thumb && (
        <span
          aria-hidden="true"
          className="glass rim rim-float absolute top-1 bottom-1 left-0 rounded-full transition-[transform,width] duration-[400ms] ease-spring"
          style={{ width: thumb.width, transform: `translateX(${thumb.left}px)` }}
        />
      )}
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
              'relative z-[1] px-3.5 py-1.5 rounded-full text-[12px] whitespace-nowrap transition-colors duration-150 ' +
              (isActive
                ? 'font-semibold text-text-primary on-glass'
                : 'font-medium text-text-tertiary hover:text-text-primary')
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
