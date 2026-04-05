import { useTradingStore } from '../store/useTradingStore'
import { useUserStore } from '../store/useUserStore'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import ModeSelector from '../components/common/ModeSelector'
import EmaChart from '../components/trading/EmaChart'
import SignalFeed from '../components/trading/SignalFeed'
import RawScoreGauge from '../components/trading/RawScoreGauge'

function getScoreColor(score: number | null): string {
  if (score === null) return 'text-text-disabled'
  if (score <= 0.4) return 'text-sell'
  if (score <= 0.6) return 'text-connecting'
  return 'text-buy'
}

export default function TradingRoomPage() {
  const { mode, setMode, signalHistory, activeSignal } = useTradingStore()
  const { plan, settings, setSettings } = useUserStore()

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

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* 상단 바 */}
      <div className="flex items-center justify-between shrink-0 h-9">
        <div className="flex items-center gap-3">
          {/* LIVE 인디케이터 */}
          <div className="flex items-center gap-2 bg-buy/10 border border-buy/20 rounded-md px-3 py-1.5">
            <span className="w-2 h-2 rounded-full bg-buy animate-pulse" />
            <span className="text-buy text-xs font-bold tracking-widest">LIVE</span>
          </div>
          {activeSignal && (
            <span className="num text-sm font-semibold text-text-primary">{activeSignal.ticker}</span>
          )}
        </div>
        <div className="w-72">
          <ModeSelector currentMode={mode} userPlan={plan} onChange={handleModeChange} size="compact" />
        </div>
      </div>

      {/* 메인 그리드 */}
      <div className="grid grid-cols-5 gap-3 flex-1 min-h-0">
        {/* EMA 차트 (60%) */}
        <div className="col-span-3 card p-0 flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-[#1e2738] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">EMA 추세</span>
              {activeSignal && (
                <span className={`num text-xs font-medium px-1.5 py-0.5 rounded
                                ${activeSignal.action === 'BUY'
                                  ? 'bg-buy/15 text-buy'
                                  : 'bg-sell/15 text-sell'}`}>
                  {(activeSignal.ema_score * 100).toFixed(1)}
                </span>
              )}
            </div>
            {activeSignal && (
              <span className="num text-[10px] text-text-disabled">{activeSignal.ticker}</span>
            )}
          </div>
          <div className="flex-1 min-h-0 p-3">
            <EmaChart signalHistory={signalHistory} />
          </div>
        </div>

        {/* 신호 피드 + 게이지 (40%) */}
        <div className="col-span-2 card p-0 flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-[#1e2738] shrink-0 flex items-center justify-between">
            <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">신호 피드</span>
            <span className="num text-[10px] text-text-disabled">{signalHistory.length}건</span>
          </div>

          {/* 신호 목록 */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <SignalFeed items={signalHistory} />
          </div>

          {/* EMA 게이지 — 하단 고정 */}
          <div className="shrink-0 border-t border-[#1e2738] px-4 py-3">
            <div className="flex items-center gap-4">
              <div className="w-24 h-24 shrink-0">
                <RawScoreGauge score={activeSignal?.ema_score ?? null} />
              </div>
              <div className="flex flex-col gap-1.5">
                <div>
                  <p className="text-[10px] text-text-disabled uppercase tracking-wide">EMA Score</p>
                  <p className={`num text-2xl font-bold ${getScoreColor(activeSignal?.ema_score ?? null)}`}>
                    {activeSignal ? (activeSignal.ema_score * 100).toFixed(0) : '--'}
                  </p>
                </div>
                {activeSignal && (
                  <div className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-1 rounded
                                  ${activeSignal.action === 'BUY'
                                    ? 'bg-buy/15 text-buy'
                                    : 'bg-sell/15 text-sell'}`}>
                    <span>{activeSignal.action === 'BUY' ? '▲' : '▼'}</span>
                    <span>{activeSignal.action}</span>
                    <span className="num font-normal text-text-disabled">×{activeSignal.target_qty}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
