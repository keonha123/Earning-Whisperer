import { useConnectionStore } from '../../store/useConnectionStore'
import type { WsStatus, KisTokenStatus } from '../../store/useConnectionStore'

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

export default function StatusBar() {
  const { wsStatus, kisTokenStatus } = useConnectionStore()

  const ws = WS_CONFIG[wsStatus] ?? WS_CONFIG.DISCONNECTED
  const kis = KIS_CONFIG[kisTokenStatus] ?? KIS_CONFIG.UNKNOWN

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

