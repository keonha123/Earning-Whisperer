const NAV_ITEMS = [
  { path: '/dashboard', label: '대시보드', icon: '⬡' },
  { path: '/trading-room', label: '트레이딩 룸', icon: '◈' },
  { path: '/history', label: '체결 내역', icon: '≡' },
  { path: '/settings', label: '설정', icon: '⚙' },
]

interface Props {
  activePath: string
  onNavigate: (path: string) => void
}

export default function LeftSidebar({ activePath, onNavigate }: Props) {
  return (
    <nav className="p-3 flex flex-col gap-1">
      {NAV_ITEMS.map((item) => (
        <button
          key={item.path}
          className={activePath === item.path ? 'nav-item-active' : 'nav-item'}
          onClick={() => onNavigate(item.path)}
        >
          <span className="text-base w-5 text-center">{item.icon}</span>
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  )
}
