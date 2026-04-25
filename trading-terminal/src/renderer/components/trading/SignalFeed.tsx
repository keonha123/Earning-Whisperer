import { SignalFeedItem, SignalStatus } from '../../store/useTradingStore'

interface SignalFeedProps {
  items: SignalFeedItem[]
  maxItems?: number
}

const STATUS_CLASS: Record<SignalStatus, string> = {
  EXECUTED: 'badge-success',
  FAILED: 'badge-danger',
  PENDING: 'badge-warning',
  IGNORED: 'badge-neutral',
  REJECTED: 'badge-neutral',
}

const STATUS_LABEL: Record<SignalStatus, string> = {
  EXECUTED: '체결',
  FAILED: '실패',
  PENDING: '대기',
  IGNORED: '무시',
  REJECTED: '거절',
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export default function SignalFeed({ items, maxItems = 50 }: SignalFeedProps) {
  const visible = items.slice(0, maxItems)

  if (visible.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-disabled text-sm p-6">
        <span className="animate-pulse">신호 대기 중...</span>
      </div>
    )
  }

  return (
    <div className="overflow-y-auto h-full">
      {visible.map((item, index) => (
        <div key={item.trade_id} className={index === 0 ? 'signal-row-latest' : 'signal-row'}>
          <span className={item.action === 'BUY' ? 'badge-buy' : 'badge-sell'}>
            {item.action}
          </span>
          <div className="flex-1 min-w-0">
            <p className="num font-medium text-text-primary">{item.ticker}</p>
            <p className="num text-xs text-text-secondary">Score {item.ai_score.toFixed(3)}</p>
          </div>
          <span className={STATUS_CLASS[item.status]}>{STATUS_LABEL[item.status]}</span>
          <span className="num text-xs text-text-disabled ml-2">{formatTime(item.receivedAt)}</span>
        </div>
      ))}
    </div>
  )
}
