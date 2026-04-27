interface MiniGaugeProps {
  /** 0~1 범위의 값. 외부에서 클램프 안 해도 내부에서 처리. */
  value: number
  /** value 의 최대치 (기본 1). 0~1 범위가 아닌 경우 사용. */
  max?: number
  /** 픽셀 단위 외경 지름 (기본 22). */
  size?: number
  /** stroke 색 — 호출자가 임계치별로 결정 */
  color?: 'accent' | 'warning' | 'neutral' | 'sell'
  /** 게이지 옆에 0.84 같은 값 텍스트 표시 여부 */
  showValue?: boolean
  /** 표시값 포맷터 (기본: 소수점 2자리) */
  formatValue?: (v: number) => string
  className?: string
  ariaLabel?: string
}

const COLOR_MAP: Record<NonNullable<MiniGaugeProps['color']>, { stroke: string; text: string }> = {
  accent: { stroke: '#10b981', text: 'text-buy' },
  warning: { stroke: '#f59e0b', text: 'text-warning' },
  neutral: { stroke: '#64748b', text: 'text-neutral' },
  sell: { stroke: '#ef4444', text: 'text-sell' },
}

/**
 * MiniGauge — 원형 진행률 인디케이터 (SVG, 의존성 0).
 *
 * 디자인 매칭: HistoryPage.html `.ema-g` (22px) + EMA value 텍스트.
 *
 * 사용처:
 *  - HistoryPage AI 컬럼
 *  - CompanyDrawer AI 점수 뱃지 (옵션)
 *  - 추후 TradingRoom 에서 재사용 예상
 *
 * 색은 호출자가 결정 (예: value > 0.7 → accent, 0.5~0.7 → warning, < 0.5 → neutral).
 */
export default function MiniGauge({
  value,
  max = 1,
  size = 22,
  color = 'accent',
  showValue = true,
  formatValue,
  className = '',
  ariaLabel,
}: MiniGaugeProps) {
  const safeMax = max > 0 ? max : 1
  const ratio = Math.max(0, Math.min(1, value / safeMax))

  // 디자인 캔버스: r=9, stroke=3 → 둘레 ≈ 56.5
  // size=22 기준이며 size 변경 시 스케일링.
  const r = 9
  const circumference = 2 * Math.PI * r
  const dash = circumference * ratio
  const gap = circumference - dash

  const colors = COLOR_MAP[color]
  const display = showValue
    ? formatValue
      ? formatValue(value)
      : value.toFixed(2)
    : null

  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      role="img"
      aria-label={ariaLabel ?? `gauge ${(ratio * 100).toFixed(0)}%`}
    >
      <span
        className="relative inline-block"
        style={{ width: size, height: size }}
      >
        <svg viewBox="0 0 24 24" width={size} height={size}>
          <circle cx="12" cy="12" r={r} fill="none" stroke="#242e3f" strokeWidth="3" />
          <circle
            cx="12"
            cy="12"
            r={r}
            fill="none"
            stroke={colors.stroke}
            strokeWidth="3"
            strokeDasharray={`${dash} ${gap}`}
            strokeDashoffset={-circumference * 0.25}
            transform="rotate(-90 12 12)"
            strokeLinecap="round"
          />
        </svg>
      </span>
      {display && (
        <span className={`num text-[11px] font-semibold tabular-nums ${colors.text}`}>
          {display}
        </span>
      )}
    </span>
  )
}
