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
          background: 'linear-gradient(135deg, #3a3b40, #26272b)',
          color: '#fbfaf6',
          boxShadow:
            '0 0 0 1px rgba(226,189,98,.5), 0 12px 32px -10px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.35)',
        }}
      >
        EW
      </div>
      <div className="text-text-primary text-base font-semibold tracking-tight whitespace-nowrap">
        EarningWhisperer Terminal
      </div>
      <div className="text-text-tertiary text-sm whitespace-nowrap">
        실시간 어닝콜 AI 분석 · 직접 주문
      </div>
    </div>
  )
}
