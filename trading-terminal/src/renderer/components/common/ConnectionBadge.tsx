import type { WsStatus, KisTokenStatus } from '../../store/useConnectionStore'

interface Props {
  wsStatus: WsStatus
  kisTokenStatus: KisTokenStatus
  compact?: boolean
}

const WS_DOT_CLASS: Record<WsStatus, string> = {
  CONNECTED:    'bg-buy',
  CONNECTING:   'bg-warning',
  RECONNECTING: 'bg-warning',
  DISCONNECTED: 'bg-sell',
}

export default function ConnectionBadge({ wsStatus, kisTokenStatus, compact }: Props) {
  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <span className={`status-dot ${WS_DOT_CLASS[wsStatus] ?? WS_DOT_CLASS.DISCONNECTED}`} />
        {kisTokenStatus === 'EXPIRED' && (
          <span className="badge-danger text-xs">KIS 만료</span>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-4">
      <div className="status-item">
        <span className={`status-dot ${WS_DOT_CLASS[wsStatus] ?? WS_DOT_CLASS.DISCONNECTED}`} />
        <span className="text-text-tertiary">{wsStatus}</span>
      </div>
      <div className="status-item">
        <span
          className={`status-dot ${kisTokenStatus === 'VALID' ? 'bg-buy' : 'bg-sell'}`}
        />
        <span className="text-text-tertiary">KIS {kisTokenStatus}</span>
      </div>
    </div>
  )
}
