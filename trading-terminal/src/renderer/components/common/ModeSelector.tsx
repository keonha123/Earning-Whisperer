import type { TradingMode } from '../../store/useTradingStore'
import type { UserPlan } from '../../store/useUserStore'
import { useConnectionStore } from '../../store/useConnectionStore'

interface Props {
  currentMode: TradingMode
  userPlan: UserPlan
  onChange: (mode: TradingMode) => void
  size?: 'full' | 'compact'
}

const MODES: { value: TradingMode; label: string; proOnly: boolean }[] = [
  { value: 'MANUAL',     label: '수동 (Manual)',       proOnly: false },
  { value: 'SEMI_AUTO',  label: '1-Click (Semi-Auto)', proOnly: false },
  { value: 'AUTO_PILOT', label: '자동 (Auto-Pilot)',   proOnly: true },
]

export default function ModeSelector({ currentMode, userPlan, onChange, size = 'full' }: Props) {
  const wsStatus = useConnectionStore((s) => s.wsStatus)
  const isDisconnected = wsStatus === 'DISCONNECTED'

  return (
    <div className={`flex gap-2 ${size === 'full' ? 'p-4 bg-[#161b22] rounded-lg border border-[#2a3344]' : ''}`}>
      {MODES.map((m) => {
        const isLocked = m.proOnly && userPlan !== 'PRO'
        const isActive = currentMode === m.value
        const isDisabled = isDisconnected && m.value !== 'MANUAL'

        let cls = 'mode-tab-inactive'
        if (isActive) cls = 'mode-tab-active'
        if (isLocked || isDisabled) cls = 'mode-tab-locked'

        return (
          <button
            key={m.value}
            className={cls}
            disabled={isLocked || isDisabled}
            title={
              isLocked ? 'Pro 플랜에서 사용 가능합니다' :
              isDisabled ? '백엔드 연결 복구 후 전환 가능합니다' : undefined
            }
            onClick={() => !isLocked && !isDisabled && onChange(m.value)}
          >
            {m.label}
            {isLocked && <span className="ml-1 text-xs opacity-60">🔒</span>}
          </button>
        )
      })}
    </div>
  )
}
