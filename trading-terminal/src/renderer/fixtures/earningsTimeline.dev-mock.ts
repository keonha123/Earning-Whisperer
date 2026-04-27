/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * EarningsTimeline 컴포넌트가 표시하는 어닝콜 일정 더미값.
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 컴포넌트가 빈 placeholder ("일정 동기화 중") 표시.
 *
 * 추후 백엔드 PR:
 *   - 어닝 일정 IPC 채널 (`EARNINGS_GET_UPCOMING` 등) 추가 예정.
 * ========================================================================== */

export type EarningsGroupKind = 'live' | 'today' | 'tomorrow' | 'week'

export interface EarningsEvent {
  ticker: string
  name: string
  /** 표시용 시간 라벨 (예: "오후 5:00 PM", "금 오전 6:00 AM"). KST 기준. */
  timeLabel: string
  /** 시간대 prefix (예: "오후", "금 오전"). 디자인 캔버스의 `.tl-right .when` 매칭. */
  whenLabel?: string
  /** 정확한 시각 (예: "5:00 PM"). `.tl-right .cd` 매칭. */
  clockLabel?: string
}

export interface EarningsLiveEvent extends EarningsEvent {
  /** 진행 경과 (예: "25:14"). */
  elapsed: string
  /** 회차/콜 라벨 (예: "Q3 FY25 Earnings Call"). */
  callLabel: string
}

export interface EarningsGroup {
  kind: Exclude<EarningsGroupKind, 'live'>
  /** 그룹 라벨 ("오늘", "내일", "이번 주"). */
  label: string
  events: EarningsEvent[]
}

export interface EarningsTimelineFixture {
  live: EarningsLiveEvent | null
  groups: EarningsGroup[]
}

export const earningsTimelineDevMock: EarningsTimelineFixture = {
  live: {
    ticker: 'NVDA',
    name: 'NVIDIA Corp.',
    timeLabel: '진행중',
    elapsed: '25:14',
    callLabel: 'Q3 FY25 Earnings Call',
  },
  groups: [
    {
      kind: 'today',
      label: '오늘',
      events: [
        {
          ticker: 'TSLA',
          name: 'Tesla Inc.',
          timeLabel: '오후 5:00 PM',
          whenLabel: '오후',
          clockLabel: '5:00 PM',
        },
        {
          ticker: 'AMZN',
          name: 'Amazon.com Inc.',
          timeLabel: '오후 5:00 PM',
          whenLabel: '오후',
          clockLabel: '5:00 PM',
        },
      ],
    },
    {
      kind: 'tomorrow',
      label: '내일',
      events: [
        {
          ticker: 'MSFT',
          name: 'Microsoft Corp.',
          timeLabel: '오전 6:30 AM',
          whenLabel: '오전',
          clockLabel: '6:30 AM',
        },
      ],
    },
    {
      kind: 'week',
      label: '이번 주',
      events: [
        {
          ticker: 'META',
          name: 'Meta Platforms',
          timeLabel: '금 오전 6:00 AM',
          whenLabel: '금 오전',
          clockLabel: '6:00 AM',
        },
        {
          ticker: 'GOOGL',
          name: 'Alphabet Inc.',
          timeLabel: '금 오전 7:00 AM',
          whenLabel: '금 오전',
          clockLabel: '7:00 AM',
        },
      ],
    },
  ],
} as const
