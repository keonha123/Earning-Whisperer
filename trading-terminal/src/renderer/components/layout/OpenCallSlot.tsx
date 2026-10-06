import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import { useTradingStore } from '../../store/useTradingStore'
import { useTranscriptStore } from '../../store/useTranscriptStore'

type CallPhase = 'BEFORE' | 'LIVE' | 'ENDED'

const PHASE_LABEL: Record<CallPhase, string> = {
  BEFORE: '시작 전',
  LIVE: 'LIVE',
  ENDED: '종료',
}

/**
 * 메뉴 맨 위 "열린 콜" 자리 (docs/design/ux.md 메뉴).
 *
 * 빨강은 가격 상승에만 쓰므로 LIVE 는 무채색 점멸로 나타낸다.
 * 콜 화면을 열면 생기고, 종목과 콜 상태(시작 전 · LIVE · 종료)를 보여 준다. 시연 재생 중이면
 * 시연 표시를 늘 함께 둔다. 누르면 콜 화면으로 돌아가고, 닫기를 누르면 세션을 끝낸다.
 * 콜 상태는 콜 화면과 같은 기준(마지막 자막의 callId 가 종료 표시를 받았는지)으로 판단한다.
 */
export default function OpenCallSlot({ active }: { active: boolean }) {
  const isSessionActive = useTradingStore((s) => s.isSessionActive)
  const ticker = useTradingStore((s) => s.sessionTicker)
  const isDemo = useTradingStore((s) => s.isDemo)
  const setSession = useTradingStore((s) => s.setSession)
  const tickerState = useTranscriptStore((s) => (ticker ? s.byTicker.get(ticker) : undefined))
  const navigate = useNavigate()

  if (!isSessionActive || !ticker) return null

  const segments = tickerState?.segments ?? []
  const lastCallId = segments.length > 0 ? segments[segments.length - 1].callId : null
  const phase: CallPhase =
    lastCallId === null ? 'BEFORE' : tickerState?.endedCallIds.has(lastCallId) ? 'ENDED' : 'LIVE'

  async function handleClose() {
    await ipc.invoke(IPC_CHANNELS.TRADE_SESSION_END).catch(console.error)
    setSession(false)
    if (active) navigate('/home')
  }

  return (
    <div
      className={`glass rim rim-float group flex items-center gap-2 rounded-[20px] pl-3.5 pr-1.5 py-1.5
                  ${active ? '' : 'opacity-90 hover:opacity-100'}`}
    >
      <button
        type="button"
        onClick={() => navigate(`/call?ticker=${encodeURIComponent(ticker)}`)}
        className="flex-1 min-w-0 flex flex-col items-start gap-0.5 text-left py-0.5 on-glass"
        aria-current={active ? 'page' : undefined}
      >
        <span className="text-[11px] text-ink-3 font-medium">열린 콜</span>
        <span className="flex items-center gap-2 min-w-0">
          <span className="num text-[15px] font-bold text-ink-1 truncate">{ticker}</span>
          <PhaseMark phase={phase} />
          {isDemo && (
            <span
              className="px-1.5 py-px rounded-full border border-border-strong text-[10.5px] font-semibold text-ink-2"
              title="시연 재생 중입니다"
            >
              시연
            </span>
          )}
        </span>
      </button>
      <button
        type="button"
        onClick={() => void handleClose()}
        className="gbtn gbtn-icon gbtn-sm shrink-0"
        aria-label={`${ticker} 콜 닫기`}
        title="콜 닫기"
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  )
}

function PhaseMark({ phase }: { phase: CallPhase }) {
  if (phase === 'LIVE') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-bold text-ink-1">
        <span className="relative w-1.5 h-1.5">
          <span className="absolute inset-0 rounded-full bg-ink-1 opacity-60 animate-ping" />
          <span className="absolute inset-0 rounded-full bg-ink-1" />
        </span>
        {PHASE_LABEL.LIVE}
      </span>
    )
  }
  return <span className="text-[11px] font-medium text-ink-3">{PHASE_LABEL[phase]}</span>
}
