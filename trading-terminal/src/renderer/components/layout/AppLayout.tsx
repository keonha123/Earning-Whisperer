import { useLocation, useNavigate } from 'react-router-dom'
import TopHeader from './TopHeader'
import LeftSidebar from './LeftSidebar'
import StatusBar from './StatusBar'
import ForcedManualBanner from '../common/ForcedManualBanner'
import { useTradingStore } from '../../store/useTradingStore'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { isForcedManual, forcedManualReason, clearForcedManual } = useTradingStore()

  return (
    <div
      className="h-screen overflow-hidden"
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

      <div style={{ gridArea: 'sidebar' }} className="bg-[#0f1215] border-r border-[#2a3344] overflow-y-auto">
        <LeftSidebar activePath={location.pathname} onNavigate={navigate} />
      </div>

      <main style={{ gridArea: 'content' }} className="overflow-y-auto p-6 bg-bg-base">
        {children}
      </main>

      <div style={{ gridArea: 'statusbar' }}>
        <StatusBar />
      </div>
    </div>
  )
}
