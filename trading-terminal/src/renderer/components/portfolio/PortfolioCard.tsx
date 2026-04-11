import type { Holding } from '../../store/usePortfolioStore'

interface Props {
  orderableCash: number
  totalCash: number
  holdings: Holding[]
  totalAsset: number
}

function AssetBar({ ratio, color }: { ratio: number; color: string }) {
  return (
    <div className="w-full h-1 bg-[#1e2738] rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(ratio * 100, 100)}%`, backgroundColor: color }}
      />
    </div>
  )
}

export default function PortfolioCard({ orderableCash, totalCash, holdings, totalAsset }: Props) {
  const stockValue = holdings.reduce((s, h) => s + h.qty * (h.currentPrice ?? 0), 0)
  const cashRatio = totalAsset > 0 ? totalCash / totalAsset : 1
  const stockRatio = totalAsset > 0 ? stockValue / totalAsset : 0

  return (
    <div className="flex flex-col h-full">
      {/* 총자산 섹션 */}
      <div className="px-5 pt-5 pb-4 border-b border-[#1e2738]">
        <p className="text-[10px] text-text-disabled uppercase tracking-widest mb-1">총 자산 (USD)</p>
        <p className="num text-2xl font-bold text-text-primary">
          ${totalAsset.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
      </div>

      {/* 현금/평가 섹션 */}
      <div className="px-5 py-4 border-b border-[#1e2738] flex flex-col gap-3">
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] text-text-disabled uppercase tracking-wide">현금</span>
            <div className="flex items-center gap-2">
              <div className="text-right">
                <span className="num text-sm text-text-primary">
                  ${totalCash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </span>
                <p className="num text-[10px] text-text-disabled">
                  주문가능 ${orderableCash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </p>
              </div>
              <span className="num text-[10px] text-text-disabled w-8 text-right">
                {(cashRatio * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <AssetBar ratio={cashRatio} color="#3b82f6" />
        </div>
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] text-text-disabled uppercase tracking-wide">평가</span>
            <div className="flex items-center gap-2">
              <span className="num text-sm text-text-primary">
                ${stockValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </span>
              <span className="num text-[10px] text-text-disabled w-8 text-right">
                {(stockRatio * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <AssetBar ratio={stockRatio} color="#22c55e" />
        </div>
      </div>

      {/* 보유 종목 */}
      {holdings.length > 0 ? (
        <div className="flex-1 overflow-y-auto">
          <div className="px-5 pt-3 pb-1">
            <span className="text-[10px] text-text-disabled uppercase tracking-widest">보유 종목</span>
          </div>
          {holdings.map((h) => {
            const price = h.currentPrice ?? 0
            const evalValue = h.qty * price
            const pnl = (price - h.avgPrice) * h.qty
            const pnlPct = h.avgPrice > 0 ? ((h.currentPrice - h.avgPrice) / h.avgPrice) * 100 : 0
            const isPositive = pnl >= 0
            return (
              <div
                key={h.ticker}
                className="flex items-center justify-between px-5 py-2.5
                           border-b border-[#1e2738] last:border-b-0
                           hover:bg-[#1c2330] transition-colors duration-100"
              >
                <div>
                  <p className="num text-sm font-semibold text-text-primary">{h.ticker}</p>
                  <p className="num text-[10px] text-text-disabled">{h.qty}주 @ ${h.avgPrice.toFixed(2)}</p>
                </div>
                <div className="text-right">
                  <p className="num text-sm text-text-primary">
                    ${evalValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </p>
                  <p className={`num text-[10px] ${isPositive ? 'text-buy' : 'text-sell'}`}>
                    {isPositive ? '+' : ''}{pnl.toFixed(2)} ({isPositive ? '+' : ''}{pnlPct.toFixed(1)}%)
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-text-disabled text-xs">보유 종목 없음</span>
        </div>
      )}
    </div>
  )
}
