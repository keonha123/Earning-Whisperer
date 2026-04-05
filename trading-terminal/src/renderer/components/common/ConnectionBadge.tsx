import type { WsStatus, KisTokenStatus } from '../../store/useConnectionStore'

interface Props {
  wsStatus: WsStatus
  kisTokenStatus: KisTokenStatus
  compact?: boolean
}

const WS_COLOR: Record<WsStatus, string> = {
  CONNECTED: '#22c55e',
  CONNECTING: '#f59e0b',
  RECONNECTING: '#f97316',
  DISCONNECTED: '#ef4444',
}

export default function ConnectionBadge({ wsStatus, kisTokenStatus, compact }: Props) {
  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <span className="status-dot" style={{ backgroundColor: WS_COLOR[wsStatus] }} />
        {kisTokenStatus === 'EXPIRED' && (
          <span className="badge-danger text-xs">KIS 만료</span>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-4">
      <div className="status-item">
        <span className="status-dot" style={{ backgroundColor: WS_COLOR[wsStatus] }} />
        <span className="text-text-secondary">{wsStatus}</span>
      </div>
      <div className="status-item">
        <span
          className="status-dot"
          style={{ backgroundColor: kisTokenStatus === 'VALID' ? '#22c55e' : '#ef4444' }}
        />
        <span className="text-text-secondary">KIS {kisTokenStatus}</span>
      </div>
    </div>
  )
}
