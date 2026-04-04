import { useEffect } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { useTradingStore } from '../store/useTradingStore'
import { usePortfolioStore } from '../store/usePortfolioStore'
import { useUserStore } from '../store/useUserStore'
import ModeSelector from '../components/common/ModeSelector'

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
    <div className="flex flex-col gap-6">
      {/* 모드 선택 */}
      <ModeSelector currentMode={mode} userPlan={plan} onChange={handleModeChange} size="full" />

      {/* 포트폴리오 + 최근 신호 */}
      <div className="grid grid-cols-5 gap-6">
        {/* 포트폴리오 (40%) */}
        <div className="col-span-2 card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-text-primary">포트폴리오</h3>
            <button className="btn-ghost text-xs px-2 py-1" onClick={syncBalance} disabled={isSyncing}>
              {isSyncing ? '동기화 중...' : '↻ 동기화'}
            </button>
          </div>

          <div className="flex flex-col gap-3">
            <div>
              <p className="text-text-disabled text-xs">총 자산 (USD)</p>
              <p className="num text-2xl font-bold text-text-primary">${totalAsset.toLocaleString('en-US', { minimumFractionDigits: 2 })}</p>
            </div>
            <div>
              <p className="text-text-disabled text-xs">현금</p>
              <p className="num text-md text-text-primary">${cash.toLocaleString('en-US', { minimumFractionDigits: 2 })}</p>
            </div>
          </div>

          {holdings.length > 0 && (
            <div className="mt-4 border-t border-[#2a3344] pt-4">
              <p className="text-xs text-text-disabled mb-2">보유 종목</p>
              {holdings.map((h) => (
                <div key={h.ticker} className="flex justify-between items-center py-1.5 text-sm">
                  <span className="font-medium text-text-primary num">{h.ticker}</span>
                  <span className="text-text-secondary num">{h.qty}주</span>
                </div>
              ))}
            </div>
          )}

          {lastSyncedAt && (
            <p className="text-text-disabled text-xs mt-3">
              마지막 동기화: {new Date(lastSyncedAt * 1000).toLocaleTimeString('ko-KR')}
            </p>
          )}
        </div>

        {/* 최근 신호 피드 (60%) */}
        <div className="col-span-3 card">
          <h3 className="text-sm font-semibold text-text-primary mb-4">최근 신호</h3>
          {signalHistory.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-text-disabled text-sm">
              신호 대기 중
              <span className="animate-pulse ml-1">...</span>
            </div>
          ) : (
            <div className="flex flex-col">
              {signalHistory.slice(0, 5).map((s, i) => (
                <div key={s.trade_id} className={i === 0 ? 'signal-row-latest' : 'signal-row'}>
                  <span className={s.action === 'BUY' ? 'badge-buy' : 'badge-sell'}>{s.action}</span>
                  <span className="font-medium text-text-primary num flex-1">{s.ticker}</span>
                  <span className="num text-text-secondary text-xs">EMA {s.ema_score.toFixed(3)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
