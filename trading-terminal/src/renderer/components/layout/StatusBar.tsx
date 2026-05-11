import { useEffect, useState } from 'react'
import { useConnectionStore } from '../../store/useConnectionStore'
import { useTradingStore } from '../../store/useTradingStore'
import type { WsStatus, KisTokenStatus } from '../../store/useConnectionStore'
import type { TradingMode } from '../../store/useTradingStore'

const WS_CONFIG: Record<WsStatus, { label: string; dotClass: string; pulse: boolean }> = {
  CONNECTED:    { label: 'connected',    dotClass: 'bg-buy',     pulse: true  },
  CONNECTING:   { label: 'connecting…',  dotClass: 'bg-warning', pulse: true  },
  RECONNECTING: { label: 'reconnecting', dotClass: 'bg-warning', pulse: true  },
  DISCONNECTED: { label: 'disconnected', dotClass: 'bg-sell',    pulse: false },
}

const KIS_CONFIG: Record<KisTokenStatus, { label: string; dotClass: string; pulse: boolean }> = {
  VALID:   { label: '유효',     dotClass: 'bg-buy',     pulse: true  },
  EXPIRED: { label: '만료',     dotClass: 'bg-sell',    pulse: false },
  UNKNOWN: { label: '미연결',   dotClass: 'bg-neutral', pulse: false },
}

const MODE_CONFIG: Record<TradingMode, { label: string; toneClass: string }> = {
  MANUAL:     { label: '🛡 MANUAL',  toneClass: 'text-text-secondary' },
  SEMI_AUTO:  { label: '⚡ 1-CLICK', toneClass: 'text-warning' },
  AUTO_PILOT: { label: '🚀 AUTO',    toneClass: 'text-buy' },
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

  const kstString = formatKst(now)

  return (
    <footer className="h-8 bg-surface-0 border-t border-border-strong flex items-center px-3.5 gap-4 text-text-tertiary">
      <StatusItem
        labelClass="uppercase tracking-[0.12em]"
        label="WS"
        dotClass={ws.dotClass}
        pulse={ws.pulse}
        value={ws.label}
      />
      <Separator />
      <StatusItem
        labelClass="uppercase tracking-[0.12em]"
        label="KIS"
        dotClass={kis.dotClass}
        pulse={kis.pulse}
        value={kis.label}
      />
      <Separator />

      {/* 현재 모드 */}
      <div className="inline-flex items-center gap-1.5">
        <span className="text-text-tertiary text-[10px] uppercase tracking-[0.12em]">
          MODE
        </span>
        <span className={`num text-[10px] font-semibold tracking-[0.04em] ${modeConf.toneClass}`}>
          {modeConf.label}
        </span>
      </div>

      {/* 마지막 신호 */}
      {lastSignal && (
        <>
          <Separator />
          <div className="inline-flex items-center gap-1.5">
            <span className="text-text-tertiary text-[10px] uppercase tracking-[0.12em]">
              Last Signal
            </span>
            <span
              className={`num text-[10px] font-semibold ${
                lastSignal.action === 'BUY' ? 'text-buy' : 'text-sell'
              }`}
            >
              {lastSignal.ticker} {lastSignal.action === 'BUY' ? '▲' : '▼'} {lastSignal.action}
            </span>
            <span className="num text-[10px] text-text-tertiary tabular-nums">
              {new Date(lastSignal.receivedAt * 1000).toLocaleTimeString('ko-KR')}
            </span>
          </div>
        </>
      )}

      {/* 오른쪽 정렬 — KST 시간 */}
      <div className="ml-auto inline-flex items-center gap-1.5">
        <span className="text-text-tertiary text-[10px] uppercase tracking-[0.12em]">
          KST
        </span>
        <span className="num text-[10px] text-text-secondary tabular-nums tracking-[0.04em]">
          {kstString}
        </span>
      </div>
    </footer>
  )
}

interface StatusItemProps {
  label: string
  labelClass?: string
  dotClass: string
  pulse?: boolean
  value: string
}

function StatusItem({ label, labelClass = '', dotClass, pulse, value }: StatusItemProps) {
  return (
    <div className="inline-flex items-center gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full ${dotClass} ${pulse ? 'animate-pulse' : ''}`} />
      <span className={`text-text-tertiary text-[10px] ${labelClass}`}>{label}</span>
      <span className="num text-[10px] text-text-secondary tracking-[0.04em] normal-case">
        {value}
      </span>
    </div>
  )
}

function Separator() {
  return <span className="w-px h-3 bg-border-subtle" />
}

function formatKst(d: Date): string {
  // 2026-04-20 14:32:48
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
