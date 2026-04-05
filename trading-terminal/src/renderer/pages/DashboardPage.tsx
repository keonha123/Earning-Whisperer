import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useTradingStore } from '../store/useTradingStore'
import { usePortfolioStore } from '../store/usePortfolioStore'
import { useUserStore } from '../store/useUserStore'
import ModeSelector from '../components/common/ModeSelector'
import SignalFeed from '../components/trading/SignalFeed'
import PortfolioCard from '../components/portfolio/PortfolioCard'

export default function DashboardPage() {
  const { mode, setMode, signalHistory } = useTradingStore()
  const { cash, holdings, lastSyncedAt, isSyncing, setBalance, setSyncing } = usePortfolioStore()
  const { plan, settings, setSettings } = useUserStore()

  useEffect(() => {
    syncBalance()
  }, [])

  async function syncBalance() {
    setSyncing(true)
    try {
      const balance = await ipc.invoke<{ cash: number; holdings: any[] }>(IPC_CHANNELS.KIS_GET_BALANCE)
      setBalance(balance.cash, balance.holdings)
    } catch (e) {
      console.error('잔고 조회 실패:', e)
    } finally {
      setSyncing(false)
    }
  }

  async function handleModeChange(newMode: typeof mode) {
    await ipc.invoke(IPC_CHANNELS.SETTINGS_UPDATE, {
      tradingMode: newMode,
      maxBuyRatio: settings.maxBuyRatio,
      maxHoldingRatio: settings.maxHoldingRatio,
      cooldownMinutes: settings.cooldownMinutes,
    })
    setMode(newMode)
    setSettings({ tradingMode: newMode })
  }

  const totalAsset = cash + holdings.reduce((sum, h) => sum + h.qty * h.currentPrice, 0)

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* 헤더 행 */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">대시보드</h2>
          {lastSyncedAt && (
            <p className="num text-[10px] text-text-disabled mt-0.5">
              마지막 동기화 {new Date(lastSyncedAt * 1000).toLocaleTimeString('ko-KR')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            className="flex items-center gap-1.5 text-xs text-text-disabled hover:text-text-primary
                       transition-colors duration-100 px-2 py-1 rounded hover:bg-[#1c2330]"
            onClick={syncBalance}
            disabled={isSyncing}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                 className={isSyncing ? 'animate-spin' : ''}>
              <path d="M21 2v6h-6" />
              <path d="M3 12a9 9 0 0115-6.7L21 8" />
              <path d="M3 22v-6h6" />
              <path d="M21 12a9 9 0 01-15 6.7L3 16" />
            </svg>
            {isSyncing ? '동기화 중' : '동기화'}
          </button>
          <ModeSelector currentMode={mode} userPlan={plan} onChange={handleModeChange} size="compact" />
        </div>
      </div>

      {/* 메인 그리드 */}
      <div className="grid grid-cols-5 gap-4 flex-1 min-h-0">
        {/* 포트폴리오 (40%) */}
        <div className="col-span-2 card flex flex-col gap-0 p-0 overflow-hidden">
          <PortfolioCard cash={cash} holdings={holdings} totalAsset={totalAsset} />
        </div>

        {/* 신호 피드 (60%) */}
        <div className="col-span-3 card flex flex-col p-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-[#1e2738] shrink-0 flex items-center justify-between">
            <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">최근 신호</span>
            <span className="num text-[10px] text-text-disabled">
              최근 {Math.min(signalHistory.length, 5)}건
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            <SignalFeed items={signalHistory.slice(0, 5)} />
          </div>
        </div>
      </div>
    </div>
  )
}
