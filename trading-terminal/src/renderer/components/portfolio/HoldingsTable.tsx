import type { ReactNode } from 'react'
import CompanyLogo from '../common/CompanyLogo'
import { EmptyState } from '../common/StateView'
import type { EarningsTimelineStatus } from '../../hooks/useEarningsTimeline'
import { directionClass, directionMark, signedPct, signedUsd, usd } from './format'

/** 보유 종목의 다가오는 콜. 일정이 없으면 null. */
export type UpcomingCall = { kind: 'live' } | { kind: 'scheduled'; at: number } | null

export interface HoldingRow {
  ticker: string
  name: string
  qty: number
  avgPrice: number
  currentPrice: number
  /** 전일 종가를 모르면 null. */
  dailyChangePct: number | null
  marketValue: number
  /** 총자산(현금 포함) 대비 비중, 0~1. */
  weight: number
  unrealizedPnl: number
  unrealizedPct: number
  call: UpcomingCall
  logoBg?: string
  logoFg?: string
  logoLabel?: string
}

interface HoldingsTableProps {
  rows: HoldingRow[]
  /** 행을 누르면 종목 브리핑을 연다. */
  onRowClick: (ticker: string) => void
  callStatus: EarningsTimelineStatus
  onRetryCalls: () => void
}

/**
 * 보유 종목 표 — 예전 캐러셀의 "종목 비중" · 종목별 손익을 열로 펼쳤다.
 * 관심 종목은 홈 · 종목 화면이 맡아서 이 표에는 두지 않는다.
 */
export default function HoldingsTable({ rows, onRowClick, callStatus, onRetryCalls }: HoldingsTableProps) {
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex items-center justify-between gap-3 px-6 pt-5 pb-3">
        <h2 className="text-[18px] font-semibold text-ink-1">
          보유 종목 <span className="tabular-nums text-ink-3 font-normal">{rows.length}</span>
        </h2>
        {callStatus === 'error' && (
          <span className="flex items-center gap-2 text-[12.5px] text-ink-3">
            <span className="text-danger">콜 일정을 불러오지 못했습니다</span>
            <button type="button" className="gbtn gbtn-sm" onClick={onRetryCalls}>
              다시 시도
            </button>
          </span>
        )}
      </div>
      {rows.length === 0 ? (
        <EmptyState message="보유 종목이 없습니다. 주문이 체결되면 여기에 표시됩니다." />
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto px-3 pb-3">
          <table className="w-full border-separate border-spacing-0 text-[13px]">
            <caption className="sr-only">보유 종목 목록</caption>
            <thead>
              <tr>
                <Th align="left">종목</Th>
                <Th>수량</Th>
                <Th>평균가</Th>
                <Th>현재가</Th>
                <Th>일간</Th>
                <Th>평가금액</Th>
                <Th>비중</Th>
                <Th>미실현 손익</Th>
                <Th>다가오는 콜</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Row key={row.ticker} row={row} callStatus={callStatus} onClick={onRowClick} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** 머리 행은 스크롤해도 남는다. 바탕은 서리 유리가 창 바탕 위에 겹친 색이라 판과 띠가 지지 않는다. */
function Th({ children, align = 'right' }: { children: ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      scope="col"
      className={`sticky top-0 z-[1] bg-[#17181b] px-3 h-9 text-[12px] font-medium text-ink-3 whitespace-nowrap
                  border-b border-white/[0.08] ${align === 'left' ? 'text-left' : 'text-right'}`}
    >
      {children}
    </th>
  )
}

function Row({
  row,
  callStatus,
  onClick,
}: {
  row: HoldingRow
  callStatus: EarningsTimelineStatus
  onClick: (ticker: string) => void
}) {
  const td = 'px-3 h-12 border-b border-white/[0.06] text-right tabular-nums whitespace-nowrap'
  return (
    // 행 어디를 눌러도 열리지만, 키보드 · 화면 낭독기는 종목 셀의 버튼으로 연다 (표 구조를 지키기 위해 행에 role 을 주지 않는다)
    <tr
      onClick={() => onClick(row.ticker)}
      className="cursor-pointer transition-colors duration-200 hover:bg-white/[0.04] focus-within:bg-white/[0.06]"
    >
      <td className="px-3 h-12 border-b border-white/[0.06]">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onClick(row.ticker)
          }}
          aria-label={`${row.ticker} ${row.name} 종목 브리핑 열기`}
          className="flex items-center gap-2.5 min-w-0 text-left rounded-[10px]
                     focus-visible:outline focus-visible:outline-2 focus-visible:outline-gold-hi focus-visible:outline-offset-[3px]"
        >
          <CompanyLogo ticker={row.ticker} label={row.logoLabel} bg={row.logoBg} fg={row.logoFg} size={26} />
          <span className="min-w-0">
            <span className="block num text-[13px] font-semibold text-ink-1">{row.ticker}</span>
            <span className="block text-[12px] text-ink-3 truncate max-w-[200px]">{row.name}</span>
          </span>
        </button>
      </td>
      <td className={`${td} text-ink-2`}>{row.qty.toLocaleString()}주</td>
      <td className={`${td} text-ink-2`}>{usd(row.avgPrice)}</td>
      <td className={`${td} text-ink-1`}>{usd(row.currentPrice)}</td>
      <td className={`${td} ${row.dailyChangePct == null ? 'text-ink-3' : directionClass(row.dailyChangePct)}`}>
        {row.dailyChangePct == null ? '—' : `${directionMark(row.dailyChangePct)} ${signedPct(row.dailyChangePct)}`}
      </td>
      <td className={`${td} text-ink-1`}>{usd(row.marketValue)}</td>
      <td className={`${td} text-ink-2`}>{(row.weight * 100).toFixed(1)}%</td>
      <td className={`${td} ${directionClass(row.unrealizedPnl)}`}>
        <div>{signedUsd(row.unrealizedPnl)}</div>
        <div className="text-[12px]">{signedPct(row.unrealizedPct)}</div>
      </td>
      <td className={td}>
        <CallCell call={row.call} status={callStatus} />
      </td>
    </tr>
  )
}

const KST_DATE = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric' })
const KST_DAY_KEY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' })

function CallCell({ call, status }: { call: UpcomingCall; status: EarningsTimelineStatus }) {
  if (status === 'loading') return <span className="skeleton inline-block w-16 h-3.5 align-middle" />
  if (call == null) return <span className="text-ink-3">—</span>
  if (call.kind === 'live') {
    // 콜 진행 표시는 무채색. 깜빡임은 쓰지 않는다 (design-system 움직임)
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-ink-1">
        <span className="w-1.5 h-1.5 rounded-full bg-ink-1" aria-hidden="true" />
        진행 중
      </span>
    )
  }
  const when = new Date(call.at * 1000)
  return (
    <span className="inline-flex flex-col items-end leading-tight">
      <span className="text-ink-1">{KST_DATE.format(when)}</span>
      <span className="text-[12px] text-ink-3">{relativeDay(when)}</span>
    </span>
  )
}

/** 한국 시간 날짜 기준으로 오늘 · 내일 · N일 후. 지난 일정이 남아 있으면 오늘로 읽히지 않게 따로 쓴다. */
function relativeDay(when: Date): string {
  const days = Math.round(
    (Date.parse(KST_DAY_KEY.format(when)) - Date.parse(KST_DAY_KEY.format(new Date()))) / 86_400_000,
  )
  if (days < 0) return '지난 일정'
  if (days === 0) return '오늘'
  if (days === 1) return '내일'
  return `${days}일 후`
}
