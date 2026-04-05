import type { TradingMode } from '../../store/useTradingStore'
import type { UserPlan } from '../../store/useUserStore'
import { useConnectionStore } from '../../store/useConnectionStore'

interface Props {
  currentMode: TradingMode
  userPlan: UserPlan
  onChange: (mode: TradingMode) => void
  size?: 'full' | 'compact'
}

const MODE_CONFIG: Record<TradingMode, {
  label: string
  sublabel: string
  proOnly: boolean
  icon: React.ReactNode
  activeClass: string
  inactiveClass: string
}> = {
  MANUAL: {
    label: '수동',
    sublabel: 'Manual',
    proOnly: false,
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
    activeClass: 'mode-tab-manual-active',
    inactiveClass: 'mode-tab-manual-inactive',
  },
  SEMI_AUTO: {
    label: '1-Click',
    sublabel: 'Semi-Auto',
    proOnly: false,
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
    ),
    activeClass: 'mode-tab-semi-active',
    inactiveClass: 'mode-tab-semi-inactive',
  },
  AUTO_PILOT: {
    label: '자동',
    sublabel: 'Auto-Pilot',
    proOnly: true,
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2L8.5 8.5H3L7.5 13l-2 7 6.5-4 6.5 4-2-7L20.5 8.5H15L12 2z" />
      </svg>
    ),
    activeClass: 'mode-tab-auto-active',
    inactiveClass: 'mode-tab-auto-inactive',
  },
}

export default function ModeSelector({ currentMode, userPlan, onChange, size = 'full' }: Props) {
  const wsStatus = useConnectionStore((s) => s.wsStatus)
  const isDisconnected = wsStatus === 'DISCONNECTED'

  return (
    <div className={`flex gap-1.5 ${
      size === 'full'
        ? 'p-3 bg-[#161b22] rounded-lg border border-[#2a3344]'
        : ''
    }`}>
      {(Object.entries(MODE_CONFIG) as [TradingMode, typeof MODE_CONFIG[TradingMode]][]).map(([value, conf]) => {
        const isLocked = conf.proOnly && userPlan !== 'PRO'
        const isActive = currentMode === value
        const isDisabled = isDisconnected && value !== 'MANUAL'

        let cls = conf.inactiveClass
        if (isActive) cls = conf.activeClass
        if (isLocked || isDisabled) cls = 'mode-tab-locked'

        return (
          <button
            key={value}
            className={cls}
            disabled={isLocked || isDisabled}
            title={
              isLocked
                ? 'Pro 플랜에서 사용 가능합니다'
                : isDisabled
                  ? '백엔드 연결 복구 후 전환 가능합니다'
                  : undefined
            }
            onClick={() => !isLocked && !isDisabled && onChange(value)}
          >
            <span className="opacity-80">{conf.icon}</span>
            <span className="text-[10px] leading-none">{conf.label}</span>
            {size === 'full' && (
              <span className="text-[9px] opacity-50 leading-none">{conf.sublabel}</span>
            )}
            {isLocked && (
              <span className="absolute top-1 right-1">
                <svg width="8" height="8" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" />
                  <path d="M7 11V7a5 5 0 0110 0v4" />
                </svg>
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
