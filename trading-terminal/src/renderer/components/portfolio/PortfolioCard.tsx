import type { Holding } from '../../store/usePortfolioStore'
import type { IpcError } from '../../../lib/types/ipcError'
import StaleDataOverlay from '../common/StaleDataOverlay'

interface Props {
  orderableCash: number
  totalCash: number
  holdings: Holding[]
  totalAsset: number
  /**
   * F-2: 마지막 잔고 조회 실패 시 IpcError. null 이면 overlay 숨김.
   * 상위 (DashboardPage) 가 store 의 balanceFetchError 를 그대로 전달.
   */
  balanceFetchError?: IpcError | null
  /** F-2: overlay 의 "다시 조회" 버튼 클릭 핸들러. 미전달 시 버튼 숨김. */
  onRetryBalance?: () => void
  /** F-2: 재시도 진행 중 (보통 store.isSyncing). overlay 버튼 비활성. */
  isSyncing?: boolean
  /** F-2: 마지막 성공 동기화 시각 (epoch sec). overlay 하단 라벨에 사용. */
  lastSyncedAt?: number | null
}

function StackedBar({ cashRatio, stockRatio }: { cashRatio: number; stockRatio: number }) {
  return (
    <div className="w-full h-1.5 bg-[#1e2738] rounded-full overflow-hidden flex">
      <div
        className="h-full transition-all duration-500 bg-[#3b82f6]"
        style={{ width: `${Math.min(cashRatio * 100, 100)}%` }}
      />
      <div
        className="h-full transition-all duration-500 bg-[#22c55e]"
        style={{ width: `${Math.min(stockRatio * 100, 100)}%` }}
      />
    </div>
  )
}

export default function PortfolioCard({
  orderableCash,
  totalCash,
  holdings,
  totalAsset,
  balanceFetchError = null,
  onRetryBalance,
  isSyncing = false,
  lastSyncedAt = null,
}: Props) {
  const stockValue = holdings.reduce((s, h) => s + h.qty * (h.currentPrice ?? 0), 0)
  const cashRatio = totalAsset > 0 ? totalCash / totalAsset : 1
  const stockRatio = totalAsset > 0 ? stockValue / totalAsset : 0

  return (
    // F-2: overlay 가 absolute 로 깔리므로 컨테이너에 relative 필요.
    // 부모 section (DashboardPage) 도 relative 지만, 그 위 좌측 gradient 바를
    // 가리지 않도록 PortfolioCard 자체 박스로 overlay 범위 제한.
    <div className="flex flex-col h-full relative">
      {/* 총자산 섹션 */}
      <div className="px-5 pt-5 pb-4 border-b border-[#1e2738]">
        <p className="text-[10px] text-text-disabled uppercase tracking-widest mb-1">총 자산 (USD)</p>
        <p className="num text-2xl font-bold text-text-primary">
          ${totalAsset.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
      </div>

      {/* 현금/평가 통합 섹션 */}
      <div className="px-5 py-4">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#3b82f6] shrink-0" />
            <span className="text-[10px] text-text-disabled uppercase tracking-wide">현금</span>
            <span className="num text-sm text-text-primary">
              ${totalCash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </span>
            <span className="num text-[10px] text-text-disabled">
              ({(cashRatio * 100).toFixed(0)}%)
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="num text-[10px] text-text-disabled">
              ({(stockRatio * 100).toFixed(0)}%)
            </span>
            <span className="num text-sm text-text-primary">
              ${stockValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </span>
            <span className="text-[10px] text-text-disabled uppercase tracking-wide">평가</span>
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#22c55e] shrink-0" />
          </div>
        </div>
        <StackedBar cashRatio={cashRatio} stockRatio={stockRatio} />
        <p className="num text-[10px] text-text-disabled mt-1.5">
          주문가능 ${orderableCash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </p>
      </div>

      {/* F-2: stale 데이터 overlay — error 가 null 일 때 컴포넌트 자체가 null 반환하므로 무비용. */}
      <StaleDataOverlay
        error={balanceFetchError}
        onRetry={onRetryBalance}
        isRetrying={isSyncing}
        lastSyncedAt={lastSyncedAt}
      />
    </div>
  )
}
