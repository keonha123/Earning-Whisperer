import { useSearchParams } from 'react-router-dom'
import SegmentedControl from '../components/common/SegmentedControl'
import AssetsView from '../components/portfolio/AssetsView'
import HistoryPage from './HistoryPage'

type PortfolioTab = 'assets' | 'history'

const TABS: { id: PortfolioTab; label: string }[] = [
  { id: 'assets', label: '자산 · 보유' },
  { id: 'history', label: '거래 내역' },
]

/**
 * 포트폴리오 — 자산 · 보유 / 거래 내역 (docs/design/ux.md 정보 구조).
 *
 * 화면 명세는 docs/design/screens/portfolio.md. 탭은 ?tab= 으로 남겨
 * 다른 화면에서 거래 내역 탭으로 바로 보낼 수 있게 한다.
 */
export default function PortfolioPage() {
  const [params, setParams] = useSearchParams()
  const tab: PortfolioTab = params.get('tab') === 'history' ? 'history' : 'assets'

  return (
    <div className="flex flex-col gap-4 h-full min-h-0">
      <div className="flex items-center gap-4 shrink-0">
        <h1 className="text-[24px] font-bold tracking-[-0.02em] text-ink-1">포트폴리오</h1>
        <SegmentedControl
          items={TABS}
          activeId={tab}
          onChange={(id) => setParams(id === 'assets' ? {} : { tab: id }, { replace: true })}
        />
      </div>
      <div className="flex-1 min-h-0">
        {tab === 'history' ? (
          <HistoryPage />
        ) : (
          <AssetsView />
        )}
      </div>
    </div>
  )
}
