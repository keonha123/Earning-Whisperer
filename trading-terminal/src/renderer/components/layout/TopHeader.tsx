import { useConnectionStore } from '../../store/useConnectionStore'
import { useUserStore } from '../../store/useUserStore'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import ConnectionBadge from '../common/ConnectionBadge'

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': '대시보드',
  '/trading-room': '라이브 트레이딩 룸',
  '/history': '체결 내역',
  '/settings': '설정',
}

export default function TopHeader({ currentPath }: { currentPath: string }) {
  const { wsStatus, kisTokenStatus } = useConnectionStore()
  const { nickname } = useUserStore()
  const { setAuthenticated } = useConnectionStore()
  const { clear } = useUserStore()

  async function handleLogout() {
    await ipc.invoke(IPC_CHANNELS.AUTH_LOGOUT)
    setAuthenticated(false)
    clear()
  }

  return (
    <header className="h-12 bg-[#0f1215] border-b border-[#2a3344] flex items-center justify-between px-4">
      <div className="flex items-center gap-3">
        <span className="text-text-secondary text-xs font-medium uppercase tracking-widest">EW</span>
        <span className="text-text-primary font-medium">{PAGE_TITLES[currentPath] ?? ''}</span>
      </div>

      <div className="flex items-center gap-4">
        <ConnectionBadge wsStatus={wsStatus} kisTokenStatus={kisTokenStatus} compact />
        <span className="text-text-secondary text-sm">{nickname}</span>
        <button className="btn-ghost text-xs px-3 py-1.5" onClick={handleLogout}>
          로그아웃
        </button>
      </div>
    </header>
  )
}
