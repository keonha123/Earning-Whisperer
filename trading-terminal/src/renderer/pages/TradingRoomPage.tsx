import { useTradingStore } from '../store/useTradingStore'
import { useUserStore } from '../store/useUserStore'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import ModeSelector from '../components/common/ModeSelector'
import EmaChart from '../components/trading/EmaChart'
import SignalFeed from '../components/trading/SignalFeed'
import RawScoreGauge from '../components/trading/RawScoreGauge'

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
    <div className="flex flex-col gap-4 h-full">
      {/* 상단 모드 바 */}
      <div className="flex items-center justify-between">
        <h2 className="text-md font-semibold text-text-primary">라이브 트레이딩 룸</h2>
        <div className="w-80">
          <ModeSelector currentMode={mode} userPlan={plan} onChange={handleModeChange} size="compact" />
        </div>
      </div>

      {/* 메인 레이아웃 */}
      <div className="grid grid-cols-5 gap-4 flex-1 min-h-0">
        {/* 차트 영역 (60%) */}
        <div className="col-span-3 card flex flex-col">
          <h3 className="text-sm font-semibold text-text-primary mb-3">EMA 추세</h3>
          <div className="flex-1 min-h-0">
            <EmaChart signalHistory={signalHistory} />
          </div>
        </div>

        {/* 신호 피드 (40%) */}
        <div className="col-span-2 card flex flex-col min-h-0">
          <h3 className="text-sm font-semibold text-text-primary mb-3">신호 피드</h3>
          <div className="flex-1 overflow-y-auto -mx-6 -mb-6">
            <SignalFeed items={signalHistory} />
          </div>
        </div>
      </div>

      {/* Raw Score 게이지 */}
      <div className="card h-32">
        <RawScoreGauge score={activeSignal?.ema_score ?? null} />
      </div>
    </div>
  )
}
