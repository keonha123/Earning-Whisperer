import type {
  EarningsTimelineFixture,
  EarningsGroup,
  EarningsGroupKind,
  EarningsLiveEvent,
  EarningsEvent,
} from '../../fixtures/earningsTimeline.dev-mock'

/**
 * 그룹 헤더 좌측 닷의 색/그림자. exhaustive Record 로 정의해 향후 새 kind 추가 시
 * TypeScript 컴파일 에러로 강제 매핑 누락 방지. (live 는 LiveRow 가 별도 처리.)
 */
type EarningsGroupBlockKind = Exclude<EarningsGroupKind, 'live'>
const DOT_BY_KIND: Record<EarningsGroupBlockKind, string> = {
  today: 'bg-warning shadow-[0_0_0_3px_rgba(245,158,11,0.15)]',
  tomorrow: 'bg-info shadow-[0_0_0_3px_rgba(59,130,246,0.15)]',
  week: 'bg-neutral',
}

interface EarningsTimelineProps {
  data: EarningsTimelineFixture
  /** 카드 행 클릭 — ticker 전달 → CompanyDrawer 트리거. */
  onPickTicker?: (ticker: string) => void
  /** LIVE 행 우측 [입장 →] 버튼 — TradingRoom 라우트. */
  onEnterLive?: (ticker: string) => void
  className?: string
}

/**
 * EarningsTimeline — 어닝콜 일정 (LIVE + 오늘/내일/이번 주).
 *
 * 디자인 매칭: DashboardPage.html `.tl` 카드 본체.
 *  - LIVE 섹션: 좌측 2px sell 보더 + pulse 닷.
 *  - 그룹 헤더: 색이 있는 닷 (오늘=warning / 내일=info / 이번주=neutral).
 *  - 각 행 hover: 좌측 2px border-strong + surface-2 배경.
 */
export default function EarningsTimeline({
  data,
  onPickTicker,
  onEnterLive,
  className = '',
}: EarningsTimelineProps) {
  const totalCount =
    (data.live ? 1 : 0) +
    data.groups.reduce((sum, g) => sum + g.events.length, 0)

  return (
    <section
      className={`rounded-lg bg-surface-1 border border-border-subtle flex flex-col min-h-0 overflow-hidden ${className}`}
    >
      {/* Card header */}
      <div className="h-[38px] px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <div className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
          다음 어닝콜
        </div>
        <div className="num text-[11px] text-text-tertiary">KST · {totalCount}건</div>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col">
        {data.live && (
          <LiveRow event={data.live} onEnter={onEnterLive} onPick={onPickTicker} />
        )}
        {data.groups.map((g) => (
          <GroupBlock key={g.kind} group={g} onPick={onPickTicker} />
        ))}
      </div>
    </section>
  )
}

function LiveRow({
  event,
  onPick,
  onEnter,
}: {
  event: EarningsLiveEvent
  onPick?: (t: string) => void
  onEnter?: (t: string) => void
}) {
  return (
    <div
      className="relative border-b border-border-subtle"
      style={{
        backgroundImage:
          'linear-gradient(90deg, rgba(239,68,68,0.06), transparent 60%)',
      }}
    >
      <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-sell" aria-hidden="true" />
      <div className="flex items-center gap-3 px-4 py-3">
        <span
          aria-hidden="true"
          className="w-2.5 h-2.5 rounded-full bg-sell flex-none"
          style={{ boxShadow: '0 0 0 4px rgba(239,68,68,0.2)' }}
        />
        <button
          type="button"
          onClick={() => onPick?.(event.ticker)}
          className="flex-1 min-w-0 text-left"
        >
          <div className="flex items-center gap-2">
            <span className="num text-[15px] font-bold text-text-primary">{event.ticker}</span>
            <span className="text-[12px] text-text-secondary truncate">{event.name}</span>
            <span
              className="num text-[9px] font-bold tracking-[0.06em] inline-flex items-center gap-1
                         px-1.5 py-0.5 rounded-[3px]
                         bg-sell/10 border border-sell/30 text-sell"
            >
              <span className="w-1 h-1 rounded-full bg-sell" /> LIVE
            </span>
          </div>
          <div className="text-[11px] text-text-tertiary mt-0.5">
            <span className="text-sell">{event.timeLabel}</span>
            {' · '}
            <span className="num text-text-secondary">{event.elapsed}</span>
            {' 경과 · '}
            {event.callLabel}
          </div>
        </button>
        <button
          type="button"
          onClick={() => onEnter?.(event.ticker)}
          className="h-[30px] px-3.5 rounded-md bg-sell hover:bg-sell-hover
                     text-white text-[11px] font-bold tracking-[0.04em] shrink-0"
        >
          입장 →
        </button>
      </div>
    </div>
  )
}

function GroupBlock({
  group,
  onPick,
}: {
  group: EarningsGroup
  onPick?: (t: string) => void
}) {
  const dotCls = DOT_BY_KIND[group.kind]

  return (
    <div className="border-b border-border-subtle last:border-b-0 py-1.5">
      <div className="flex items-center gap-2.5 px-4 py-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-tertiary inline-flex items-center gap-1.5">
          <span className={`w-1 h-1 rounded-full ${dotCls}`} aria-hidden="true" />
          {group.label}
        </span>
        <span className="flex-1 h-px bg-border-subtle" aria-hidden="true" />
        <span className="num text-[10px] text-text-disabled">{group.events.length}</span>
      </div>
      {group.events.map((ev) => (
        <Row key={`${group.kind}-${ev.ticker}`} event={ev} onPick={onPick} />
      ))}
    </div>
  )
}

function Row({ event, onPick }: { event: EarningsEvent; onPick?: (t: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onPick?.(event.ticker)}
      className="w-full grid grid-cols-[22px_1fr_auto] gap-2.5 items-center
                 px-4 py-1.5 border-l-2 border-transparent
                 hover:bg-surface-2 hover:border-border-strong text-left
                 transition-colors duration-100"
    >
      <span
        className="w-1.5 h-1.5 rounded-full bg-border-strong ml-1.5"
        aria-hidden="true"
      />
      <span className="flex items-baseline gap-2 min-w-0">
        <span className="num text-[12px] font-semibold text-text-primary">{event.ticker}</span>
        <span className="text-[11px] text-text-tertiary truncate">{event.name}</span>
      </span>
      <span className="flex items-center gap-2.5 num text-[11px] text-text-secondary whitespace-nowrap">
        {event.whenLabel && <span className="text-text-tertiary">{event.whenLabel}</span>}
        <span>{event.clockLabel ?? event.timeLabel}</span>
      </span>
    </button>
  )
}
