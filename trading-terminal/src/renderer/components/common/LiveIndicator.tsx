interface LiveIndicatorProps {
  /** true: 빨간 펄스 + LIVE 라벨. false: 회색 dot + 대기 중 라벨. */
  active: boolean
  /** active=true 일 때 표시 라벨 (기본 "LIVE"). */
  label?: string
  /** active=false 일 때 표시 라벨 (기본 "대기 중"). */
  idleLabel?: string
}

/**
 * LiveIndicator — 헤더용 LIVE 상태 뱃지.
 *
 * 디자인 매칭: TradingRoomPage.html `.live-pulse` + `.live-dot`.
 *  - active: rgba(239,68,68,.1) 배경 + 빨간 펄스 닷 + sell 컬러 라벨.
 *  - idle: 투명 배경 + 회색 닷 + tertiary 라벨.
 *
 * 사용처: TradingRoomHeader (활성 어닝콜 = 신호 수신 중 ↔ 비수신).
 */
export default function LiveIndicator({
  active,
  label = 'LIVE',
  idleLabel = '대기 중',
}: LiveIndicatorProps) {
  if (active) {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2 py-[3px] rounded
                   bg-sell/10 border border-sell/30 text-sell
                   text-[10px] font-bold tracking-[0.14em]"
        role="status"
        aria-label="LIVE 진행 중"
      >
        <span className="relative w-1.5 h-1.5">
          {/* 펄스 (ping) — 디자인 캔버스의 box-shadow expand 와 동일 효과 */}
          <span className="absolute inset-0 rounded-full bg-sell opacity-60 animate-ping" />
          <span className="absolute inset-0 rounded-full bg-sell" />
        </span>
        {label}
      </span>
    )
  }

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-[3px] rounded
                 border border-border-subtle text-text-tertiary
                 text-[10px] font-semibold tracking-[0.14em]"
      role="status"
      aria-label="LIVE 비활성"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-border-strong" />
      {idleLabel}
    </span>
  )
}
