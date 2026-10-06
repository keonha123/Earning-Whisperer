import { isMac } from '../../lib/ipc'
import OpenCallSlot from './OpenCallSlot'
import ShellStatus from './ShellStatus'

/**
 * 메뉴 (docs/design/ux.md 정보 구조).
 *
 *  - 맨 위: 콜을 열었을 때만 생기는 "열린 콜" 자리
 *  - 가운데: 홈 · 종목 · 포트폴리오 · 설정
 *  - 아래쪽: 연결 · KIS 상태와 계정 — 앱 전체에서 상태를 보여 주는 곳은 여기 한 곳뿐이다
 *
 * 메뉴 판은 조작층이라 맑은 유리 + 금테 1px, 고른 메뉴는 세그먼트 썸과 같은 떠 있는 유리다.
 * 굴절은 걸지 않는다. 메뉴 판 뒤는 단색 바탕이라 휠 것이 없고, 판 안쪽 유리는 판에 가려 뒤를 보지 못한다.
 */
const NAV_ITEMS = [
  { path: '/home', label: '홈' },
  { path: '/stocks', label: '종목' },
  { path: '/portfolio', label: '포트폴리오' },
  { path: '/settings', label: '설정' },
] as const

const ICON_PROPS = {
  viewBox: '0 0 20 20',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

const NAV_ICONS: Record<(typeof NAV_ITEMS)[number]['path'], React.ReactNode> = {
  '/home': (
    <svg {...ICON_PROPS}>
      <path d="M3.5 9 10 3.5 16.5 9" />
      <path d="M5.5 7.5V16h9V7.5" />
    </svg>
  ),
  '/stocks': (
    <svg {...ICON_PROPS}>
      <circle cx="8.5" cy="8.5" r="5" />
      <path d="m12.5 12.5 4 4" />
    </svg>
  ),
  '/portfolio': (
    <svg {...ICON_PROPS}>
      <rect x="3" y="6" width="14" height="10" rx="2.5" />
      <path d="M7 6V4.5h6V6M3 10.5h14" />
    </svg>
  ),
  '/settings': (
    <svg {...ICON_PROPS}>
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1 4.7 4.7" />
    </svg>
  ),
}

interface Props {
  activePath: string
  onNavigate: (path: string) => void
}

export default function LeftSidebar({ activePath, onNavigate }: Props) {
  return (
    <nav className="glass glass-flat rim h-full rounded-[24px] flex flex-col" aria-label="메뉴">
      {/* 이름 — macOS 는 창 단추 아래로 내리고, 이 띠를 창 끌기 영역으로 쓴다 */}
      <div
        className={`shrink-0 px-5 ${isMac ? 'pt-11 [-webkit-app-region:drag]' : 'pt-5'} pb-4`}
      >
        <span className="on-glass text-[17px] font-semibold tracking-[0.01em] text-ink-1">Logothea</span>
      </div>

      <div className="px-2.5 pb-3 shrink-0">
        <OpenCallSlot active={activePath === '/call'} />
      </div>

      <ul className="flex-1 px-2.5 flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <li key={item.path}>
            <NavItem
              label={item.label}
              icon={NAV_ICONS[item.path]}
              active={activePath === item.path}
              onClick={() => onNavigate(item.path)}
            />
          </li>
        ))}
      </ul>

      <ShellStatus onOpenSettings={() => onNavigate('/settings')} />
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
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-full text-[14px] transition-[color,transform] duration-200 ease-spring active:scale-[0.97]
        ${
          active
            ? 'glass rim rim-float text-ink-1 font-semibold on-glass'
            : 'text-ink-3 font-medium hover:text-ink-1 hover:bg-white/[0.04]'
        }`}
    >
      <span className="w-[18px] h-[18px] shrink-0 [&>svg]:w-full [&>svg]:h-full">{icon}</span>
      <span>{label}</span>
    </button>
  )
}
