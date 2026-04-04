interface RawScoreGaugeProps {
  score: number | null
}

const ARC_LENGTH = Math.PI * 80

function getArcColor(score: number): string {
  if (score <= 0.4) return '#ef4444'
  if (score <= 0.6) return '#f59e0b'
  return '#22c55e'
}

function describeArc(cx: number, cy: number, r: number): string {
  const startX = cx - r
  const startY = cy
  const endX = cx + r
  const endY = cy
  return `M ${startX} ${startY} A ${r} ${r} 0 0 1 ${endX} ${endY}`
}

function getNeedleCoords(cx: number, cy: number, length: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180
  return {
    x2: cx + length * Math.cos(rad),
    y2: cy + length * Math.sin(rad),
  }
}

export default function RawScoreGauge({ score }: RawScoreGaugeProps) {
  const safeScore = score ?? 0
  const arcColor = score !== null ? getArcColor(safeScore) : '#1e2738'
  const dashOffset = ARC_LENGTH * (1 - safeScore)
  const needleAngleDeg = -180 + safeScore * 180
  const { x2, y2 } = getNeedleCoords(100, 100, 65, needleAngleDeg)

  return (
    <div className="flex flex-col items-center justify-center w-full h-full">
      <svg viewBox="0 0 200 110" className="w-full max-w-[200px]">
        {/* 배경 arc */}
        <path
          d={describeArc(100, 100, 80)}
          fill="none"
          stroke="#1e2738"
          strokeWidth={12}
          strokeLinecap="round"
        />
        {/* 점수 arc */}
        <path
          d={describeArc(100, 100, 80)}
          fill="none"
          stroke={arcColor}
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={`${ARC_LENGTH}`}
          strokeDashoffset={`${dashOffset}`}
        />
        {/* 바늘 */}
        <line
          x1={100}
          y1={100}
          x2={x2}
          y2={y2}
          stroke="#e2e8f0"
          strokeWidth={2}
          strokeLinecap="round"
        />
        {/* 중심 원 */}
        <circle cx={100} cy={100} r={4} fill="#e2e8f0" />
        {/* 점수 텍스트 */}
        <text
          x={100}
          y={96}
          textAnchor="middle"
          className="num"
          fontSize={22}
          fontWeight="bold"
          fill="#e2e8f0"
          fontFamily="monospace"
        >
          {score !== null ? (score * 100).toFixed(0) : '--'}
        </text>
        {/* 레이블 */}
        <text
          x={100}
          y={108}
          textAnchor="middle"
          fontSize={9}
          fill="#475569"
          fontFamily="sans-serif"
        >
          Raw EMA Score
        </text>
      </svg>
    </div>
  )
}
