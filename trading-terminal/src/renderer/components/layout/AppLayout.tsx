import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { isMac } from '../../lib/ipc'
import LeftSidebar from './LeftSidebar'
import CompanyDrawer from '../dashboard/CompanyDrawer'
import { useDrawerStore } from '../../store/useDrawerStore'

/**
 * 앱 셸 — 왼쪽 메뉴 판 + 내용.
 *
 * 위쪽 머리줄과 아래 상태 표시줄은 없앴다. 페이지 제목은 각 화면 안에, 연결 · KIS 상태와 계정은
 * 메뉴 아래쪽 한 곳에 둔다 (docs/design/ux.md). 바탕은 단색이고, 메뉴 판은 바탕에서 띄운 유리다.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const closeDrawer = useDrawerStore((s) => s.close)

  // 라우터 변경 시 drawer 닫기.
  // 사용자가 홈에서 drawer 를 열어둔 채 콜 화면으로 이동하면 컨텍스트가
  // 끊기므로 (다른 페이지의 다른 종목 컨텍스트), 페이지 전환 시 명시적으로 닫는다.
  useEffect(() => {
    closeDrawer()
  }, [location.pathname, closeDrawer])

  return (
    <div className="h-screen overflow-hidden bg-bg-base text-text-secondary grid grid-cols-[232px_1fr]">
      <div className="p-2.5 pr-0 min-h-0">
        <LeftSidebar activePath={location.pathname} onNavigate={navigate} />
      </div>

      <div className="relative min-w-0 min-h-0">
        {/* macOS 는 네이티브 제목 막대가 없어 내용 위쪽 여백 띠를 창 끌기 영역으로 쓴다.
            스크롤에 밀려 올라가지 않도록 스크롤 영역 밖에 둔다. */}
        {isMac && (
          <div className="absolute top-0 left-0 right-0 h-5 z-10 [-webkit-app-region:drag]" aria-hidden />
        )}
        <main className="h-full overflow-y-auto p-6">{children}</main>
      </div>

      {/*
        CompanyDrawer 전역 mount.
        - useDrawerStore.openTicker 가 non-null 인 동안 표시.
        - 홈 / 콜 화면 등 인증된 모든 페이지에서 useDrawerStore.open(ticker)
          호출만으로 표시 가능.
      */}
      <CompanyDrawer />
    </div>
  )
}
