import { useConnectionStore } from '../../store/useConnectionStore'
import { useTradingStore } from '../../store/useTradingStore'

const WS_LABELS: Record<string, { label: string; color: string }> = {
  CONNECTED:    { label: 'WS 연결됨',    color: '#22c55e' },
  CONNECTING:   { label: '연결 중...',   color: '#f59e0b' },
  RECONNECTING: { label: '재연결 중...', color: '#f97316' },
  DISCONNECTED: { label: '연결 끊김',    color: '#ef4444' },
}

const KIS_LABELS: Record<string, { label: string; color: string }> = {
  VALID:   { label: 'KIS 유효',  color: '#22c55e' },
  EXPIRED: { label: 'KIS 만료', color: '#ef4444' },
  UNKNOWN: { label: 'KIS 확인 중', color: '#64748b' },
}

const MODE_LABELS: Record<string, string> = {
  MANUAL:     '수동',
  SEMI_AUTO:  '1-Click',
  AUTO_PILOT: '자동',
}

export default function StatusBar() {
  const { wsStatus, kisTokenStatus } = useConnectionStore()
  const { mode } = useTradingStore()

  const ws = WS_LABELS[wsStatus]
  const kis = KIS_LABELS[kisTokenStatus]

  return (
    <footer className="h-8 bg-[#0f1215] border-t border-[#2a3344] flex items-center gap-6 px-4">
      <div className="status-item">
        <span className="status-dot" style={{ backgroundColor: ws.color }} />
        <span className="text-text-secondary">{ws.label}</span>
      </div>

      <div className="status-item">
        <span className="status-dot" style={{ backgroundColor: kis.color }} />
        <span className="text-text-secondary">{kis.label}</span>
      </div>

      <div className="status-item">
        <span className="text-text-disabled">모드:</span>
        <span className="text-text-primary font-medium">{MODE_LABELS[mode]}</span>
      </div>
    </footer>
  )
}
