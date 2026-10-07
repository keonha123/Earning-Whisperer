import { useRef } from 'react'
import { useRefraction } from '../../lib/refraction'
import type { CallPhase } from '../../lib/callScreen'

interface CallBarProps {
  ticker: string
  companyName: string | null
  phase: CallPhase
  /** 시연 재생으로 들어온 콜인지. 시연 중에는 표시를 늘 둔다. */
  isDemo: boolean
  /** 콜 시작 기준 경과 시간. 자막이 없으면 null. */
  elapsedLabel: string | null
  /** 비교 대상 직전 콜. 첫 대조 항목이 도착하기 전에는 알 수 없어 null. */
  previousCallLabel: string | null
  speakerCount: number
  onSpeakers?: () => void
  onCompanyInfo: () => void
  onOrder: () => void
  /** 주문 시트가 열려 있는지. 버튼의 펼침 상태로 알린다. */
  orderOpen: boolean
  /** 시연 재생 제어. 지정하지 않으면 그리지 않는다. */
  demo?: {
    busy: boolean
    /** 시연 종목(WMT) 콜 화면인지. 시연 재생은 이 화면에서만 시작한다. */
    canStart: boolean
    onStart: () => void
    onStop: () => void
    onRestart: () => void
  }
}

const PHASE_LABEL: Record<CallPhase, string> = {
  BEFORE: '시작 전',
  LIVE: 'LIVE',
  ENDED: '종료',
}

/**
 * 콜 바 — 콜 화면 위쪽에 떠 있는 유리 캡슐 (design-system 판 · 콜 바 · 시트).
 *
 * 자막이 이 아래로 지나가므로 굴절을 건다. 종목 · 콜 상태 · 시연 표시 · 경과 시간 · 비교 대상을
 * 왼쪽에, 발화자 · 종목 정보 · 주문을 오른쪽에 둔다. 이 화면의 색상 유리 주 버튼은 `주문` 하나다.
 */
export default function CallBar({
  ticker,
  companyName,
  phase,
  isDemo,
  elapsedLabel,
  previousCallLabel,
  speakerCount,
  onSpeakers,
  onCompanyInfo,
  onOrder,
  orderOpen,
  demo,
}: CallBarProps) {
  const ref = useRef<HTMLDivElement>(null)
  useRefraction(ref, 14)

  return (
    <div
      ref={ref}
      className="glass rim rim-float rounded-full flex items-center gap-4 pl-6 pr-2 py-2 min-w-0 [-webkit-app-region:no-drag]"
      role="toolbar"
      aria-label={`${ticker} 콜`}
    >
      <div className="flex items-baseline gap-2.5 min-w-0 on-glass">
        <span className="num text-[16px] font-bold text-ink-1">{ticker}</span>
        {companyName && <span className="text-[13px] text-ink-2 truncate max-w-[180px]">{companyName}</span>}
      </div>

      <div className="flex items-center gap-2 shrink-0 on-glass">
        <PhaseMark phase={phase} />
        {isDemo && (
          <span
            className="px-2 py-0.5 rounded-full border border-border-strong text-[11px] font-semibold text-ink-2"
            title="준비된 어닝콜 스크립트를 재생하는 중입니다"
          >
            시연
          </span>
        )}
      </div>

      <div className="flex items-center gap-3 min-w-0 text-[12px] text-ink-3 on-glass">
        {elapsedLabel && (
          <span>
            <span className="num text-ink-2">{elapsedLabel}</span> 경과
          </span>
        )}
        {phase !== 'BEFORE' && (
          <span className="truncate" title="직전 콜 대조의 비교 대상">
            비교 대상 · {previousCallLabel ?? <span className="text-ink-4">첫 대조가 오면 표시합니다</span>}
          </span>
        )}
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-1.5 shrink-0">
        {demo && (
          <>
            {phase === 'LIVE' && isDemo ? (
              <button type="button" className="gbtn gbtn-sm" onClick={demo.onStop} disabled={demo.busy}>
                <StopIcon />
                중지
              </button>
            ) : null}
            {/* 시연은 시연 종목 콜 화면에서만 시작한다. 시작한 뒤에는 멈추거나 처음부터 다시 재생한다. */}
            {demo.canStart && !isDemo && (
              <button
                type="button"
                className="gbtn gbtn-sm"
                onClick={demo.onStart}
                disabled={demo.busy}
                title="준비된 어닝콜 스크립트를 재생합니다"
              >
                <PlayIcon />
                시연 재생
              </button>
            )}
            {isDemo && (
              <button
                type="button"
                className="gbtn gbtn-sm"
                onClick={demo.onRestart}
                disabled={demo.busy}
                title="시연 스크립트를 처음부터 다시 재생합니다"
              >
                <RestartIcon />
                처음부터
              </button>
            )}
          </>
        )}
        {onSpeakers && (
          <button type="button" className="gbtn gbtn-sm" onClick={onSpeakers} title="콜 참가자 명부와 발언 집계">
            발화자
            {speakerCount > 0 && <span className="tabular-nums text-ink-3">{speakerCount}</span>}
          </button>
        )}
        <button type="button" className="gbtn gbtn-sm" onClick={onCompanyInfo} aria-label={`${ticker} 종목 정보`}>
          종목 정보
        </button>
        <button type="button" className="gbtn gbtn-lapis gbtn-sm" onClick={onOrder} data-order-toggle="" aria-expanded={orderOpen}>
          주문
        </button>
      </div>
    </div>
  )
}

function PhaseMark({ phase }: { phase: CallPhase }) {
  if (phase === 'LIVE') {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] font-bold text-ink-1" role="status">
        <span className="relative w-2 h-2">
          <span className="absolute inset-0 rounded-full bg-ink-1 opacity-60 animate-ping" />
          <span className="absolute inset-0 rounded-full bg-ink-1" />
        </span>
        {PHASE_LABEL.LIVE}
      </span>
    )
  }
  return (
    <span className="text-[12px] font-semibold text-ink-3" role="status">
      {PHASE_LABEL[phase]}
    </span>
  )
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M5 3.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L5.9 2.7a.6.6 0 0 0-.9.5z" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <rect x="4.5" y="4.5" width="7" height="7" rx="1.2" />
    </svg>
  )
}

function RestartIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <path d="M3.5 8a4.5 4.5 0 1 0 1.4-3.3M3.5 2.5v2.6h2.6" />
    </svg>
  )
}
