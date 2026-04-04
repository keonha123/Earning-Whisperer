import { useTradingStore } from '../store/useTradingStore'
import { useUserStore } from '../store/useUserStore'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import ModeSelector from '../components/common/ModeSelector'

export default function TradingRoomPage() {
  const { mode, setMode, signalHistory } = useTradingStore()
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
        {/* 차트 영역 (60%) — 추후 lightweight-charts 적용 */}
        <div className="col-span-3 card flex flex-col">
          <h3 className="text-sm font-semibold text-text-primary mb-3">EMA 추세</h3>
          <div className="flex-1 flex items-center justify-center text-text-disabled text-sm">
            차트 준비 중 — 신호 수신 시 표시됩니다
          </div>
        </div>

        {/* 신호 피드 (40%) */}
        <div className="col-span-2 card flex flex-col min-h-0">
          <h3 className="text-sm font-semibold text-text-primary mb-3">신호 피드</h3>
          <div className="flex-1 overflow-y-auto -mx-6 -mb-6">
            {signalHistory.length === 0 ? (
              <div className="flex items-center justify-center h-full text-text-disabled text-sm p-6">
                신호 대기 중<span className="animate-pulse ml-1">...</span>
              </div>
            ) : (
              signalHistory.map((s, i) => (
                <div key={s.trade_id} className={i === 0 ? 'signal-row-latest' : 'signal-row'}>
                  <span className={s.action === 'BUY' ? 'badge-buy' : 'badge-sell'}>{s.action}</span>
                  <div className="flex-1 min-w-0">
                    <p className="num font-medium text-text-primary">{s.ticker}</p>
                    <p className="num text-xs text-text-secondary">EMA {s.ema_score.toFixed(3)}</p>
                  </div>
                  <StatusBadge status={s.status} />
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Raw Score 게이지 — 추후 구현 */}
      <div className="card h-16 flex items-center justify-center text-text-disabled text-sm">
        Raw Score 게이지
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    EXECUTED: 'badge-success',
    FAILED: 'badge-danger',
    PENDING: 'badge-warning',
    IGNORED: 'badge-neutral',
    REJECTED: 'badge-neutral',
  }
  const labels: Record<string, string> = {
    EXECUTED: '체결', FAILED: '실패', PENDING: '대기', IGNORED: '무시', REJECTED: '거절',
  }
  return <span className={map[status] ?? 'badge-neutral'}>{labels[status] ?? status}</span>
}
