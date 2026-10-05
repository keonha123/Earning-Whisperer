import { useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import { useTradingStore } from '../../store/useTradingStore'

export default function SessionBadge() {
  const isSessionActive = useTradingStore((s) => s.isSessionActive)
  const sessionTicker = useTradingStore((s) => s.sessionTicker)
  const setSession = useTradingStore((s) => s.setSession)
  const navigate = useNavigate()

  if (!isSessionActive) return null

  async function handleExit() {
    await ipc.invoke(IPC_CHANNELS.TRADE_SESSION_END).catch(console.error)
    setSession(false)
    navigate('/market')
  }

  return (
    <div className="mx-2 mb-2 rounded-lg bg-surface-2 border border-border-subtle px-3 py-2.5 flex flex-col gap-2">
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-accent-500" />
        <span className="text-[11px] font-semibold text-text-primary tracking-tight truncate flex-1 min-w-0">
          {sessionTicker}
        </span>
      </div>
      <button
        type="button"
        onClick={() => void handleExit()}
        className="w-full h-[26px] rounded-md text-[11px] font-semibold inline-flex items-center justify-center
                   bg-transparent border border-border-strong text-text-secondary
                   hover:bg-surface-3 hover:text-text-primary transition-colors"
      >
        나가기
      </button>
    </div>
  )
}
