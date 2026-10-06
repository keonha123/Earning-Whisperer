import { useEffect, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
import { pickXLabels, pickYTicks } from '../../lib/chartUtils'
import SegmentedControl from '../common/SegmentedControl'
import { EmptyState, LoadingBlock } from '../common/StateView'
import MiniLineChart from '../dashboard/MiniLineChart'
import { directionClass, signedPct, signedUsd, usd } from './format'

type RangeId = '7' | '30' | '90'

const RANGES: { id: RangeId; label: string }[] = [
  { id: '7', label: '7일' },
  { id: '30', label: '30일' },
  { id: '90', label: '90일' },
]

/**
 * 자산 추이 — 계좌 동기화 때 하루 한 건씩 쌓이는 자산 기록을 기간별로 그린다.
 *
 * 빈 배열은 "아직 안 왔다" 와 "기록이 하나도 없다" 를 모두 뜻해서 상태를 따로 든다.
 * 그러지 않으면 실패해도 화면이 "불러오는 중" 에 머문다. 실패하면 마지막으로 받은 추이를 남기고 위에 알린다.
 */
export default function AssetTrendCard() {
  const [range, setRange] = useState<RangeId>('30')
  /** 마지막으로 받은 추이와 그 기간. 실패해도 지우지 않는다. */
  const [loaded, setLoaded] = useState<{ range: RangeId; points: { date: string; price: number }[] } | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    ipc
      .invoke<{ date: string; totalAssetUsd: number }[]>(IPC_CHANNELS.KIS_GET_ASSET_TIMESERIES, {
        days: Number(range),
      })
      .then((res) => {
        if (cancelled) return
        setLoaded({ range, points: res.map((p) => ({ date: p.date.slice(5), price: p.totalAssetUsd })) })
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [range, attempt])

  return (
    <section className="glass rim on-glass rounded-[28px] p-6 flex flex-col gap-4 min-h-0" aria-label="자산 추이">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[18px] font-semibold text-ink-1">자산 추이</h2>
        <SegmentedControl items={RANGES} activeId={range} onChange={setRange} />
      </div>
      <div className="flex-1 min-h-0 flex flex-col">
        {status === 'loading' ? (
          <LoadingBlock lines={4} lineHeight={22} />
        ) : status === 'error' && loaded != null && loaded.points.length > 0 ? (
          <>
            <div role="alert" className="mb-3 flex items-center gap-3 text-[12.5px]">
              <span className="text-danger font-semibold">조회 실패</span>
              <span className="text-ink-2 min-w-0">
                {loaded.range === range
                  ? '추이를 새로 불러오지 못했습니다. 아래는 마지막으로 받은 값입니다'
                  : `${range}일 추이를 불러오지 못했습니다. 아래는 ${loaded.range}일 추이입니다`}
              </span>
              <button type="button" className="gbtn gbtn-sm ml-auto shrink-0" onClick={() => setAttempt((n) => n + 1)}>
                다시 시도
              </button>
            </div>
            <TrendChart points={loaded.points} />
          </>
        ) : status === 'error' ? (
          <EmptyState
            message="자산 추이를 불러오지 못했습니다."
            action={
              <button type="button" className="gbtn gbtn-sm" onClick={() => setAttempt((n) => n + 1)}>
                다시 시도
              </button>
            }
          />
        ) : loaded == null || loaded.points.length === 0 ? (
          <EmptyState message={`최근 ${range}일간 자산 기록이 없습니다. 계좌를 동기화할 때마다 하루 한 건씩 쌓입니다.`} />
        ) : (
          <TrendChart points={loaded.points} />
        )}
      </div>
    </section>
  )
}

function TrendChart({ points }: { points: { date: string; price: number }[] }) {
  const prices = points.map((p) => p.price)
  const start = prices[0]
  const change = prices[prices.length - 1] - start
  const changePct = start > 0 ? (change / start) * 100 : 0

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-3">
      <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]">
        <Stat label="시작" value={usd(start)} />
        <Stat label="고점" value={usd(Math.max(...prices))} />
        <Stat label="저점" value={usd(Math.min(...prices))} />
        <Stat
          label="기간 손익"
          value={`${signedUsd(change)} (${signedPct(changePct)})`}
          className={directionClass(change)}
        />
      </dl>
      <div className="relative flex-1 min-h-[120px]">
        <div className="absolute left-0 top-0 bottom-5 w-[68px] flex flex-col justify-between text-right pr-2 text-[11px] tabular-nums text-ink-3">
          {/* 추이가 평탄하면 눈금이 같은 값으로 반올림돼 key 가 겹친다. 위치가 정체성이라 index 를 섞는다 */}
          {pickYTicks(prices, 4, tickStep(prices)).map((y, i) => (
            <span key={`${y}-${i}`}>${y.toLocaleString('en-US')}</span>
          ))}
        </div>
        <div className="absolute left-[76px] right-0 top-1 bottom-6">
          <MiniLineChart
            points={points}
            color={change > 0 ? 'accent' : change < 0 ? 'sell' : 'neutral'}
            viewWidth={600}
            viewHeight={160}
          />
        </div>
        <div className="absolute left-[76px] right-0 bottom-0 flex justify-between num text-[11px] text-ink-3">
          {pickXLabels(points, 5).map((p, i) => (
            <span key={`${p.date}-${i}`}>{p.date}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

/** 눈금 반올림 단위. 7일처럼 폭이 좁은 기간에 100 단위로 반올림하면 눈금이 같은 값으로 겹친다. */
function tickStep(prices: number[]): number {
  const span = Math.max(...prices) - Math.min(...prices)
  return span >= 400 ? 100 : span >= 40 ? 10 : 1
}

function Stat({ label, value, className = 'text-ink-1' }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-ink-3">{label}</dt>
      <dd className={`tabular-nums font-medium ${className}`}>{value}</dd>
    </div>
  )
}
