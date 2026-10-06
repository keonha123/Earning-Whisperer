import { directionClass, directionMark, signedPct, signedUsd, usd } from './format'

interface AssetSummaryProps {
  totalAsset: number
  totalCash: number
  orderableCash: number
  stockValue: number
  unrealizedPnl: number
  unrealizedPct: number
  /** 전일 종가를 아는 종목이 하나도 없으면 null. */
  dailyPnl: number | null
}

/**
 * 계좌 요약 — 예전 대시보드 캐러셀의 "자산 현황" · "일간 손익" · "미실현 손익" 합계를 한 판에 모은다.
 * 종목별 손익과 비중은 보유 표의 열로 옮겼다.
 */
export default function AssetSummary({
  totalAsset,
  totalCash,
  orderableCash,
  stockValue,
  unrealizedPnl,
  unrealizedPct,
  dailyPnl,
}: AssetSummaryProps) {
  const cashRatio = totalAsset > 0 ? totalCash / totalAsset : 0
  const stockRatio = totalAsset > 0 ? stockValue / totalAsset : 0

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <span className="text-[13px] text-ink-3">총자산</span>
        <span className="text-[32px] font-bold leading-none tracking-[-0.02em] tabular-nums text-ink-1">
          {usd(totalAsset)}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px]">
        <dt className="text-ink-3">미실현 손익</dt>
        <dt className="text-ink-3">일간 손익</dt>
        <dd className={`tabular-nums text-[15px] font-semibold ${directionClass(unrealizedPnl)}`}>
          {directionMark(unrealizedPnl)} {signedUsd(unrealizedPnl)}{' '}
          <span className="text-[13px] font-normal">({signedPct(unrealizedPct)})</span>
        </dd>
        <dd className={`tabular-nums text-[15px] font-semibold ${dailyPnl == null ? 'text-ink-3' : directionClass(dailyPnl)}`}>
          {dailyPnl == null ? '—' : `${directionMark(dailyPnl)} ${signedUsd(dailyPnl)}`}
        </dd>
      </dl>

      <div className="flex flex-col gap-2">
        {/* 현금 · 주식은 범주라서 가격색 · 상태색을 쓰지 않고 무채 단계로 나눈다 */}
        <div
          className="h-1.5 rounded-full overflow-hidden flex bg-white/[0.08]"
          role="img"
          aria-label={`현금 ${(cashRatio * 100).toFixed(0)}%, 주식 ${(stockRatio * 100).toFixed(0)}%`}
        >
          <div className="h-full bg-ink-3" style={{ width: `${Math.min(cashRatio * 100, 100)}%` }} />
          <div className="h-full bg-ink-1" style={{ width: `${Math.min(stockRatio * 100, 100)}%` }} />
        </div>
        <dl className="grid grid-cols-3 gap-x-4 text-[12.5px]">
          <div className="flex flex-col gap-0.5">
            <dt className="flex items-center gap-1.5 text-ink-3">
              <span className="w-1.5 h-1.5 rounded-full bg-ink-3" aria-hidden="true" />
              현금 <span className="tabular-nums">{(cashRatio * 100).toFixed(0)}%</span>
            </dt>
            <dd className="tabular-nums text-ink-1">{usd(totalCash)}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="flex items-center gap-1.5 text-ink-3">
              <span className="w-1.5 h-1.5 rounded-full bg-ink-1" aria-hidden="true" />
              평가금액 <span className="tabular-nums">{(stockRatio * 100).toFixed(0)}%</span>
            </dt>
            <dd className="tabular-nums text-ink-1">{usd(stockValue)}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-ink-3">주문가능</dt>
            <dd className="tabular-nums text-ink-1">{usd(orderableCash)}</dd>
          </div>
        </dl>
      </div>
    </div>
  )
}
