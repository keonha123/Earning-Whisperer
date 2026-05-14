import SessionBadge from './SessionBadge'

const NAV_ITEMS = [
  { path: '/dashboard', label: '대시보드' },
  { path: '/market', label: 'Market' },
  { path: '/history', label: '체결 내역' },
  { path: '/settings', label: '설정' },
] as const

const NAV_ICONS: Record<string, React.ReactNode> = {
  '/dashboard': (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </svg>
  ),
  '/market': (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path d="M2 12l3-4 3 2 3-5 3 3" />
      <circle cx="13" cy="8" r="1" fill="currentColor" />
    </svg>
  ),
  '/history': (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path d="M2 3h12M2 8h12M2 13h12" />
    </svg>
  ),
  '/settings': (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <circle cx="8" cy="8" r="2.5" />
      <path d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4" />
    </svg>
  ),
}

interface Props {
  activePath: string
  onNavigate: (path: string) => void
}

export default function LeftSidebar({ activePath, onNavigate }: Props) {
  return (
    <nav className="flex flex-col h-full">
      {/* 브랜드 영역 */}
      <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-border-subtle shrink-0">
        <div
          className="w-6 h-6 rounded-md grid place-items-center text-[12px] font-bold num shrink-0 text-accent-foreground"
          style={{
            background: 'linear-gradient(135deg, var(--color-accent-500), var(--color-accent-700))',
            boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.08)',
          }}
        >
          EW
        </div>
        <div className="flex flex-col leading-tight min-w-0">
          <span className="text-text-primary text-[13px] font-semibold truncate">
            EarningWhisperer
          </span>
          <span className="text-text-disabled text-[10px] uppercase tracking-[0.14em] mt-0.5">
            Trading Terminal
          </span>
        </div>
      </div>

      {/* 네비게이션 */}
      <div className="flex-1 px-2 py-2.5 flex flex-col gap-0.5">
        <div className="text-text-disabled text-[10px] uppercase tracking-[0.14em] px-2.5 pt-2.5 pb-1.5">
          Workspace
        </div>
        {NAV_ITEMS.map((item) => (
          <NavItem
            key={item.path}
            label={item.label}
            icon={NAV_ICONS[item.path]}
            active={activePath === item.path}
            onClick={() => onNavigate(item.path)}
          />
        ))}
      </div>

      {/* 세션 배지 — 활성 세션 시에만 표시 */}
      <SessionBadge />

      {/* 하단 — PRO 뱃지 + 버전 */}
      <div className="mt-auto px-3 py-2.5 border-t border-border-subtle flex flex-col gap-1.5 shrink-0">
        <span
          className="inline-flex items-center gap-1.5 self-start px-2 py-[3px] rounded-sm text-[10px] font-semibold uppercase tracking-[0.12em] bg-accent-500/10 text-accent-400 border border-accent-500/25"
        >
          <span className="w-1 h-1 rounded-full bg-accent-400" />
          PRO
        </span>
        <span className="num text-[10px] text-text-disabled tracking-[0.08em]">
          v1.0.0
        </span>
      </div>
    </nav>
  )
}

interface NavItemProps {
  label: string
  icon: React.ReactNode
  active: boolean
  onClick: () => void
}

function NavItem({ label, icon, active, onClick }: NavItemProps) {
  const base =
    'flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[13px] font-medium whitespace-nowrap w-full transition-colors duration-100 cursor-pointer'
  const stateClass = active
    ? 'bg-surface-2 text-text-primary'
    : 'text-text-tertiary hover:bg-surface-2 hover:text-text-primary'

  return (
    <button type="button" className={`${base} ${stateClass}`} onClick={onClick}>
      <span
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          active
            ? 'bg-accent-500 shadow-[0_0_0_3px_rgba(16,185,129,0.15)]'
            : 'bg-border-strong'
        }`}
      />
      <span className="w-3.5 h-3.5 shrink-0 flex items-center justify-center opacity-85">
        {icon}
      </span>
      <span>{label}</span>
    </button>
  )
}
