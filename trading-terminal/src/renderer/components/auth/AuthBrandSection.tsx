/**
 * AuthBrandSection — 인증 페이지 카드 위쪽 브랜드 영역.
 * 그라데이션 EW 로고 + 워드마크 + 서브 카피.
 */
export default function AuthBrandSection() {
  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className="w-11 h-11 rounded-xl grid place-items-center font-extrabold text-base tracking-tight"
        style={{
          background: 'linear-gradient(135deg, #34d399, #059669)',
          color: '#041711',
          boxShadow:
            '0 0 0 1px rgba(255,255,255,.06), 0 12px 40px -8px rgba(16,185,129,.55), inset 0 1px 0 rgba(255,255,255,.35)',
        }}
      >
        EW
      </div>
      <div className="text-text-primary text-base font-semibold tracking-tight whitespace-nowrap">
        EarningWhisperer Terminal
      </div>
      <div className="text-text-tertiary text-sm whitespace-nowrap">
        실시간 어닝콜 시그널 · AI 기반 자동매매
      </div>
    </div>
  )
}
