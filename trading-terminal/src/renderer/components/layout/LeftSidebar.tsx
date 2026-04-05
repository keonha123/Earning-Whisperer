const NAV_ITEMS = [
  { path: '/dashboard', label: '대시보드' },
  { path: '/trading-room', label: '트레이딩 룸' },
  { path: '/history', label: '체결 내역' },
  { path: '/settings', label: '설정' },
]

const NAV_ICONS: Record<string, React.ReactNode> = {
  '/dashboard': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
  '/trading-room': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="2 12 6 6 10 14 14 8 18 16 22 12" />
    </svg>
  ),
  '/history': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" />
      <rect x="9" y="3" width="6" height="4" rx="1" />
      <line x1="9" y1="12" x2="15" y2="12" />
      <line x1="9" y1="16" x2="13" y2="16" />
    </svg>
  ),
  '/settings': (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
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
      {/* 로고 섹션 — TopHeader와 높이 정렬 */}
      <div className="h-12 flex items-center px-4 border-b border-[#1e2738] shrink-0">
        <div className="flex items-center gap-2.5">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <rect width="20" height="20" rx="4" fill="#3b82f6" fillOpacity="0.15" />
            <rect x="0.75" y="0.75" width="18.5" height="18.5" rx="3.25"
                  stroke="#3b82f6" strokeWidth="1.5" />
            <path d="M5 10 L9 6 L13 10 L9 14 Z" fill="#3b82f6" />
          </svg>
          <div className="flex flex-col leading-none">
            <span className="text-text-primary text-xs font-bold tracking-widest uppercase">EW</span>
            <span className="text-text-disabled text-[10px] tracking-wide">Terminal</span>
          </div>
        </div>
      </div>

      {/* 네비게이션 */}
      <div className="flex-1 p-2 flex flex-col gap-0.5 mt-1">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.path}
            className={activePath === item.path ? 'nav-item-active' : 'nav-item'}
            onClick={() => onNavigate(item.path)}
          >
            <span className="w-4 h-4 shrink-0 flex items-center justify-center">
              {NAV_ICONS[item.path]}
            </span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      {/* 하단 버전 */}
      <div className="px-4 py-3 border-t border-[#1e2738] shrink-0">
        <span className="num text-[10px] text-text-disabled">v1.0.0</span>
      </div>
    </nav>
  )
}
