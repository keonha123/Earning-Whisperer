import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import TopHeader from './TopHeader'
import LeftSidebar from './LeftSidebar'
import StatusBar from './StatusBar'
import ForcedManualBanner from '../common/ForcedManualBanner'
import CompanyDrawer from '../dashboard/CompanyDrawer'
import { useTradingStore } from '../../store/useTradingStore'
import { useDrawerStore } from '../../store/useDrawerStore'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { isForcedManual, forcedManualReason, clearForcedManual } = useTradingStore()
  const closeDrawer = useDrawerStore((s) => s.close)

  // 라우터 변경 시 drawer 닫기.
  // 사용자가 Dashboard 에서 drawer 를 열어둔 채 TradingRoom 으로 이동하면 컨텍스트가
  // 끊기므로 (다른 페이지의 다른 종목 컨텍스트), 페이지 전환 시 명시적으로 닫는다.
  useEffect(() => {
    closeDrawer()
  }, [location.pathname, closeDrawer])

  return (
    <div
      className="h-screen overflow-hidden bg-bg-base text-text-secondary"
      style={{
        display: 'grid',
        gridTemplateRows: 'auto 48px 1fr 32px',
        gridTemplateColumns: '200px 1fr',
        gridTemplateAreas: `
          "banner  banner"
          "header  header"
          "sidebar content"
          "statusbar statusbar"
        `,
      }}
    >
      {/* Forced Manual 배너 */}
      {isForcedManual && (
        <div style={{ gridArea: 'banner' }}>
          <ForcedManualBanner
            reason={forcedManualReason ?? ''}
            onDismiss={clearForcedManual}
          />
        </div>
      )}

      <div style={{ gridArea: 'header' }}>
        <TopHeader currentPath={location.pathname} />
      </div>

      <div
        style={{ gridArea: 'sidebar' }}
        className="bg-surface-0 border-r border-border-strong overflow-y-auto"
      >
        <LeftSidebar activePath={location.pathname} onNavigate={navigate} />
      </div>

      <main
        style={{ gridArea: 'content' }}
        className="overflow-y-auto p-6 bg-bg-base"
      >
        {children}
      </main>

      <div style={{ gridArea: 'statusbar' }}>
        <StatusBar />
      </div>

      {/*
        CompanyDrawer 전역 mount.
        - useDrawerStore.openTicker 가 non-null 인 동안 표시.
        - Dashboard / TradingRoom 등 인증된 모든 페이지에서 useDrawerStore.open(ticker)
          호출만으로 표시 가능. (이전에는 DashboardPage 내부에만 mount 되어 있어서
          TradingRoom 의 종목정보 버튼이 무반응이었음.)
      */}
      <CompanyDrawer />
    </div>
  )
}
