import { useEffect, useState } from 'react'
import type { StockDetailResponsePayload } from '../../../lib/types/stockDetail'
import { countdownParts } from '../../lib/callScreen'
import { formatDirectPercent, formatEps, formatRevenue } from '../../lib/companyDetailFormatters'
import ScrollEdge from './ScrollEdge'
import { ComingSoon, EmptyState, LoadingBlock } from '../common/StateView'

interface CallBriefingProps {
  detail: StockDetailResponsePayload | null
  loading: boolean
  error: Error | null
  topInset: number
}

/**
 * 시작 전 브리핑 — 콜이 시작되기 전 콜 화면의 주인공 (docs/design/ux.md 콜 준비).
 *
 * 빈 자막 대신 "이 콜을 듣기 전에 알아야 할 것" 을 위에서부터 둔다. 콜 시작까지 남은 시간, 일정,
 * 시장 기대치, 지난 분기 어닝 반응 순서다. AI 사전 요약은 데이터가 없어 자리만 둔다.
 * 콜이 시작되면(첫 자막 도착) 같은 화면이 자막으로 바뀐다.
 */
export default function CallBriefing({ detail, loading, error, topInset }: CallBriefingProps) {
  const next = detail?.nextEarning ?? null
  // 최근 분기부터. 응답 순서에 기대지 않고 발표 시각으로 정렬한다.
  const history = [...(detail?.earningsHistory ?? [])].sort((a, b) => b.announcedAt - a.announcedAt).slice(0, 4)

  return (
    <section className="frost relative h-full rounded-[28px] overflow-hidden" aria-label="시작 전 브리핑">
      <ScrollEdge height={topInset + 12} />
      <div className="absolute inset-0 overflow-y-auto" style={{ paddingTop: topInset }}>
        <div className="px-8 pt-4 pb-10 flex flex-col gap-8 max-w-[760px]">
          {loading && !detail ? (
            <LoadingBlock lines={6} lineHeight={18} />
          ) : error && !detail ? (
            <EmptyState message="종목 정보를 불러오지 못했습니다. 콜이 시작되면 자막은 그대로 들어옵니다." />
          ) : (
            <>
              <Countdown next={next} />

              <div className="grid grid-cols-2 gap-6">
                <Block title="시장 기대치">
                  {next ? (
                    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[14px]">
                      <dt className="text-ink-3">EPS 컨센서스</dt>
                      <dd className="tabular-nums text-right text-ink-1">{formatEps(next.epsEstimate)}</dd>
                      <dt className="text-ink-3">매출 컨센서스</dt>
                      <dd className="tabular-nums text-right text-ink-1">{formatRevenue(next.revenueEstimate)}</dd>
                    </dl>
                  ) : (
                    <p className="text-[13px] text-ink-3">다음 실적 일정이 잡히면 기대치를 보여 줍니다.</p>
                  )}
                </Block>

                <Block title="최근 어닝 반응">
                  {history.length === 0 ? (
                    <p className="text-[13px] text-ink-3">지난 실적 기록이 없습니다.</p>
                  ) : (
                    <ul className="flex flex-col gap-2 text-[14px]">
                      {history.map((row) => (
                        <li key={`${row.fiscalPeriodLabel}-${row.announcedAt}`} className="flex items-baseline justify-between gap-3">
                          <span className="text-ink-2">{row.fiscalPeriodLabel}</span>
                          <span className="flex items-baseline gap-3">
                            <span className="tabular-nums text-[12px] text-ink-3">
                              EPS {formatEps(row.epsEstimate)} → {formatEps(row.epsActual)}
                            </span>
                            <Reaction value={row.priceReactionPercent} />
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Block>
              </div>

              <ComingSoon title="AI 사전 요약" note="콜 전에 짚어 볼 쟁점을 정리하는 기능은 준비 중입니다" />
            </>
          )}
        </div>
      </div>
    </section>
  )
}

function Countdown({ next }: { next: StockDetailResponsePayload['nextEarning'] }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  if (!next) {
    return (
      <div className="flex flex-col gap-2">
        <span className="text-[13px] text-ink-3">다음 콜</span>
        <span className="text-[24px] font-bold text-ink-1">예정된 실적 발표가 없습니다</span>
        <span className="text-[13px] text-ink-3">콜이 시작되면 이 화면이 자막으로 바뀝니다.</span>
      </div>
    )
  }

  const parts = countdownParts(next.scheduledAt, now)
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[13px] text-ink-3">콜 시작까지</span>
      {parts ? (
        <span className="num text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink-1" aria-live="off">
          {parts.days > 0 && (
            <>
              {parts.days}
              <span className="font-sans text-[28px] text-ink-2">일 </span>
            </>
          )}
          {String(parts.hours).padStart(2, '0')}:{String(parts.minutes).padStart(2, '0')}:
          {String(parts.seconds).padStart(2, '0')}
        </span>
      ) : (
        <span className="text-[24px] font-bold text-ink-1">예정 시각이 지났습니다 · 첫 자막을 기다립니다</span>
      )}
      <span className="text-[14px] text-ink-2">
        {formatKst(next.scheduledAt)} KST
        <span className="text-ink-3"> (미 동부 {formatEt(next.scheduledAt)})</span>
        <span className="text-ink-3"> · {next.confirmed ? '확정' : '예정'}</span>
      </span>
    </div>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <span className="text-[13px] font-semibold text-ink-2">{title}</span>
      {children}
    </div>
  )
}

function Reaction({ value }: { value: number | null }) {
  if (value == null || !Number.isFinite(value)) return <span className="tabular-nums text-ink-3 w-16 text-right">—</span>
  const up = value >= 0
  return (
    <span className="tabular-nums font-semibold w-16 text-right" style={{ color: up ? 'var(--up)' : 'var(--down)' }}>
      {up ? '▲' : '▼'} {formatDirectPercent(Math.abs(value))}
    </span>
  )
}

const KST = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'long',
  day: 'numeric',
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
})

const ET = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'America/New_York',
  hour: 'numeric',
  minute: '2-digit',
})

function formatKst(sec: number): string {
  return KST.format(new Date(sec * 1000))
}

function formatEt(sec: number): string {
  return ET.format(new Date(sec * 1000))
}
