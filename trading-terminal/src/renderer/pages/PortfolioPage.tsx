import { useSearchParams } from 'react-router-dom'
import SegmentedControl from '../components/common/SegmentedControl'
import { ComingSoon } from '../components/common/StateView'
import HistoryPage from './HistoryPage'

type PortfolioTab = 'assets' | 'history'

const TABS: { id: PortfolioTab; label: string }[] = [
  { id: 'assets', label: '자산 · 보유' },
  { id: 'history', label: '거래 내역' },
]

/**
 * 포트폴리오 — 자산 · 보유 / 거래 내역 (docs/design/ux.md 정보 구조).
 *
 * 메뉴 개편(#154) 단계에서는 자리만 잡는다. 거래 내역 탭은 예전 체결 내역 화면을 그대로 담고,
 * 자산 · 보유는 화면 이슈(#158)에서 홈의 계좌 카드를 옮겨 온다. 탭은 ?tab= 으로 남겨
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
          <ComingSoon title="자산 · 보유" note="지금은 홈 화면에서 계좌와 보유 종목을 볼 수 있습니다" />
        )}
      </div>
    </div>
  )
}
