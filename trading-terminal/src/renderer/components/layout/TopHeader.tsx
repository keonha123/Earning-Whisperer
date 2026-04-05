import { useConnectionStore } from '../../store/useConnectionStore'
import { useUserStore } from '../../store/useUserStore'
import { useTradingStore } from '../../store/useTradingStore'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': '대시보드',
  '/trading-room': '트레이딩 룸',
  '/history': '체결 내역',
  '/settings': '설정',
}

const WS_COLOR: Record<string, string> = {
  CONNECTED:    '#22c55e',
  CONNECTING:   '#f59e0b',
  RECONNECTING: '#f97316',
  DISCONNECTED: '#ef4444',
}

export default function TopHeader({ currentPath }: { currentPath: string }) {
  const { wsStatus, kisTokenStatus, setAuthenticated } = useConnectionStore()
  const { nickname, clear } = useUserStore()
  const { activeSignal } = useTradingStore()

  async function handleLogout() {
    try {
      await ipc.invoke(IPC_CHANNELS.AUTH_LOGOUT)
    } finally {
      setAuthenticated(false)
      clear()
    }
  }

  const wsColor = WS_COLOR[wsStatus] ?? '#ef4444'
  const wsLabel = wsStatus === 'CONNECTED' ? 'WS' : wsStatus === 'RECONNECTING' ? 'WS↻' : 'WS✕'
  const kisColor = kisTokenStatus === 'VALID' ? '#22c55e' : '#ef4444'

  return (
    <header className="h-12 bg-[#0f1215] border-b border-[#2a3344] flex items-center justify-between px-4">
      {/* 좌측: 브레드크럼 타이틀 */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-text-disabled text-xs font-medium uppercase tracking-widest shrink-0">EW</span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-[#2a3344] shrink-0">
          <path d="M4 2 L8 6 L4 10" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="text-text-primary text-sm font-semibold truncate">
          {PAGE_TITLES[currentPath] ?? ''}
        </span>
      </div>

      {/* 중앙: 활성 시그널 ticker (트레이딩 룸에서만) */}
      {currentPath === '/trading-room' && activeSignal && (
        <div className="flex items-center gap-2 bg-[#161b22] border border-[#2a3344] rounded-md px-3 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-buy animate-pulse shrink-0" />
          <span className="num text-sm font-medium text-text-primary">{activeSignal.ticker}</span>
          <span className={`text-xs font-medium num ${activeSignal.action === 'BUY' ? 'text-buy' : 'text-sell'}`}>
            {activeSignal.action}
          </span>
          <span className="num text-xs text-text-disabled">
            {(activeSignal.ema_score * 100).toFixed(0)}
          </span>
        </div>
      )}

      {/* 우측: 연결 상태 + 유저 */}
      <div className="flex items-center gap-3">
        <HeaderStatusDot color={wsColor} label={wsLabel} active={wsStatus === 'CONNECTED'} />
        <HeaderStatusDot color={kisColor} label="KIS" active={kisTokenStatus === 'VALID'} />
        <div className="w-px h-4 bg-[#2a3344]" />
        <span className="text-text-secondary text-xs num">{nickname}</span>
        <button
          className="text-text-disabled hover:text-sell text-xs transition-colors duration-100 px-2 py-1 rounded hover:bg-sell/10"
          onClick={handleLogout}
        >
          로그아웃
        </button>
      </div>
    </header>
  )
}

function HeaderStatusDot({ color, label, active }: { color: string; label: string; active: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`w-1.5 h-1.5 rounded-full ${active ? 'animate-pulse' : ''}`}
        style={{ backgroundColor: color }}
      />
      <span className="text-[10px] font-medium text-text-disabled num">{label}</span>
    </div>
  )
}
