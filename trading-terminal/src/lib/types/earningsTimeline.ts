export type EarningsGroupKind = 'live' | 'today' | 'tomorrow' | 'week' | 'nextWeek' | 'later'

export interface EarningsEvent {
  ticker: string
  name: string
  /** epoch seconds (UTC). 배지 날짜 표시용. */
  scheduledAt: number
  /** 표시용 전체 시간 라벨 (예: "오후 5:00 PM", "금 오전 6:00 AM"). KST 기준. */
  timeLabel: string
  /** 시간대 prefix (예: "오후", "금 오전"). */
  whenLabel?: string
  /** 시각만 (예: "5:00 PM"). */
  clockLabel?: string
}

export interface EarningsLiveEvent extends EarningsEvent {
  /** 진행 경과 (예: "25:14"). */
  elapsed: string
  /** 콜 라벨 (예: "Earnings Call"). */
  callLabel: string
}

export interface EarningsGroup {
  kind: Exclude<EarningsGroupKind, 'live'>
  label: string
  events: EarningsEvent[]
}

export interface EarningsTimelineData {
  live: EarningsLiveEvent | null
  groups: EarningsGroup[]
}
