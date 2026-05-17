interface CompanyLogoProps {
  ticker: string
  size?: number
  /** 배경 색 (CSS color). 미지정 시 surface-3 fallback. */
  bg?: string
  /** 글자 색 (CSS color). 미지정 시 text-primary fallback. */
  fg?: string
  /** 표시할 텍스트 (보통 ticker 의 앞 2자리). 미지정 시 ticker[0..2]. */
  label?: string
  className?: string
}

/**
 * CompanyLogo — 회사 로고 자리 표시자 (배경 + 이니셜 텍스트).
 *
 * 디자인 매칭: DashboardPage.html `.tk-logo` + `.lg-nvda` 등 회사별 색.
 *
 * 토큰 정책:
 *  - 회사별 색은 디자인 캔버스 §1.6 에 정의된 헥스값을 fixture(holdings/companyDetail
 *    dev-mock) 가 보유하고 prop 으로 전달. 새 토큰을 추가하지 않는다.
 *  - bg/fg 미전달 시 surface-3 + text-primary 로 안전한 fallback.
 *
 * 사용처: HoldingsTable, EarningsTimeline (옵션), CompanyDrawer 헤더.
 */
export default function CompanyLogo({
  ticker,
  size = 22,
  bg,
  fg,
  label,
  className = '',
}: CompanyLogoProps) {
  const text = (label ?? ticker.slice(0, 2)).toUpperCase()

  const style: React.CSSProperties = {
    width: size,
    height: size,
    fontSize: Math.max(8, Math.round(size * 0.4)),
  }
  if (bg) style.backgroundColor = bg
  if (fg) style.color = fg
  // 디자인 캔버스의 inset 1px 보더 효과 — 헥스 미전달 시도 자연스럽게
  style.boxShadow = `inset 0 0 0 1px ${
    fg ? hexToRgba(fg, 0.18) : 'rgba(255,255,255,0.08)'
  }`

  const fallbackCls = bg ? '' : 'bg-surface-3'
  const fallbackTxt = fg ? '' : 'text-text-primary'

  return (
    <span
      aria-label={`${ticker} 로고`}
      style={style}
      className={`inline-grid place-items-center rounded-[4px] num font-bold tracking-[0.02em] ${fallbackCls} ${fallbackTxt} ${className}`}
    >
      {text}
    </span>
  )
}

function hexToRgba(hex: string, alpha: number): string {
  // 헥스 (#rgb / #rrggbb) → rgba(...). 형식 외에는 fg 를 그대로 반환 (브라우저가 무시).
  const m6 = /^#([0-9a-f]{6})$/i.exec(hex)
  const m3 = /^#([0-9a-f]{3})$/i.exec(hex)
  let r = 0
  let g = 0
  let b = 0
  if (m6) {
    r = parseInt(m6[1].slice(0, 2), 16)
    g = parseInt(m6[1].slice(2, 4), 16)
    b = parseInt(m6[1].slice(4, 6), 16)
  } else if (m3) {
    r = parseInt(m3[1][0] + m3[1][0], 16)
    g = parseInt(m3[1][1] + m3[1][1], 16)
    b = parseInt(m3[1][2] + m3[1][2], 16)
  } else {
    return hex
  }
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
