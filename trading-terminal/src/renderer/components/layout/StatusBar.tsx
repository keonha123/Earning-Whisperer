import { useEffect, useState } from 'react'
import { useConnectionStore } from '../../store/useConnectionStore'
import { useTradingStore } from '../../store/useTradingStore'

const WS_CONFIG: Record<string, { label: string; color: string }> = {
  CONNECTED:    { label: 'WS',     color: '#22c55e' },
  CONNECTING:   { label: 'WS...',  color: '#f59e0b' },
  RECONNECTING: { label: 'WS↻',   color: '#f97316' },
  DISCONNECTED: { label: 'WS✕',   color: '#ef4444' },
}

const KIS_CONFIG: Record<string, { label: string; color: string }> = {
  VALID:   { label: 'KIS',  color: '#22c55e' },
  EXPIRED: { label: 'KIS✕', color: '#ef4444' },
  UNKNOWN: { label: 'KIS?', color: '#64748b' },
}

const MODE_CONFIG: Record<string, { label: string; color: string }> = {
  MANUAL:     { label: 'MANUAL',     color: '#94a3b8' },
  SEMI_AUTO:  { label: '1-CLICK',    color: '#f59e0b' },
  AUTO_PILOT: { label: 'AUTO-PILOT', color: '#22c55e' },
}

export default function StatusBar() {
  const { wsStatus, kisTokenStatus } = useConnectionStore()
  const { mode, signalHistory } = useTradingStore()
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  const ws = WS_CONFIG[wsStatus] ?? WS_CONFIG.DISCONNECTED
  const kis = KIS_CONFIG[kisTokenStatus] ?? KIS_CONFIG.UNKNOWN
  const modeConf = MODE_CONFIG[mode] ?? MODE_CONFIG.MANUAL
  const lastSignal = signalHistory[0]

  return (
    <footer className="h-8 bg-[#0f1215] border-t border-[#2a3344] flex items-center px-4 gap-0">
      <StatusItem color={ws.color} label={ws.label} pulse={wsStatus === 'CONNECTED'} />
      <StatusDivider />
      <StatusItem color={kis.color} label={kis.label} pulse={kisTokenStatus === 'VALID'} />
      <StatusDivider />

      {/* 현재 모드 */}
      <div className="flex items-center gap-1.5 px-2">
        <span className="text-text-disabled text-[10px] uppercase tracking-wide">MODE</span>
        <span className="num text-[10px] font-bold tracking-widest" style={{ color: modeConf.color }}>
          {modeConf.label}
        </span>
      </div>

      {/* 마지막 신호 */}
      {lastSignal && (
        <>
          <StatusDivider />
          <div className="flex items-center gap-1.5 px-2">
            <span className="text-text-disabled text-[10px]">신호</span>
            <span className={`num text-[10px] font-semibold ${lastSignal.action === 'BUY' ? 'text-buy' : 'text-sell'}`}>
              {lastSignal.ticker} {lastSignal.action}
            </span>
            <span className="num text-[10px] text-text-disabled">
              {new Date(lastSignal.receivedAt * 1000).toLocaleTimeString('ko-KR')}
            </span>
          </div>
        </>
      )}

      {/* 오른쪽 정렬 — 현재 시간 */}
      <div className="ml-auto flex items-center">
        <span className="num text-[10px] text-text-disabled">
          {now.toLocaleTimeString('ko-KR')}
        </span>
      </div>
    </footer>
  )
}

function StatusItem({ color, label, pulse }: { color: string; label: string; pulse?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 px-2">
      <span
        className={`w-1.5 h-1.5 rounded-full ${pulse ? 'animate-pulse' : ''}`}
        style={{ backgroundColor: color }}
      />
      <span className="num text-[10px] font-medium" style={{ color }}>{label}</span>
    </div>
  )
}

function StatusDivider() {
  return <span className="w-px h-3 bg-[#2a3344] mx-1" />
}
