import { useEffect, useRef, useState } from 'react'
import type { TradeSignal } from '../../store/useTradingStore'

interface Props {
  signal: TradeSignal
  timeoutSeconds: number
  onApprove: () => Promise<void>
  onReject: () => void
  onTimeout: () => void
}

export default function TradeConfirmDialog({ signal, timeoutSeconds, onApprove, onReject, onTimeout }: Props) {
  const [remaining, setRemaining] = useState(timeoutSeconds)
  const [isLoading, setIsLoading] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      setRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(intervalRef.current!)
          onTimeout()
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(intervalRef.current!)
  }, [])

  // 키보드 단축키
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Enter' && !isLoading) handleApprove()
      if (e.key === 'Escape') onReject()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isLoading])

  async function handleApprove() {
    setIsLoading(true)
    clearInterval(intervalRef.current!)
    try {
      await onApprove()
    } finally {
      setIsLoading(false)
    }
  }

  const isUrgent = remaining <= 5
  const isBuy = signal.action === 'BUY'
  const progress = (remaining / timeoutSeconds) * 100

  return (
    <div className="confirm-dialog-overlay">
      <div className={isUrgent ? 'confirm-dialog-card-urgent' : 'confirm-dialog-card'}>
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-4">
          <span className="text-text-secondary text-sm">매매 신호 확인</span>
          <CountdownRing remaining={remaining} total={timeoutSeconds} urgent={isUrgent} />
        </div>

        {/* 신호 정보 */}
        <div className={`rounded-lg p-4 mb-5 ${isBuy ? 'bg-buy/10 border border-buy/30' : 'bg-sell/10 border border-sell/30'}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xl font-bold text-text-primary num">{signal.ticker}</span>
            <span className={`text-xl font-bold ${isBuy ? 'text-buy' : 'text-sell'}`}>
              {signal.action}
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-text-secondary">비중: <span className="num text-text-primary">{Math.round(signal.order_ratio * 100)}%</span></span>
            <span className="text-text-secondary">Score: <span className="num text-text-primary">{signal.ai_score.toFixed(3)}</span></span>
          </div>
        </div>

        {/* 타임아웃 프로그레스바 */}
        <div className="h-1 bg-[#232d3f] rounded-full mb-5 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-1000 ${isUrgent ? 'bg-sell' : isBuy ? 'bg-buy' : 'bg-sell'}`}
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* 버튼 */}
        <div className="flex gap-3">
          <button className="btn-reject flex-1" onClick={onReject} disabled={isLoading}>
            거절 (Esc)
          </button>
          <button
            className={`flex-1 ${isBuy ? 'btn-buy' : 'btn-sell'}`}
            onClick={handleApprove}
            disabled={isLoading}
          >
            {isLoading ? (
              <span className="flex items-center gap-2">
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                처리 중...
              </span>
            ) : (
              `승인 (Enter)`
            )}
          </button>
        </div>

        <p className="text-center text-text-disabled text-xs mt-3">
          {remaining}초 후 자동 취소
        </p>
      </div>
    </div>
  )
}

function CountdownRing({ remaining, total, urgent }: { remaining: number; total: number; urgent: boolean }) {
  const size = 44
  const stroke = 3
  const r = (size - stroke) / 2
  const circumference = 2 * Math.PI * r
  const offset = circumference - (remaining / total) * circumference

  return (
    <div className="relative w-11 h-11 flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#232d3f" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={urgent ? '#ef4444' : '#3b82f6'}
          strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-1000"
        />
      </svg>
      <span className={`absolute text-xs font-mono font-bold ${urgent ? 'text-sell' : 'text-text-primary'}`}>
        {remaining}
      </span>
    </div>
  )
}
