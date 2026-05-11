import { useMemo } from 'react'
import type { ChartPoint } from '../../fixtures/companyDetail.dev-mock'

interface MiniLineChartProps {
  points: ChartPoint[]
  /** SVG viewBox 너비 (기본 320). 부모 컨테이너 너비에 맞춰 stretch. */
  viewWidth?: number
  /** SVG viewBox 높이 (기본 86). 부모 컨테이너 높이에 맞춰 stretch. */
  viewHeight?: number
  /** 라인/영역 색 (기본 accent). 'sell' → 빨강. */
  color?: 'accent' | 'sell' | 'neutral'
  /** 마지막 점에 highlight (원 + glow). 기본 true. */
  highlightLast?: boolean
  className?: string
}

const COLOR_MAP = {
  accent: { line: '#10b981', area: 'rgba(16,185,129,0.1)', dot: '#10b981' },
  sell: { line: '#ef4444', area: 'rgba(239,68,68,0.08)', dot: '#ef4444' },
  neutral: { line: '#94a3b8', area: 'rgba(148,163,184,0.08)', dot: '#94a3b8' },
}

/**
 * MiniLineChart — SVG 기반 라인 + 영역 차트 (의존성 0).
 *
 * 디자인 매칭:
 *  - DashboardPage.html 자산 추이 차트 (`.chart-svg`).
 *  - CompanyDrawer.html 30일 일봉 차트 (`.csvg`).
 *
 * 구현:
 *  - viewBox + preserveAspectRatio="none" 으로 부모 컨테이너에 stretch.
 *  - 가격 시계열 → x = idx * (viewWidth / (n-1)), y = (max - p) / range * viewHeight.
 *  - 영역은 라인 path 끝에 `L X,height L 0,height Z` 추가.
 *  - 마지막 점 강조: 작은 원 + 큰 반투명 원 (glow).
 *
 * 설계 결정 (PR3 옵션 4):
 *  - lightweight-charts 도입은 PR #4 로 이연. SVG 직접 그리기로 의존성 0 유지.
 */
export default function MiniLineChart({
  points,
  viewWidth = 320,
  viewHeight = 86,
  color = 'accent',
  highlightLast = true,
  className = '',
}: MiniLineChartProps) {
  const colors = COLOR_MAP[color]

  const { linePath, areaPath, lastX, lastY, hasData } = useMemo(() => {
    // NaN/Infinity 방어: 결측치 (백엔드 IPC 데이터) 가 섞이면 Math.min/max → NaN
    // 전파 → SVG path d="MNaN,NaN..." 이 되어 차트 전체가 깨진다.
    // 유한값만 추려서 사용. 모두 무효면 빈 placeholder 로 fallback.
    const validPoints = points.filter((p) => Number.isFinite(p.price))
    if (validPoints.length === 0) {
      return { linePath: '', areaPath: '', lastX: 0, lastY: 0, hasData: false }
    }
    const prices = validPoints.map((p) => p.price)
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const range = max - min || 1
    // y 가 위쪽일수록 0 — SVG 좌표계 매칭. 상단 4px 패딩, 하단 0.
    const padTop = 6
    const padBottom = 0
    const drawH = viewHeight - padTop - padBottom

    const stepX = validPoints.length > 1 ? viewWidth / (validPoints.length - 1) : 0

    const coords = validPoints.map((pt, i) => {
      const x = i * stepX
      const y = padTop + ((max - pt.price) / range) * drawH
      return { x, y }
    })

    const linePathStr = coords
      .map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(2)},${c.y.toFixed(2)}`)
      .join(' ')
    const last = coords[coords.length - 1]
    const areaPathStr =
      linePathStr +
      ` L${last.x.toFixed(2)},${viewHeight} L0,${viewHeight} Z`

    return {
      linePath: linePathStr,
      areaPath: areaPathStr,
      lastX: last.x,
      lastY: last.y,
      hasData: true,
    }
  }, [points, viewWidth, viewHeight])

  if (!hasData) {
    return (
      <div
        className={`flex items-center justify-center text-[10px] text-text-disabled ${className}`}
      >
        차트 데이터 없음
      </div>
    )
  }

  return (
    <svg
      viewBox={`0 0 ${viewWidth} ${viewHeight}`}
      preserveAspectRatio="none"
      className={`w-full h-full ${className}`}
      role="img"
      aria-label="가격 추이 차트"
    >
      {/* 가로 grid 4줄 */}
      {[0.1, 0.4, 0.7, 1].map((r, i) => {
        const y = viewHeight * r - (i === 3 ? 1 : 0)
        return (
          <line
            key={r}
            x1={0}
            y1={y}
            x2={viewWidth}
            y2={y}
            stroke="#1e2738"
            strokeWidth={1}
          />
        )
      })}

      <path d={areaPath} fill={colors.area} />
      <path
        d={linePath}
        fill="none"
        stroke={colors.line}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />

      {highlightLast && (
        <>
          <circle cx={lastX} cy={lastY} r={7} fill={`${colors.area}`} />
          <circle
            cx={lastX}
            cy={lastY}
            r={3}
            fill={colors.dot}
            stroke="#0b1017"
            strokeWidth={1.5}
          />
        </>
      )}
    </svg>
  )
}
