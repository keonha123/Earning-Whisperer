import { useConnectionStore } from '../../store/useConnectionStore'
import { useUserStore } from '../../store/useUserStore'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import type { WsStatus, KisTokenStatus } from '../../store/useConnectionStore'

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': '대시보드',
  '/trading-room': 'Trading Room',
  '/history': '체결 내역',
  '/settings': '설정',
}

const WS_DOT_TONE: Record<WsStatus, string> = {
  CONNECTED: 'bg-buy shadow-[0_0_0_2px_rgba(16,185,129,0.2)]',
  CONNECTING: 'bg-warning shadow-[0_0_0_2px_rgba(245,158,11,0.2)]',
  RECONNECTING: 'bg-warning shadow-[0_0_0_2px_rgba(245,158,11,0.2)]',
  DISCONNECTED: 'bg-sell shadow-[0_0_0_2px_rgba(239,68,68,0.2)]',
}

const KIS_DOT_TONE: Record<KisTokenStatus, string> = {
  VALID: 'bg-buy shadow-[0_0_0_2px_rgba(16,185,129,0.2)]',
  EXPIRED: 'bg-sell shadow-[0_0_0_2px_rgba(239,68,68,0.2)]',
  UNKNOWN: 'bg-neutral shadow-[0_0_0_2px_rgba(100,116,139,0.2)]',
}

export default function TopHeader({ currentPath }: { currentPath: string }) {
  const { wsStatus, kisTokenStatus, setAuthenticated } = useConnectionStore()
  const { nickname, clear } = useUserStore()

  async function handleLogout() {
    try {
      await ipc.invoke(IPC_CHANNELS.AUTH_LOGOUT)
    } finally {
      setAuthenticated(false)
      clear()
    }
  }

  const wsLabel = wsStatus === 'CONNECTED' ? 'WS' : wsStatus === 'RECONNECTING' ? 'WS↻' : 'WS✕'
  const kisLabel = kisTokenStatus === 'VALID' ? 'KIS' : kisTokenStatus === 'EXPIRED' ? 'KIS✕' : 'KIS?'

  return (
    <header className="h-12 bg-surface-0 border-b border-border-strong flex items-center px-4 gap-3">
      {/*
        좌측: 브레드크럼 + 페이지 타이틀.
        모든 페이지에서 동일하게 워크스페이스 + 페이지 타이틀 + WS/KIS/유저 만 표시한다.
        TradingRoom 의 ticker / 회사명 / LIVE / 종목정보 버튼은 TradingRoomHeader 가 흡수
        (페이지 내부 상단 행). 두 곳에서 같은 ticker 가 중복 표시되지 않도록 분리.
      */}
      <div className="flex items-center gap-2.5 min-w-0 flex-1">
        <span className="text-text-tertiary text-[11px] font-medium uppercase tracking-[0.12em] shrink-0">
          Workspace /
        </span>
        <span className="text-text-primary text-sm font-semibold tracking-[0.01em] truncate">
          {PAGE_TITLES[currentPath] ?? ''}
        </span>
      </div>

      {/* 우측: 연결 상태 + 유저 + 로그아웃 */}
      <div className="flex items-center gap-2 shrink-0">
        <ConnectionDot
          dotClass={WS_DOT_TONE[wsStatus] ?? WS_DOT_TONE.DISCONNECTED}
          label={wsLabel}
        />
        <ConnectionDot
          dotClass={KIS_DOT_TONE[kisTokenStatus] ?? KIS_DOT_TONE.UNKNOWN}
          label={kisLabel}
        />

        <div className="flex items-center gap-2 pl-1">
          <div
            className="w-6 h-6 rounded-full grid place-items-center text-[11px] font-semibold text-text-primary"
            // design-canvas: avatar gradient (slate-700 → slate-800), surface 토큰과 다른 의도된 hex
            style={{ background: 'linear-gradient(135deg, #334155, #1e293b)' }}
          >
            {(nickname || '··').slice(0, 2).toUpperCase()}
          </div>
          <span className="text-text-secondary text-xs num truncate max-w-[140px]">
            {nickname}
          </span>
        </div>

        <button
          className="text-text-tertiary hover:text-sell text-xs transition-colors duration-100 px-2 py-1 rounded hover:bg-sell/10"
          onClick={handleLogout}
        >
          로그아웃
        </button>
      </div>
    </header>
  )
}

interface ConnectionDotProps {
  dotClass: string
  label: string
}

function ConnectionDot({ dotClass, label }: ConnectionDotProps) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded border border-border-subtle text-[10px] tracking-[0.1em] uppercase text-text-tertiary">
      <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
      {label}
    </span>
  )
}
