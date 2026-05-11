import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'

interface SliderProps {
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
  /** 표시용 포맷터 (slider 값 우측이 아니라 bounds 라벨에 사용) */
  formatValue?: (v: number) => string
  ariaLabel?: string
}

/**
 * Slider — 커스텀 트랙 + fill + thumb + bounds 라벨.
 *
 * 인터랙션:
 *  - 마우스 drag (mousedown → window mousemove/mouseup)
 *  - 트랙 클릭으로 즉시 이동
 *  - 키보드 ←/→/↑/↓ (step), Home/End (min/max)
 *
 * a11y:
 *  - 컨테이너 div 가 role="slider" + aria-valuemin/max/now + tabIndex=0 을 가져
 *    스크린리더가 단독으로 인식 가능. 별도 native <input type="range"> 미사용
 *    (hit-area 경합 + Tab stop 중복 방지).
 *
 * 한계 (마우스/키보드 전용):
 *  - 터치 입력 미지원. 향후 pointermove 기반으로 확장 예정.
 */
export default function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  formatValue,
  ariaLabel,
}: SliderProps) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)

  const clamp = useCallback(
    (v: number) => Math.min(max, Math.max(min, v)),
    [min, max],
  )

  const snap = useCallback(
    (v: number) => {
      const stepped = Math.round((v - min) / step) * step + min
      // step 이 소수점일 때 부동소수 보정
      const decimals = (step.toString().split('.')[1] ?? '').length
      return Number(clamp(stepped).toFixed(decimals))
    },
    [min, step, clamp],
  )

  const setFromClientX = useCallback(
    (clientX: number) => {
      const track = trackRef.current
      if (!track) return
      const rect = track.getBoundingClientRect()
      const ratio = (clientX - rect.left) / rect.width
      const raw = min + ratio * (max - min)
      onChange(snap(raw))
    },
    [min, max, onChange, snap],
  )

  // 드래그 중 글로벌 listener
  useEffect(() => {
    if (!dragging) return
    const handleMove = (e: MouseEvent) => setFromClientX(e.clientX)
    const handleUp = () => setDragging(false)
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
    return () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }
  }, [dragging, setFromClientX])

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault()
      onChange(snap(value - step))
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault()
      onChange(snap(value + step))
    } else if (e.key === 'Home') {
      e.preventDefault()
      onChange(min)
    } else if (e.key === 'End') {
      e.preventDefault()
      onChange(max)
    }
  }

  const ratio = max === min ? 0 : ((value - min) / (max - min)) * 100
  const fillPercent = Math.min(100, Math.max(0, ratio))

  return (
    <div className="flex flex-col gap-1.5 w-full">
      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-label={ariaLabel}
        onMouseDown={(e) => {
          setDragging(true)
          setFromClientX(e.clientX)
        }}
        onKeyDown={handleKeyDown}
        className="relative h-1.5 rounded-full bg-surface-3 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/40"
      >
        <div
          className="absolute left-0 top-0 bottom-0 bg-accent-500 rounded-full pointer-events-none"
          style={{ width: `${fillPercent}%` }}
        />
        <div
          className="absolute top-1/2 w-3.5 h-3.5 rounded-full bg-white pointer-events-none"
          style={{
            left: `${fillPercent}%`,
            transform: 'translate(-50%, -50%)',
            boxShadow: '0 1px 3px rgba(0,0,0,.4), 0 0 0 3px rgba(16,185,129,.15)',
          }}
        />
      </div>
      <div className="flex justify-between font-mono text-xs text-text-disabled">
        <span>{formatValue ? formatValue(min) : min}</span>
        <span>{formatValue ? formatValue(max) : max}</span>
      </div>
    </div>
  )
}
